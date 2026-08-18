"""Read and prune the Gemini File Search store the bot grounds its answers on.

Until now nothing in this codebase ever listed the store's contents: documents
went in via ``index_document.py`` and there was no inventory, no way to see what
the bot was grounding on, and no way to remove anything.

That matters because indexing has **no upsert**. Re-uploading a corrected
document adds a second copy rather than replacing the first, and both stay
retrievable — so the model can ground on superseded text with nothing to
indicate which version it used. Deleting the stale copy is the only fix, and
this module is what makes that possible.

Adding or removing a document takes effect on the next customer message: the
store name is sent with each request and resolved server-side, so there is no
cache to bust and no restart needed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import config


# Well above the largest TVS brochure (9.2 MB) and inside the 100 MB body
# limit of the tunnel in front of the admin app.
MAX_DOCUMENT_BYTES = 30 * 1024 * 1024


class KnowledgeBaseError(RuntimeError):
    """Reportable failure — the message is safe to show an admin."""


@dataclass(frozen=True)
class KbDocument:
    document_id: str
    name: str
    display_name: str
    state: str
    size_bytes: int
    mime_type: str
    create_time: str
    update_time: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "name": self.name,
            "display_name": self.display_name,
            "state": self.state,
            "size_bytes": self.size_bytes,
            "mime_type": self.mime_type,
            "create_time": self.create_time,
            "update_time": self.update_time,
        }


def _text(value: Any) -> str:
    """Enum members, datetimes and None all have to survive to JSON."""
    if value is None:
        return ""
    return getattr(value, "value", None) or str(value)


def document_id_of(name: str) -> str:
    """Last path segment of ``fileSearchStores/x/documents/y``.

    Used as the URL-safe handle, since the full resource name contains slashes.
    """
    return (name or "").strip().rstrip("/").rsplit("/", 1)[-1].strip()


class KnowledgeBase:
    """Inventory and pruning for one File Search store."""

    def __init__(
        self,
        *,
        client_factory: Callable[[], Any] | None = None,
        store_name: str | None = None,
    ):
        self._client_factory = client_factory
        self._store_name = store_name

    @property
    def store_name(self) -> str:
        if self._store_name is not None:
            return self._store_name
        return config.FILE_SEARCH_STORE

    def _client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        import rag

        client = rag.get_client()
        if client is None:
            raise KnowledgeBaseError(
                "No Gemini API key is configured, so the knowledge base "
                "cannot be read."
            )
        return client

    def _require_store(self) -> str:
        store = self.store_name
        if not store:
            raise KnowledgeBaseError(
                "FILE_SEARCH_STORE is not set, so there is no knowledge base "
                "to read."
            )
        return store

    def documents(self) -> list[KbDocument]:
        store = self._require_store()
        try:
            pages = self._client().file_search_stores.documents.list(parent=store)
        except Exception as exc:
            raise KnowledgeBaseError(f"Could not list documents: {exc}") from exc

        found: list[KbDocument] = []
        for document in pages:
            name = _text(getattr(document, "name", ""))
            found.append(
                KbDocument(
                    document_id=document_id_of(name),
                    name=name,
                    display_name=_text(getattr(document, "display_name", "")),
                    state=_text(getattr(document, "state", "")),
                    size_bytes=int(getattr(document, "size_bytes", 0) or 0),
                    mime_type=_text(getattr(document, "mime_type", "")),
                    create_time=_text(getattr(document, "create_time", "")),
                    update_time=_text(getattr(document, "update_time", "")),
                )
            )
        return found

    def summary(self) -> dict[str, Any]:
        """Store totals plus every document, newest first.

        ``duplicate_display_names`` is the point of this endpoint: because
        indexing never replaces, a name appearing twice means two copies are
        live and the model may be citing the older one.
        """
        store = self._require_store()
        documents = self.documents()

        counts: dict[str, int] = {}
        for document in documents:
            if document.display_name:
                counts[document.display_name] = counts.get(document.display_name, 0) + 1
        duplicates = sorted(name for name, n in counts.items() if n > 1)

        stats: dict[str, Any] = {}
        try:
            detail = self._client().file_search_stores.get(name=store)
            stats = {
                "display_name": _text(getattr(detail, "display_name", "")),
                "active_documents": getattr(detail, "active_documents_count", None),
                "pending_documents": getattr(detail, "pending_documents_count", None),
                "failed_documents": getattr(detail, "failed_documents_count", None),
                "size_bytes": getattr(detail, "size_bytes", None),
            }
        except Exception:
            # Store metadata is a nicety; the document list is the point.
            stats = {}

        return {
            "store": store,
            "document_count": len(documents),
            "duplicate_display_names": duplicates,
            "total_size_bytes": sum(d.size_bytes for d in documents),
            **stats,
            "documents": sorted(
                (d.as_dict() for d in documents),
                key=lambda d: d["create_time"],
                reverse=True,
            ),
        }

    def add(
        self,
        filename: str,
        content: bytes,
        *,
        display_name: str = "",
        replace: bool = False,
    ) -> dict[str, Any]:
        """Index a document. Returns once uploaded, not once searchable.

        Indexing is a long-running operation that can take minutes, but the
        upload itself is seconds. Waiting for indexing would hold the HTTP
        request open long enough for the tunnel in front of this app to drop
        it, so we return as soon as the file is accepted. The document shows
        as PENDING in ``summary()`` and becomes ACTIVE on its own.

        ``replace`` deletes any existing documents with the same display name
        **after** the new one is accepted. Indexing has no upsert, so without
        this a corrected document simply joins the stale one and the model can
        ground on either.
        """
        store = self._require_store()
        name = (display_name or filename or "").strip()
        if not name:
            raise KnowledgeBaseError("A filename or display name is required.")
        if not content:
            raise KnowledgeBaseError("The uploaded file is empty.")
        if len(content) > MAX_DOCUMENT_BYTES:
            raise KnowledgeBaseError(
                f"File is {len(content) / 1_048_576:.1f} MB; the limit is "
                f"{MAX_DOCUMENT_BYTES // 1_048_576} MB."
            )

        superseded = (
            [d for d in self.documents() if d.display_name == name]
            if replace
            else []
        )

        import tempfile
        from pathlib import Path as _Path

        suffix = _Path(name).suffix or ".pdf"
        client = self._client()
        with tempfile.NamedTemporaryFile(suffix=suffix) as handle:
            handle.write(content)
            handle.flush()
            try:
                client.file_search_stores.upload_to_file_search_store(
                    file_search_store_name=store,
                    file=handle.name,
                    config={"display_name": name},
                )
            except Exception as exc:
                raise KnowledgeBaseError(f"Could not index {name}: {exc}") from exc

        replaced: list[str] = []
        for stale in superseded:
            # Only after the new copy is safely in: deleting first would leave
            # the bot with no source at all if the upload then failed.
            try:
                client.file_search_stores.documents.delete(name=stale.name)
                replaced.append(stale.document_id)
            except Exception:
                # The new document is live; a failed cleanup is a duplicate to
                # tidy later, not a reason to fail the request.
                pass

        return {
            "display_name": name,
            "size_bytes": len(content),
            "state": "STATE_PENDING",
            "indexing": True,
            "replaced_document_ids": replaced,
        }

    def delete(self, document_id: str) -> bool:
        """Remove one document. False when it is not in this store.

        Scoped deliberately: the id is combined with *our* store name rather
        than accepting a full resource name, so this cannot reach a document
        in some other store.
        """
        store = self._require_store()
        wanted = document_id_of(document_id)
        if not wanted:
            raise KnowledgeBaseError("A document id is required.")

        target = next(
            (d for d in self.documents() if d.document_id == wanted), None
        )
        if target is None:
            return False
        try:
            self._client().file_search_stores.documents.delete(name=target.name)
        except Exception as exc:
            raise KnowledgeBaseError(f"Could not delete {wanted}: {exc}") from exc
        return True
