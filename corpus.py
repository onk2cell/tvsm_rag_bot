"""The knowledge base as one text the model is handed whole.

``knowledge_base/*.md`` is the source of truth for what the bot knows on
the cached-context path (see cached_context.py). This module turns that
folder into a single bundle::

    <document index="1" source="tvs_3w_loan_documents.md">
    ...normalised text...
    </document>

Byte-identical output for identical input is the contract, because the
bundle sits in a provider-side prompt cache and a bundle that differs by
one byte is a new cache: files are sorted by relative path (byte order,
not locale), text is normalised the same way every time, and nothing
time-dependent is written anywhere.

Nothing is skipped silently. A file that is not Markdown or plain text,
one that is not UTF-8, or one that normalises to nothing fails the build
and is named, together with every other failure, in one error.

    python corpus.py            # what would be cached: files, sizes, sha
    python corpus.py --write    # also write build/corpus/corpus.txt
"""
from __future__ import annotations

import hashlib
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_SUFFIXES = frozenset({".md", ".txt"})

# Bump when `render` changes shape: it is part of what the cache key hashes.
FORMAT_VERSION = 1

# Calibrated against Gemini's own count of a corpus like this one (spec
# sheets — numbers, units, table rules — tokenise far denser than prose:
# ~12,100 tokens for 30,844 chars, measured 2026-09-19). An estimate; the
# provider's count on cache creation is the figure that is logged.
CHARS_PER_TOKEN = 2.5

_BLANK_RUN = re.compile(r"\n{3,}")


class CorpusError(RuntimeError):
    """The knowledge base cannot be bundled. The message names every file."""


@dataclass(frozen=True)
class Document:
    index: int
    source: str      # path relative to the corpus root, POSIX separators
    text: str        # normalised
    sha256: str      # of the source bytes

    @property
    def chars(self) -> int:
        return len(self.text)


@dataclass(frozen=True)
class Corpus:
    text: str
    sha256: str
    documents: tuple[Document, ...]

    @property
    def chars(self) -> int:
        return len(self.text)

    @property
    def estimated_tokens(self) -> int:
        return estimate_tokens(self.chars)


def estimate_tokens(chars: int) -> int:
    return math.ceil(chars / CHARS_PER_TOKEN)


def normalise(text: str) -> str:
    """One shape for every document, whatever editor produced it."""
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    text = _BLANK_RUN.sub("\n\n", "\n".join(lines)).strip("\n")
    return text + "\n" if text else ""


def collect(root: Path) -> list[Path]:
    """Every candidate file under ``root``, in an order no filesystem can change."""
    if not root.is_dir():
        raise CorpusError(f"knowledge base directory {root} does not exist")
    files = [
        path for path in root.rglob("*")
        if path.is_file() and not any(part.startswith(".") for part in path.relative_to(root).parts)
    ]
    return sorted(files, key=lambda p: p.relative_to(root).as_posix().encode())


def _extract(path: Path, root: Path) -> tuple[str, str]:
    """(normalised text, sha256 of bytes). Raises with a message naming the file."""
    rel = path.relative_to(root).as_posix()
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise CorpusError(
            f"{rel}: unsupported type {path.suffix!r}; the knowledge base takes "
            f"{', '.join(sorted(SUPPORTED_SUFFIXES))} only"
        )
    data = path.read_bytes()
    try:
        text = normalise(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise CorpusError(f"{rel}: not UTF-8 ({exc})") from exc
    if not text.strip():
        raise CorpusError(f"{rel}: no text after normalisation")
    return text, hashlib.sha256(data).hexdigest()


def render(documents: list[Document]) -> str:
    blocks = []
    for doc in documents:
        blocks.append(
            f'<document index="{doc.index}" source="{doc.source}">\n{doc.text}</document>\n'
        )
    return "\n".join(blocks)


def build(root: str | Path) -> Corpus:
    """Bundle every document under ``root``; every failure reported at once."""
    root = Path(root)
    documents: list[Document] = []
    failures: list[str] = []
    for path in collect(root):
        try:
            text, sha = _extract(path, root)
        except CorpusError as exc:
            failures.append(str(exc))
            continue
        documents.append(Document(
            index=len(documents) + 1,
            source=path.relative_to(root).as_posix(),
            text=text,
            sha256=sha,
        ))
    if failures:
        raise CorpusError(
            f"{len(failures)} file(s) could not be bundled:\n  - " + "\n  - ".join(failures)
        )
    if not documents:
        raise CorpusError(f"no documents under {root}")
    text = render(documents)
    return Corpus(
        text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        documents=tuple(documents),
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("root", nargs="?", default=None,
                        help="knowledge base directory (default: KNOWLEDGE_BASE_DIR)")
    parser.add_argument("--write", action="store_true",
                        help="also write build/corpus/corpus.txt for inspection")
    args = parser.parse_args(argv)

    if args.root is None:
        import config
        args.root = config.KNOWLEDGE_BASE_DIR
    try:
        corpus = build(args.root)
    except CorpusError as exc:
        print(exc, file=sys.stderr)
        return 1
    for doc in corpus.documents:
        print(f"  {doc.index:>2}. {doc.source:<40} {doc.chars:>7,} chars  ~{estimate_tokens(doc.chars):,} tokens")
    print(f"  {len(corpus.documents)} document(s), {corpus.chars:,} chars, "
          f"~{corpus.estimated_tokens:,} tokens, sha256 {corpus.sha256[:16]}")
    if args.write:
        out = Path("build/corpus/corpus.txt")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(corpus.text, encoding="utf-8")
        print(f"  wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
