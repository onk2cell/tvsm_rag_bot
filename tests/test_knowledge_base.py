"""Knowledge-base inventory and pruning.

The point of this module is that indexing never replaces: re-uploading a
revised document leaves both copies retrievable, so duplicates must be visible
and removable.
"""
from __future__ import annotations

import pytest

from knowledge_base import KnowledgeBase, KnowledgeBaseError, document_id_of

STORE = "fileSearchStores/tvsmanual-abc123"


class FakeDocument:
    def __init__(self, doc_id, display_name, *, size=1024, state="STATE_ACTIVE",
                 created="2026-08-01T10:00:00Z"):
        self.name = f"{STORE}/documents/{doc_id}"
        self.display_name = display_name
        self.state = state
        self.size_bytes = size
        self.mime_type = "application/pdf"
        self.create_time = created
        self.update_time = created


class FakeStoreDetail:
    display_name = "tvs-manual"
    active_documents_count = 2
    pending_documents_count = 0
    failed_documents_count = 0
    size_bytes = 2048


class FakeClient:
    def __init__(self, documents, *, list_raises=None, delete_raises=None):
        self._documents = list(documents)
        self._list_raises = list_raises
        self._delete_raises = delete_raises
        self.deleted = []
        self.delete_configs = []
        outer = self

        class _Documents:
            def list(self, *, parent):
                if outer._list_raises:
                    raise outer._list_raises
                assert parent == STORE
                return iter(outer._documents)

            def delete(self, *, name, config=None):
                outer.delete_configs.append(config)
                if outer._delete_raises:
                    raise outer._delete_raises
                # The real API refuses an unforced delete of an indexed
                # document ("Cannot delete non-empty Document"), so the fake
                # refuses it too — an earlier version of this fake accepted
                # one, and the endpoint 502'd in production while green here.
                if not (config or {}).get("force"):
                    raise RuntimeError(
                        "400 FAILED_PRECONDITION. Cannot delete non-empty Document"
                    )
                outer.deleted.append(name)
                outer._documents = [d for d in outer._documents if d.name != name]

        class _Stores:
            documents = _Documents()

            def get(self, *, name):
                return FakeStoreDetail()

        self.file_search_stores = _Stores()


def _kb(documents, **kw):
    client = FakeClient(documents, **kw)
    return KnowledgeBase(client_factory=lambda: client, store_name=STORE), client


def test_document_id_is_the_last_path_segment():
    assert document_id_of(f"{STORE}/documents/xyz789") == "xyz789"
    assert document_id_of("") == ""


def test_lists_what_the_bot_grounds_on():
    kb, _ = _kb([FakeDocument("a1", "price_list.pdf"),
                 FakeDocument("b2", "specs.pdf", size=2048)])
    summary = kb.summary()

    assert summary["store"] == STORE
    assert summary["document_count"] == 2
    assert summary["total_size_bytes"] == 3072
    assert {d["display_name"] for d in summary["documents"]} == {
        "price_list.pdf", "specs.pdf"
    }
    assert summary["documents"][0]["document_id"] in {"a1", "b2"}


def test_duplicates_are_flagged_because_indexing_never_replaces():
    """The whole reason this endpoint exists: two copies of one document mean
    the bot may be citing the superseded one."""
    kb, _ = _kb([
        FakeDocument("old", "price_list.pdf", created="2026-01-01T00:00:00Z"),
        FakeDocument("new", "price_list.pdf", created="2026-08-01T00:00:00Z"),
        FakeDocument("solo", "specs.pdf", created="2026-02-01T00:00:00Z"),
    ])
    summary = kb.summary()
    assert summary["duplicate_display_names"] == ["price_list.pdf"]
    # newest first, so an admin sees the current copy above the stale one
    order = [d["document_id"] for d in summary["documents"]]
    assert order == ["new", "solo", "old"]
    assert order.index("new") < order.index("old")


def test_no_duplicates_reported_when_there_are_none():
    kb, _ = _kb([FakeDocument("a", "one.pdf"), FakeDocument("b", "two.pdf")])
    assert kb.summary()["duplicate_display_names"] == []


def test_store_stats_are_included():
    kb, _ = _kb([FakeDocument("a", "one.pdf")])
    summary = kb.summary()
    assert summary["active_documents"] == 2
    assert summary["display_name"] == "tvs-manual"


def test_delete_removes_the_stale_copy():
    kb, client = _kb([FakeDocument("old", "price_list.pdf"),
                      FakeDocument("new", "price_list.pdf")])
    assert kb.delete("old") is True
    assert client.deleted == [f"{STORE}/documents/old"]
    assert kb.summary()["document_count"] == 1


def test_delete_forces_because_an_indexed_document_is_never_empty():
    """Every document here owns Chunks, so an unforced delete always fails.

    Without ``force`` the API answers 400 FAILED_PRECONDITION ("Cannot delete
    non-empty Document") and the admin endpoint turns that into a 502 — which
    is exactly what it did in production.
    """
    kb, client = _kb([FakeDocument("a1", "price_list.pdf")])
    assert kb.delete("a1") is True
    assert client.delete_configs == [{"force": True}]


def test_delete_reports_a_document_that_is_not_there():
    kb, client = _kb([FakeDocument("a", "one.pdf")])
    assert kb.delete("nope") is False
    assert client.deleted == []


