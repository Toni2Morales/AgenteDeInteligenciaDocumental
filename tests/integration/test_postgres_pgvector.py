"""Integration tests for the PostgreSQL + pgvector schema and repositories.

They are skipped unless ``RUN_DB_TESTS=1`` is set and a database is reachable:

    docker compose up -d
    python scripts/migrate.py
    $env:RUN_DB_TESTS = "1"; pytest tests/integration -q

Each test runs inside a transaction that is rolled back afterwards, so no test
data is left behind.
"""

import os
from uuid import uuid4

import pytest

from app.config.settings import settings
from app.db import repositories
from app.db.connection import connect
from app.schemas.chunk import ChunkInput

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason="Set RUN_DB_TESTS=1 and start Postgres to run database integration tests.",
)

DIMENSION = settings.embedding_dimension or 768
MODEL = "integration-test-model"


def _vector(seed: float) -> list[float]:
    """Deterministic unit vector with a single non-zero component."""
    vector = [0.0] * DIMENSION
    vector[int(seed) % DIMENSION] = 1.0
    return vector


def _sha256() -> str:
    return uuid4().hex * 2


@pytest.fixture()
def conn():
    try:
        connection = connect()
    except Exception as exc:
        # RUN_DB_TESTS=1 means the database was explicitly required, so an
        # unreachable server is a real failure and must not be hidden as a skip.
        pytest.fail(f"RUN_DB_TESTS=1 but the database is not reachable: {exc}")
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture()
def document_id(conn):
    return repositories.upsert_document(
        conn,
        name="integration.pdf",
        sha256=_sha256(),
        page_count=3,
    )


def test_upsert_and_get_document(conn):
    sha = _sha256()
    created = repositories.upsert_document(conn, name="a.pdf", sha256=sha, page_count=2)

    stored = repositories.get_document(conn, created)
    assert stored is not None
    assert stored.name == "a.pdf"
    assert stored.page_count == 2

    # Same checksum must return the same row (idempotent re-ingestion).
    again = repositories.upsert_document(conn, name="a-renamed.pdf", sha256=sha, page_count=5)
    assert again == created
    assert repositories.get_document(conn, created).name == "a-renamed.pdf"


def test_replace_chunks_is_idempotent(conn, document_id):
    chunks = [
        ChunkInput(chunk_uid="c1", text="uno", page_number=1, position=0, embedding=_vector(0)),
        ChunkInput(chunk_uid="c2", text="dos", page_number=2, position=1, embedding=_vector(1)),
    ]

    repositories.replace_chunks(
        conn,
        document_id=document_id,
        chunks=chunks,
        embedding_model=MODEL,
        embedding_dim=DIMENSION,
    )
    repositories.replace_chunks(
        conn,
        document_id=document_id,
        chunks=chunks,
        embedding_model=MODEL,
        embedding_dim=DIMENSION,
    )

    assert repositories.count_chunks(conn, document_id=document_id, embedding_model=MODEL) == 2


def test_similarity_search_returns_closest_chunk_with_citation(conn, document_id):
    chunks = [
        ChunkInput(
            chunk_uid="far",
            text="texto lejano",
            page_number=1,
            position=0,
            embedding=_vector(0),
            metadata={"section": "uno"},
        ),
        ChunkInput(
            chunk_uid="near",
            text="texto cercano",
            page_number=2,
            position=1,
            embedding=_vector(1),
            metadata={"section": "dos"},
        ),
    ]
    repositories.replace_chunks(
        conn,
        document_id=document_id,
        chunks=chunks,
        embedding_model=MODEL,
        embedding_dim=DIMENSION,
    )

    results = repositories.similarity_search(
        conn,
        query_embedding=_vector(1),
        embedding_model=MODEL,
        embedding_dim=DIMENSION,
        limit=2,
    )

    assert results[0].chunk_uid == "near"
    assert results[0].page_number == 2
    assert results[0].metadata == {"section": "dos"}
    assert results[0].score > 0.99


def test_similarity_search_never_mixes_other_models(conn, document_id):
    repositories.replace_chunks(
        conn,
        document_id=document_id,
        chunks=[
            ChunkInput(chunk_uid="c1", text="x", page_number=1, position=0, embedding=_vector(0))
        ],
        embedding_model=MODEL,
        embedding_dim=DIMENSION,
    )

    results = repositories.similarity_search(
        conn,
        query_embedding=_vector(0),
        embedding_model="some-other-model",
        embedding_dim=DIMENSION,
        limit=5,
    )

    assert results == []


def test_similarity_search_filters_by_dimension(conn, document_id):
    repositories.replace_chunks(
        conn,
        document_id=document_id,
        chunks=[
            ChunkInput(chunk_uid="c1", text="x", page_number=1, position=0, embedding=_vector(0))
        ],
        embedding_model=MODEL,
        embedding_dim=DIMENSION,
    )

    results = repositories.similarity_search(
        conn,
        query_embedding=_vector(0),
        embedding_model=MODEL,
        embedding_dim=DIMENSION + 1,
        limit=5,
    )

    assert results == []
