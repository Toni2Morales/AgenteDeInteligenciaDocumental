"""Unit tests for the repositories using a fake connection.

A real PostgreSQL is not required: a small recording connection lets us assert
the SQL shape (model/dimension filtering, delete-before-insert) and the mapping
of rows to typed results.
"""

from uuid import uuid4

import pytest

from app.db import repositories
from app.schemas.chunk import ChunkInput


def _norm(sql: str) -> str:
    return " ".join(sql.split())


class FakeCursor:
    def __init__(self, connection):
        self._connection = connection
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params=None):
        self._connection.calls.append((_norm(query), params))
        self._rows = self._connection.next_rows()

    def executemany(self, query, seq):
        rows = list(seq)
        self._connection.calls.append((_norm(query), rows))
        self._connection.bulk_rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    def __init__(self, rows_queue=None):
        self.calls = []
        self.bulk_rows = []
        self._queue = list(rows_queue or [])

    def next_rows(self):
        return self._queue.pop(0) if self._queue else []

    def cursor(self):
        return FakeCursor(self)


def test_upsert_document_returns_id_and_uses_on_conflict():
    document_id = uuid4()
    conn = FakeConnection(rows_queue=[[(document_id,)]])

    result = repositories.upsert_document(conn, name="d.pdf", sha256="a" * 64, page_count=2)

    assert result == document_id
    sql, params = conn.calls[0]
    assert "ON CONFLICT (sha256)" in sql
    assert params == ("d.pdf", "a" * 64, 2)


def test_get_document_returns_none_when_missing():
    conn = FakeConnection(rows_queue=[[]])

    assert repositories.get_document(conn, uuid4()) is None


def test_replace_chunks_deletes_before_inserting():
    document_id = uuid4()
    conn = FakeConnection()
    chunks = [
        ChunkInput(chunk_uid="c1", text="a", page_number=1, position=0, embedding=[0.0] * 768),
        ChunkInput(chunk_uid="c2", text="b", page_number=1, position=1, embedding=[0.0] * 768),
    ]

    count = repositories.replace_chunks(
        conn,
        document_id=document_id,
        chunks=chunks,
        embedding_model="embeddinggemma",
        embedding_dim=768,
    )

    assert count == 2
    delete_sql, delete_params = conn.calls[0]
    assert delete_sql.startswith("DELETE FROM chunks")
    assert delete_params == (document_id, "embeddinggemma")

    insert_sql, inserted = conn.calls[1]
    assert insert_sql.startswith("INSERT INTO chunks")
    assert len(inserted) == 2
    # document_id, chunk_uid, text, page, position, metadata, embedding, model, dim, version
    assert inserted[0][0] == document_id
    assert inserted[0][1] == "c1"


def test_replace_chunks_with_empty_list_only_deletes():
    conn = FakeConnection()

    count = repositories.replace_chunks(
        conn,
        document_id=uuid4(),
        chunks=[],
        embedding_model="embeddinggemma",
        embedding_dim=768,
    )

    assert count == 0
    assert len(conn.calls) == 1
    assert conn.calls[0][0].startswith("DELETE FROM chunks")


def test_similarity_search_filters_by_model_and_dimension():
    document_id = uuid4()
    conn = FakeConnection(rows_queue=[[(document_id, "c1", "texto", 3, 1, {"section": "s"}, 0.87)]])

    results = repositories.similarity_search(
        conn,
        query_embedding=[0.0] * 768,
        embedding_model="embeddinggemma",
        embedding_dim=768,
        limit=5,
    )

    sql, params = conn.calls[0]
    assert "WHERE embedding_model = %s AND embedding_dim = %s" in sql
    assert "ORDER BY embedding <=>" in sql
    assert params[1] == "embeddinggemma"
    assert params[2] == 768
    assert params[4] == 5

    assert len(results) == 1
    assert results[0].chunk_uid == "c1"
    assert results[0].page_number == 3
    assert results[0].metadata == {"section": "s"}
    assert results[0].score == pytest.approx(0.87)


def test_count_chunks_returns_integer():
    conn = FakeConnection(rows_queue=[[(4,)]])

    assert repositories.count_chunks(conn, document_id=uuid4(), embedding_model="m") == 4
