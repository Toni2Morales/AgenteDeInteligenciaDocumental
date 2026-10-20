"""Persistence for documents and chunks.

The functions here take an open psycopg connection and never open one of their
own, so transaction boundaries stay under the caller's control (which is what
makes ``replace_chunks`` atomic). They also never store the original PDF bytes:
only metadata and extracted text are kept.

All vector queries filter by ``embedding_model`` and ``embedding_dim`` so that
vectors produced by different models or dimensions are never compared.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from pgvector import Vector
from psycopg.types.json import Jsonb

from app.schemas.chunk import ChunkInput, DocumentRecord, RetrievedChunk

_UPSERT_DOCUMENT = """
INSERT INTO documents (name, sha256, page_count)
VALUES (%s, %s, %s)
ON CONFLICT (sha256) DO UPDATE
    SET name = EXCLUDED.name,
        page_count = EXCLUDED.page_count
RETURNING id
"""

_SELECT_DOCUMENT = """
SELECT id, name, sha256, page_count, created_at
FROM documents
WHERE id = %s
"""

_SELECT_DOCUMENT_BY_SHA256 = """
SELECT id, name, sha256, page_count, created_at
FROM documents
WHERE sha256 = %s
"""

_DELETE_CHUNKS = """
DELETE FROM chunks
WHERE document_id = %s AND embedding_model = %s
"""

_INSERT_CHUNK = """
INSERT INTO chunks (
    document_id, chunk_uid, text, page_number, position,
    metadata, embedding, embedding_model, embedding_dim, embedding_version
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_SIMILARITY_SEARCH = """
SELECT document_id, chunk_uid, text, page_number, position, metadata,
       1 - (embedding <=> %s) AS score
FROM chunks
WHERE embedding_model = %s AND embedding_dim = %s
ORDER BY embedding <=> %s
LIMIT %s
"""

_SIMILARITY_SEARCH_IN_DOCUMENTS = """
SELECT document_id, chunk_uid, text, page_number, position, metadata,
       1 - (embedding <=> %s) AS score
FROM chunks
WHERE embedding_model = %s AND embedding_dim = %s AND document_id = ANY(%s)
ORDER BY embedding <=> %s
LIMIT %s
"""

_SELECT_DOCUMENTS = """
SELECT id, name, sha256, page_count, created_at
FROM documents
ORDER BY created_at DESC, name
"""

_COUNT_CHUNKS = """
SELECT count(*) FROM chunks
WHERE document_id = %s AND embedding_model = %s
"""


def upsert_document(conn, *, name: str, sha256: str, page_count: int) -> UUID:
    """Insert a document or refresh its metadata when the checksum matches."""
    with conn.cursor() as cur:
        cur.execute(_UPSERT_DOCUMENT, (name, sha256, page_count))
        row = cur.fetchone()
    return row[0]


def get_document(conn, document_id: UUID) -> DocumentRecord | None:
    """Return a stored document by id, or ``None``."""
    with conn.cursor() as cur:
        cur.execute(_SELECT_DOCUMENT, (document_id,))
        row = cur.fetchone()
    if row is None:
        return None
    return DocumentRecord(
        id=row[0],
        name=row[1],
        sha256=row[2],
        page_count=row[3],
        created_at=row[4],
    )


def list_documents(conn) -> list[DocumentRecord]:
    """Return every indexed document, most recent first."""
    with conn.cursor() as cur:
        cur.execute(_SELECT_DOCUMENTS)
        rows = cur.fetchall()
    return [
        DocumentRecord(
            id=row[0],
            name=row[1],
            sha256=row[2],
            page_count=row[3],
            created_at=row[4],
        )
        for row in rows
    ]


def replace_chunks(
    conn,
    *,
    document_id: UUID,
    chunks: Sequence[ChunkInput],
    embedding_model: str,
    embedding_dim: int,
    embedding_version: str = "1",
) -> int:
    """Replace all chunks of a document for one embedding model.

    Deleting before inserting makes reprocessing idempotent: the same document
    never accumulates duplicate fragments. Callers must commit.
    """
    with conn.cursor() as cur:
        cur.execute(_DELETE_CHUNKS, (document_id, embedding_model))
        if not chunks:
            return 0
        cur.executemany(
            _INSERT_CHUNK,
            [
                (
                    document_id,
                    chunk.chunk_uid,
                    chunk.text,
                    chunk.page_number,
                    chunk.position,
                    Jsonb(dict(chunk.metadata)),
                    Vector(chunk.embedding),
                    embedding_model,
                    embedding_dim,
                    embedding_version,
                )
                for chunk in chunks
            ],
        )
    return len(chunks)


def count_chunks(conn, *, document_id: UUID, embedding_model: str) -> int:
    """Return how many chunks a document has for one embedding model."""
    with conn.cursor() as cur:
        cur.execute(_COUNT_CHUNKS, (document_id, embedding_model))
        row = cur.fetchone()
    return int(row[0]) if row else 0


def similarity_search(
    conn,
    *,
    query_embedding: list[float],
    embedding_model: str,
    embedding_dim: int,
    limit: int = 5,
    document_ids: Sequence[UUID] | None = None,
) -> list[RetrievedChunk]:
    """Return the closest chunks for one embedding model, with citation data.

    When ``document_ids`` is provided the search is restricted to those
    documents, so chunks from documents outside the requested context are never
    returned. All values are passed as bound parameters, never interpolated.
    """
    vector = Vector(query_embedding)
    with conn.cursor() as cur:
        if document_ids:
            cur.execute(
                _SIMILARITY_SEARCH_IN_DOCUMENTS,
                (
                    vector,
                    embedding_model,
                    embedding_dim,
                    list(document_ids),
                    vector,
                    limit,
                ),
            )
        else:
            cur.execute(
                _SIMILARITY_SEARCH,
                (vector, embedding_model, embedding_dim, vector, limit),
            )
        rows = cur.fetchall()
    return [
        RetrievedChunk(
            document_id=row[0],
            chunk_uid=row[1],
            text=row[2],
            page_number=row[3],
            position=row[4],
            metadata=row[5] if isinstance(row[5], dict) else dict(row[5] or {}),
            score=float(row[6]),
        )
        for row in rows
    ]


def find_document_by_sha256(conn, sha256: str) -> DocumentRecord | None:
    """Return an already indexed document with the same content checksum."""
    with conn.cursor() as cur:
        cur.execute(_SELECT_DOCUMENT_BY_SHA256, (sha256,))
        row = cur.fetchone()
    if row is None:
        return None
    return DocumentRecord(
        id=row[0],
        name=row[1],
        sha256=row[2],
        page_count=row[3],
        created_at=row[4],
    )


__all__: list[str] = [
    "count_chunks",
    "find_document_by_sha256",
    "get_document",
    "list_documents",
    "replace_chunks",
    "similarity_search",
    "upsert_document",
]
