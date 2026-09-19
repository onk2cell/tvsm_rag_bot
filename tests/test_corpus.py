"""corpus.py — the knowledge base bundled deterministically, failing loudly."""
from __future__ import annotations

import pytest

import corpus


def _write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_bundle_is_byte_identical_for_identical_input(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    for root in (a, b):
        _write(root, "z_last.md", "# Z\n\nlast\n")
        _write(root, "a_first.md", "# A\r\n\r\nfirst   \r\n\r\n\r\n\r\nmore\r\n")
    first, second = corpus.build(a), corpus.build(b)
    assert first.text == second.text
    assert first.sha256 == second.sha256


def test_documents_are_ordered_by_path_and_wrapped_with_source(tmp_path):
    _write(tmp_path, "z.md", "zed\n")
    _write(tmp_path, "sub/a.md", "ay\n")
    built = corpus.build(tmp_path)
    assert [d.source for d in built.documents] == ["sub/a.md", "z.md"]
    assert built.text.startswith('<document index="1" source="sub/a.md">\nay\n</document>\n')
    assert '<document index="2" source="z.md">' in built.text


def test_normalisation_pins_line_endings_whitespace_and_blank_runs():
    assert corpus.normalise("﻿a  \r\nb\r\n\r\n\r\n\r\nc\n\n") == "a\nb\n\nc\n"
    assert corpus.normalise("   \n\n") == ""


def test_every_failure_is_reported_at_once(tmp_path):
    _write(tmp_path, "ok.md", "fine\n")
    _write(tmp_path, "empty.md", "\n\n")
    (tmp_path / "brochure.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "latin1.md").write_bytes("caf\xe9".encode("latin-1"))
    with pytest.raises(corpus.CorpusError) as excinfo:
        corpus.build(tmp_path)
    message = str(excinfo.value)
    assert "3 file(s) could not be bundled" in message
    assert "empty.md: no text" in message
    assert "brochure.pdf: unsupported type" in message
    assert "latin1.md: not UTF-8" in message


def test_dotfiles_are_ignored_and_an_empty_root_fails(tmp_path):
    _write(tmp_path, ".gitkeep", "")
    with pytest.raises(corpus.CorpusError, match="no documents"):
        corpus.build(tmp_path)
    with pytest.raises(corpus.CorpusError, match="does not exist"):
        corpus.build(tmp_path / "missing")


def test_the_real_knowledge_base_bundles():
    built = corpus.build("knowledge_base")
    assert [d.source for d in built.documents] == [
        "tvs_3w_loan_documents.md", "tvs_king_ev_max.md", "tvs_three_wheelers.md",
    ]
    assert 5_000 < built.estimated_tokens < 50_000
    assert "TVS King EV MAX" in built.text and "Partnership Deed" in built.text


def test_cli_lists_documents(capsys):
    assert corpus.main(["knowledge_base"]) == 0
    out = capsys.readouterr().out
    assert "tvs_three_wheelers.md" in out and "3 document(s)" in out
