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
        outer = self

        class _Documents:
            def list(self, *, parent):
                if outer._list_raises:
                    raise outer._list_raises
                assert parent == STORE
                return iter(outer._documents)

            def delete(self, *, name):
                if outer._delete_raises:
                    raise outer._delete_raises
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
