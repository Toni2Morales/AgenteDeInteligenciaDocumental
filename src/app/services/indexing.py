"""Document indexing: from PDF bytes to stored, embedded chunks.

The pipeline reuses the existing ingestion, chunking, embedding and repository
modules. Everything is written inside a single transaction, so a failure while
generating or storing embeddings never leaves a half-indexed document behind.

Re-indexing the same document is idempotent: ``replace_chunks`` deletes the
previous chunks for the same embedding model before inserting the new ones, and
the document row is matched by content checksum instead of being duplicated.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from uuid import UUID

from app.db import repositories
from app.schemas.chunk import ChunkInput
from app.services import pdf_ingestion as pdf
from app.services.chunking import ChunkingConfig, chunk_pages
from app.services.embeddings import EmbeddingService
from app.services.ollama import OllamaError


class IndexingError(Exception):
    """Base class for indexing failures."""


class EmbeddingUnavailableError(IndexingError):
    """Embeddings could not be generated (Ollama missing or model error)."""


@dataclass(frozen=True)
class IndexingConfig:
    """Indexing limits applied to every document."""

    max_size_bytes: int
    chunk_size_chars: int
    chunk_overlap_chars: int
    embedding_batch_size: int


@dataclass(frozen=True)
class IndexingResult:
    """Outcome of indexing a document."""

    document_id: UUID
    document_name: str
    page_count: int
    chunk_count: int
    already_indexed: bool


def content_sha256(data: bytes) -> str:
    """Return the content checksum used to detect repeated documents."""
    return hashlib.sha256(data).hexdigest()


def _embed_chunks(
    chunks: list[ChunkInput],
    embeddings: EmbeddingService,
    batch_size: int,
) -> list[ChunkInput]:
    """Return new chunks with their embeddings, sending small batches.

    ``ChunkInput`` is frozen, so a new list is built instead of mutating the
    input. Batching keeps the memory used by ``embed_texts`` bounded.
    """
    embedded: list[ChunkInput] = []
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        try:
            results = embeddings.embed_texts([chunk.text for chunk in batch])
        except OllamaError as exc:
            raise EmbeddingUnavailableError(str(exc)) from exc
        embedded.extend(
            replace(chunk, embedding=result.values)
            for chunk, result in zip(batch, results, strict=True)
        )
    return embedded


def index_pdf(
    conn,
    data: bytes,
    filename: str,
    *,
    embeddings: EmbeddingService,
    config: IndexingConfig,
    replace_existing: bool = True,
) -> IndexingResult:
    """Validate, chunk, embed and store a PDF.

    Args:
        conn: Open database connection. The caller owns the transaction.
        data: Raw PDF bytes.
        filename: Original file name, only used for reporting.
        embeddings: Embedding service bound to the configured model.
        config: Chunking, size and batching limits.
        replace_existing: When ``True``, re-indexing an already known document
            replaces its chunks instead of failing.

    Raises:
        pdf.PdfIngestionError: The document is not a valid, readable PDF.
        EmbeddingUnavailableError: Embeddings could not be generated.
        IndexingError: The document is already indexed and cannot be replaced.
    """
    # Raises the existing typed errors for invalid input; no database write yet.
    extracted = pdf.ingest_pdf(data, filename, max_size_bytes=config.max_size_bytes)
    sha256 = content_sha256(data)

    existing = repositories.find_document_by_sha256(conn, sha256)
    if existing is not None and not replace_existing:
        raise IndexingError(
            f"Document '{extracted.document_name}' is already indexed ({existing.id})."
        )

    chunks = chunk_pages(
        extracted.pages,
        ChunkingConfig(
            size_chars=config.chunk_size_chars,
            overlap_chars=config.chunk_overlap_chars,
        ),
    )
    if not chunks:
        raise IndexingError("The document did not produce any indexable chunks.")

    chunks = _embed_chunks(chunks, embeddings, config.embedding_batch_size)

    dimension = embeddings.expected_dimension or len(chunks[0].embedding)
    document_id = repositories.upsert_document(
        conn,
        name=extracted.document_name,
        sha256=sha256,
        page_count=extracted.page_count,
    )
    stored = repositories.replace_chunks(
        conn,
        document_id=document_id,
        chunks=chunks,
        embedding_model=embeddings.model,
        embedding_dim=dimension,
        embedding_version=embeddings.version,
    )

    return IndexingResult(
        document_id=document_id,
        document_name=extracted.document_name,
        page_count=extracted.page_count,
        chunk_count=stored,
        already_indexed=existing is not None,
    )
