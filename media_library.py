"""Admin-uploaded brochures, served by the media host.

``data/media`` is a shared volume: the admin container writes here and the
``tvsm-media-nginx`` container serves the same directory read-only at
``/media/``. So publishing a brochure is a file write — no CDN, no third party,
no long-running job.

The public URL is ``CLIENT_MEDIA_BASE_URL`` + ``/brochures/<name>``. Uploading a
file does *not* by itself change what the bot sends: an admin still has to
point ``documents.<product>.brochure`` at the returned URL. That separation is
deliberate — uploading a draft should never silently start sending it.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import config

BROCHURE_DIR = "brochures"

# Brochures run large: the biggest already on disk is 9.2 MB.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

ALLOWED_SUFFIXES = {".pdf"}

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class MediaError(ValueError):
    """Rejected upload — the message is safe to show an admin."""


def safe_filename(raw: str) -> str:
    """Reduce an uploaded filename to something that cannot escape the directory.

    A filename arriving over HTTP is attacker-controlled and is about to become
    a filesystem path, so this is a security boundary, not tidying. Everything
    outside a conservative allowlist is replaced, and only the final path
    component is kept — "../../etc/passwd" cannot survive both steps.
    """
    name = unicodedata.normalize("NFKD", (raw or "").strip())
    name = name.replace("\\", "/").split("/")[-1]  # drop any directory part
    name = _SAFE_NAME.sub("_", name).strip("._-")
    if not name:
        raise MediaError("Filename is empty after sanitising.")

    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_SUFFIXES))
        raise MediaError(f"Only {allowed} files can be uploaded, got {suffix or 'none'}.")
    if len(name) > 120:
        name = Path(name).stem[:110] + suffix
    return name


@dataclass(frozen=True)
class Brochure:
    filename: str
    size_bytes: int
    url: str

    def as_dict(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "url": self.url,
        }


class MediaLibrary:
    """Read and write the brochure directory the media host serves."""

    def __init__(self, root: Path, *, base_url: str | None = None):
        self._root = Path(root)
        self._base_url = base_url

    @property
    def directory(self) -> Path:
        return self._root / BROCHURE_DIR

    def _public_base(self) -> str:
        base = self._base_url
        if base is None:
            base = config.CLIENT_MEDIA_BASE_URL
        return (base or "").rstrip("/")

    def url_for(self, filename: str) -> str:
        base = self._public_base()
        if not base:
            # No media host configured: report it plainly rather than handing
            # back a relative URL WhatsApp cannot fetch.
            return ""
        return f"{base}/{BROCHURE_DIR}/{filename}"

    def _resolved(self, filename: str) -> Path:
        """Path inside the brochure directory, or refuse."""
        target = (self.directory / safe_filename(filename)).resolve()
        root = self.directory.resolve()
        if root != target.parent:
            raise MediaError("Refusing to touch a path outside the brochure directory.")
        return target

    def list(self) -> list[Brochure]:
        directory = self.directory
        if not directory.exists():
            return []
        items = [
            Brochure(path.name, path.stat().st_size, self.url_for(path.name))
            for path in sorted(directory.iterdir())
            if path.is_file() and path.suffix.lower() in ALLOWED_SUFFIXES
        ]
        return items

    def save(self, filename: str, content: bytes, *, overwrite: bool = False) -> Brochure:
        if not content:
            raise MediaError("The uploaded file is empty.")
        if len(content) > MAX_UPLOAD_BYTES:
            raise MediaError(
                f"File is {len(content) / 1_048_576:.1f} MB; the limit is "
                f"{MAX_UPLOAD_BYTES // 1_048_576} MB."
            )
        if not content.startswith(b"%PDF-"):
            # Trusting the extension alone would let anything through.
            raise MediaError("That file is not a PDF (missing the %PDF- header).")

        target = self._resolved(filename)
        if target.exists() and not overwrite:
            raise MediaError(
                f"{target.name} already exists. Re-send with overwrite=true to replace it."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write beside the target and move into place, so a failed or partial
        # upload can never be served as a truncated brochure.
        staging = target.with_name(f".{target.name}.part")
        staging.write_bytes(content)
        staging.replace(target)
        return Brochure(target.name, len(content), self.url_for(target.name))

    def delete(self, filename: str) -> bool:
        target = self._resolved(filename)
        if not target.exists():
            return False
        target.unlink()
        return True
