"""Admin-uploaded media, served by the media host.

``data/media`` is a shared volume: the admin container writes here and the
``tvsm-media-nginx`` container serves the same directory read-only at
``/media/``. So publishing a file is a file write — no CDN account, no third
party, no long-running job.

Two kinds live here:

* ``brochures`` — product PDFs (``data/media/brochures``)
* ``images``    — the share-location how-to cards (``data/media/share_location``)

Uploading does *not* by itself change what the bot sends. An admin still points
``documents.<product>.brochure`` or ``share_location_image.url`` at the returned
URL. That separation is deliberate: publishing a draft must never start sending
it to customers.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import config


class MediaError(ValueError):
    """Rejected upload — the message is safe to show an admin."""


@dataclass(frozen=True)
class MediaKind:
    """One publishable directory and what it will accept."""

    name: str
    subdir: str
    suffixes: frozenset[str]
    # Leading bytes a real file of this type must start with. Trusting the
    # extension alone would let anything through under a .pdf name.
    magic: tuple[bytes, ...]
    max_bytes: int
    label: str


# Brochures run large: the biggest already on disk is 9.2 MB.
BROCHURES = MediaKind(
    name="brochures",
    subdir="brochures",
    suffixes=frozenset({".pdf"}),
    magic=(b"%PDF-",),
    max_bytes=25 * 1024 * 1024,
    label="brochure",
)

# The how-to cards are ~100-120 KB each; 5 MB is generous for a screenshot.
IMAGES = MediaKind(
    name="images",
    subdir="share_location",
    suffixes=frozenset({".jpg", ".jpeg", ".png"}),
    magic=(b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"),
    max_bytes=5 * 1024 * 1024,
    label="image",
)

# Vehicle photos shown to a customer who asks to *see* the product (as
# opposed to the brochure PDF). Uploaded here, then wired to a product via
# admin_config documents[product].images — see client_media_assets.py.
PRODUCT_IMAGES = MediaKind(
    name="product_images",
    subdir="products",
    suffixes=frozenset({".jpg", ".jpeg", ".png"}),
    magic=(b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"),
    max_bytes=5 * 1024 * 1024,
    label="product image",
)

MEDIA_KINDS = {kind.name: kind for kind in (BROCHURES, IMAGES, PRODUCT_IMAGES)}

# Kept for callers that predate the images kind.
MAX_UPLOAD_BYTES = BROCHURES.max_bytes

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(raw: str, kind: MediaKind) -> str:
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
    if suffix not in kind.suffixes:
        allowed = ", ".join(sorted(kind.suffixes))
        raise MediaError(
            f"Only {allowed} files can be uploaded as {kind.name}, "
            f"got {suffix or 'none'}."
        )
    if len(name) > 120:
        name = Path(name).stem[:110] + suffix
    return name


@dataclass(frozen=True)
class MediaFile:
    filename: str
    size_bytes: int
    url: str

    def as_dict(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "url": self.url,
        }


# Older name, kept so existing imports keep working.
Brochure = MediaFile


class MediaLibrary:
    """Read and write one of the directories the media host serves."""

    def __init__(
        self,
        root: Path,
        *,
        kind: MediaKind = BROCHURES,
        base_url: str | None = None,
    ):
        self._root = Path(root)
        self._kind = kind
        self._base_url = base_url

    def for_kind(self, kind: MediaKind) -> "MediaLibrary":
        """Same root and base URL, different directory."""
        return MediaLibrary(self._root, kind=kind, base_url=self._base_url)

    @property
    def kind(self) -> MediaKind:
        return self._kind

    @property
    def directory(self) -> Path:
        return self._root / self._kind.subdir

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
        return f"{base}/{self._kind.subdir}/{filename}"

    def _resolved(self, filename: str) -> Path:
        """Path inside this kind's directory, or refuse."""
        target = (self.directory / safe_filename(filename, self._kind)).resolve()
        if self.directory.resolve() != target.parent:
            raise MediaError(
                f"Refusing to touch a path outside the {self._kind.name} directory."
            )
        return target

    def list(self) -> list[MediaFile]:
        directory = self.directory
        if not directory.exists():
            return []
        return [
            MediaFile(path.name, path.stat().st_size, self.url_for(path.name))
            for path in sorted(directory.iterdir())
            if path.is_file() and path.suffix.lower() in self._kind.suffixes
        ]

    def save(
        self, filename: str, content: bytes, *, overwrite: bool = False
    ) -> MediaFile:
        kind = self._kind
        # Name first: it is the cheapest check and gives the most specific
        # message, so uploading a PDF as an image says "wrong extension"
        # rather than complaining about its leading bytes.
        target = self._resolved(filename)
        if not content:
            raise MediaError("The uploaded file is empty.")
        if len(content) > kind.max_bytes:
            raise MediaError(
                f"File is {len(content) / 1_048_576:.1f} MB; the limit for "
                f"{kind.name} is {kind.max_bytes // 1_048_576} MB."
            )
        if not any(content.startswith(prefix) for prefix in kind.magic):
            raise MediaError(
                f"That file is not a valid {kind.label} "
                f"(its leading bytes do not match {', '.join(sorted(kind.suffixes))})."
            )

        if target.exists() and not overwrite:
            raise MediaError(
                f"{target.name} already exists. Re-send with overwrite=true to replace it."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write beside the target and move into place, so a failed or partial
        # upload can never be served as a truncated file.
        staging = target.with_name(f".{target.name}.part")
        staging.write_bytes(content)
        staging.replace(target)
        return MediaFile(target.name, len(content), self.url_for(target.name))

    def delete(self, filename: str) -> bool:
        target = self._resolved(filename)
        if not target.exists():
            return False
        target.unlink()
        return True
