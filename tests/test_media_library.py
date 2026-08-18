"""Brochure uploads: the filename is attacker-controlled, so most of this is
about what must NOT be written."""
from __future__ import annotations

import pytest

from media_library import MAX_UPLOAD_BYTES, Brochure, MediaError, MediaLibrary

PDF = b"%PDF-1.4\nfake brochure body\n"


def _library(tmp_path, base_url="https://media.example.com/media"):
    return MediaLibrary(tmp_path, base_url=base_url)


def test_upload_publishes_a_url_on_the_media_host(tmp_path):
    lib = _library(tmp_path)
    saved = lib.save("King_EV_MAX_2027.pdf", PDF)
    assert saved.url == (
        "https://media.example.com/media/brochures/King_EV_MAX_2027.pdf"
    )
    assert (tmp_path / "brochures" / "King_EV_MAX_2027.pdf").read_bytes() == PDF


@pytest.mark.parametrize(
    "attack",
    [
        "../../../etc/passwd.pdf",
        "..\\..\\windows\\system32\\evil.pdf",
        "/etc/cron.d/payload.pdf",
        "subdir/nested.pdf",
    ],
)
def test_a_filename_cannot_escape_the_brochure_directory(tmp_path, attack):
    lib = _library(tmp_path)
    saved = lib.save(attack, PDF)
    written = (tmp_path / "brochures" / saved.filename)
    assert written.exists()
    assert written.resolve().parent == (tmp_path / "brochures").resolve()
    assert "/" not in saved.filename and "\\" not in saved.filename
    assert ".." not in saved.filename


def test_only_pdfs_are_accepted(tmp_path):
    lib = _library(tmp_path)
    with pytest.raises(MediaError, match="Only .pdf"):
        lib.save("payload.svg", PDF)
    with pytest.raises(MediaError, match="Only .pdf"):
        lib.save("noextension", PDF)


def test_a_pdf_extension_is_not_enough(tmp_path):
    """Extension is trivially forged; the magic bytes are checked too."""
    lib = _library(tmp_path)
    with pytest.raises(MediaError, match="not a PDF"):
        lib.save("actually_html.pdf", b"<html><script>alert(1)</script>")


def test_empty_and_oversized_uploads_are_refused(tmp_path):
    lib = _library(tmp_path)
    with pytest.raises(MediaError, match="empty"):
        lib.save("x.pdf", b"")
    too_big = b"%PDF-" + b"0" * MAX_UPLOAD_BYTES
    with pytest.raises(MediaError, match="the limit is"):
        lib.save("big.pdf", too_big)


def test_overwrite_is_opt_in(tmp_path):
    lib = _library(tmp_path)
    lib.save("king.pdf", PDF)
    with pytest.raises(MediaError, match="already exists"):
        lib.save("king.pdf", PDF)
    replaced = lib.save("king.pdf", b"%PDF-1.7\nnewer\n", overwrite=True)
    assert replaced.size_bytes == len(b"%PDF-1.7\nnewer\n")


def test_a_failed_write_leaves_no_partial_file(tmp_path):
    """Staging means nginx can never serve a half-written brochure."""
    lib = _library(tmp_path)
    lib.save("king.pdf", PDF)
    leftovers = [p.name for p in (tmp_path / "brochures").iterdir()
                 if p.name.startswith(".")]
    assert leftovers == []


def test_listing_reports_size_and_url(tmp_path):
    lib = _library(tmp_path)
    lib.save("a.pdf", PDF)
    lib.save("b.pdf", PDF)
    (tmp_path / "brochures" / "notes.txt").write_text("ignore me")

    items = lib.list()
    assert [i.filename for i in items] == ["a.pdf", "b.pdf"]  # txt excluded
    assert all(isinstance(i, Brochure) and i.size_bytes == len(PDF) for i in items)


def test_listing_an_empty_library(tmp_path):
    assert _library(tmp_path).list() == []


def test_delete(tmp_path):
    lib = _library(tmp_path)
    lib.save("gone.pdf", PDF)
    assert lib.delete("gone.pdf") is True
    assert lib.delete("gone.pdf") is False


def test_delete_cannot_reach_outside(tmp_path):
    """A .pdf name, so this exercises the path logic rather than tripping the
    extension guard first."""
    lib = _library(tmp_path)
    victim = tmp_path / "important.pdf"          # sibling of brochures/
    victim.write_bytes(PDF)

    assert lib.delete("../important.pdf") is False
    assert victim.exists()


def test_delete_refuses_a_non_pdf_name_outright(tmp_path):
    lib = _library(tmp_path)
    victim = tmp_path / "leads.csv"
    victim.write_text("do not delete me")
    with pytest.raises(MediaError, match="Only .pdf"):
        lib.delete("../leads.csv")
    assert victim.exists()


def test_no_media_host_configured_yields_no_url(tmp_path):
    lib = _library(tmp_path, base_url="")
    assert lib.save("a.pdf", PDF).url == ""
