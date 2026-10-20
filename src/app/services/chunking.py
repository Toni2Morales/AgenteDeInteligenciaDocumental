"""Text chunking for semantic retrieval.

Splits the extracted text of a document into overlapping fragments while
preserving the original page number and the position of each fragment. Chunking
is deterministic: the same text always produces the same fragments, which is
what makes re-indexing idempotent.

Pages are never merged. A fragment always belongs to exactly one page, so a
citation can always point at a single, verifiable page.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.schemas.chunk import ChunkInput
from app.schemas.document import PageText

_PARAGRAPH_SEPARATOR = "\n"


@dataclass(frozen=True)
class ChunkingConfig:
    """Limits applied when splitting text."""

    size_chars: int = 900
    overlap_chars: int = 150


def _iter_paragraphs(text: str) -> Iterable[str]:
    """Yield non-empty trimmed paragraphs of a page."""
    for block in text.split(_PARAGRAPH_SEPARATOR):
        paragraph = block.strip()
        if paragraph:
            yield paragraph


def _split_long_paragraph(paragraph: str, size_chars: int, overlap_chars: int) -> list[str]:
    """Split a paragraph that does not fit in a single chunk.

    The split is made on whitespace boundaries when possible and consecutive
    pieces share ``overlap_chars`` characters so context is not lost at the cut.
    """
    if len(paragraph) <= size_chars:
        return [paragraph]

    pieces: list[str] = []
    start = 0
    step = size_chars - overlap_chars
    while start < len(paragraph):
        end = start + size_chars
        piece = paragraph[start:end]
        if end < len(paragraph):
            # Prefer cutting at the last whitespace to avoid splitting words.
            boundary = piece.rfind(" ")
            if boundary > size_chars // 2:
                piece = piece[:boundary]
        pieces.append(piece.strip())
        if end >= len(paragraph):
            break
        start += step
    return [piece for piece in pieces if piece]


def _split_page(text: str, config: ChunkingConfig) -> list[str]:
    """Split one page into chunks of at most ``size_chars`` characters."""
    chunks: list[str] = []
    buffer = ""

    def flush() -> None:
        nonlocal buffer
        if buffer:
            chunks.append(buffer)
            buffer = ""

    for paragraph in _iter_paragraphs(text):
        for piece in _split_long_paragraph(paragraph, config.size_chars, config.overlap_chars):
            if not buffer:
                buffer = piece
                continue
            if len(buffer) + 1 + len(piece) <= config.size_chars:
                buffer = f"{buffer}\n{piece}"
            else:
                flush()
                buffer = piece
    flush()
    return chunks


def chunk_pages(pages: Iterable[PageText], config: ChunkingConfig) -> list[ChunkInput]:
    """Turn extracted pages into chunks ready to be embedded.

    The returned ``position`` is a global, zero-based counter in document order,
    while ``page_number`` keeps the one-based original page of the fragment.
    """
    chunks: list[ChunkInput] = []
    for page in pages:
        for text in _split_page(page.text, config):
            position = len(chunks)
            chunks.append(
                ChunkInput(
                    chunk_uid=f"p{page.page_number}-c{position}",
                    text=text,
                    page_number=page.page_number,
                    position=position,
                    embedding=[],
                    metadata={"char_count": len(text)},
                )
            )
    return chunks