def test_delete_cannot_reach_another_store():
    """A full resource name is reduced to its id and recombined with our own
    store, so a document elsewhere can never be targeted."""
    kb, client = _kb([FakeDocument("a", "one.pdf")])
    assert kb.delete("fileSearchStores/someone-else/documents/a") is True
    assert client.deleted == [f"{STORE}/documents/a"]


def test_delete_requires_an_id():
    kb, _ = _kb([])
    with pytest.raises(KnowledgeBaseError, match="document id is required"):
        kb.delete("   ")


def test_an_unset_store_is_reported_clearly():
    kb = KnowledgeBase(client_factory=lambda: FakeClient([]), store_name="")
    with pytest.raises(KnowledgeBaseError, match="FILE_SEARCH_STORE is not set"):
        kb.summary()


def test_a_missing_api_key_is_reported_clearly(monkeypatch):
    import rag

    monkeypatch.setattr(rag, "get_client", lambda: None)
    kb = KnowledgeBase(store_name=STORE)
    with pytest.raises(KnowledgeBaseError, match="No Gemini API key"):
        kb.summary()


def test_an_api_failure_is_wrapped_not_leaked():
    kb, _ = _kb([], list_raises=RuntimeError("quota exceeded"))
    with pytest.raises(KnowledgeBaseError, match="Could not list documents"):
        kb.summary()


# --- adding documents -------------------------------------------------------


class UploadingClient(FakeClient):
    """FakeClient that records uploads and appends the new document."""

    def __init__(self, documents, *, upload_raises=None):
        super().__init__(documents)
        self.uploads = []
        self._upload_raises = upload_raises
        outer = self

        class _Stores:
            documents = self.file_search_stores.documents

            def get(self, *, name):
                return FakeStoreDetail()

            def upload_to_file_search_store(self, *, file_search_store_name, file, config):
                if outer._upload_raises:
                    raise outer._upload_raises
                import pathlib

                outer.uploads.append(
                    {
                        "store": file_search_store_name,
                        "display_name": config["display_name"],
                        "bytes": pathlib.Path(file).read_bytes(),
                        "suffix": pathlib.Path(file).suffix,
                    }
                )
                outer._documents.append(
                    FakeDocument(f"new{len(outer.uploads)}", config["display_name"])
                )
                return object()

        self.file_search_stores = _Stores()


def _uploading_kb(documents, **kw):
    client = UploadingClient(documents, **kw)
    return KnowledgeBase(client_factory=lambda: client, store_name=STORE), client


def test_add_indexes_a_document():
    kb, client = _uploading_kb([])
    result = kb.add("price_list.pdf", b"%PDF-1.4\nprices\n")

    assert result["display_name"] == "price_list.pdf"
    assert result["indexing"] is True
    assert result["state"] == "STATE_PENDING"
    assert client.uploads[0]["store"] == STORE
    assert client.uploads[0]["bytes"] == b"%PDF-1.4\nprices\n"
    assert client.uploads[0]["suffix"] == ".pdf"


def test_add_does_not_wait_for_indexing_to_finish():
    """Holding the request open for a multi-minute LRO is what the tunnel in
    front of this app drops."""
    kb, _ = _uploading_kb([])
    assert kb.add("a.pdf", b"%PDF-x")["indexing"] is True


def test_display_name_can_be_given_explicitly():
    """index_document.py names documents after the raw CLI path; this lets an
    admin set something sane instead."""
    kb, client = _uploading_kb([])
    kb.add("/tmp/whatever/x9f.pdf", b"%PDF-x", display_name="King EV MAX specs.pdf")
    assert client.uploads[0]["display_name"] == "King EV MAX specs.pdf"


def test_replace_removes_the_superseded_copy():
    kb, client = _uploading_kb([FakeDocument("old", "price_list.pdf")])
    result = kb.add("price_list.pdf", b"%PDF-new", replace=True)

    assert result["replaced_document_ids"] == ["old"]
    assert client.deleted == [f"{STORE}/documents/old"]
    assert [d["display_name"] for d in kb.summary()["documents"]] == ["price_list.pdf"]


def test_without_replace_a_reindex_creates_a_duplicate():
    """The default is additive, matching the API's own behaviour — the flag has
    to be asked for."""
    kb, _ = _uploading_kb([FakeDocument("old", "price_list.pdf")])
    kb.add("price_list.pdf", b"%PDF-new")
    assert kb.summary()["duplicate_display_names"] == ["price_list.pdf"]


def test_the_old_copy_survives_a_failed_upload():
    """Deleting first would leave the bot with no source at all."""
    kb, client = _uploading_kb(
        [FakeDocument("old", "price_list.pdf")],
        upload_raises=RuntimeError("quota exceeded"),
    )
    with pytest.raises(KnowledgeBaseError, match="Could not index"):
        kb.add("price_list.pdf", b"%PDF-new", replace=True)
    assert client.deleted == []
    assert kb.summary()["document_count"] == 1


def test_add_rejects_empty_and_oversized_and_unnamed():
    from knowledge_base import MAX_DOCUMENT_BYTES

    kb, _ = _uploading_kb([])
    with pytest.raises(KnowledgeBaseError, match="empty"):
        kb.add("a.pdf", b"")
    with pytest.raises(KnowledgeBaseError, match="limit is"):
        kb.add("a.pdf", b"x" * (MAX_DOCUMENT_BYTES + 1))
    with pytest.raises(KnowledgeBaseError, match="is required"):
        kb.add("   ", b"%PDF-x")
