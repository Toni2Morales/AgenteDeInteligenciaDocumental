"""End-to-end evaluation of the RAG pipeline over the demo document.

This is the only test that exercises the whole local flow with real services: it
extracts the demo PDF, generates real embeddings through Ollama, stores them in
PostgreSQL + pgvector and then checks that known questions retrieve the expected
pages and that an unanswerable question produces an abstention.

It is skipped unless BOTH ``RUN_DB_TESTS=1`` and ``RUN_OLLAMA_TESTS=1`` are set,
because it needs a running database and a working Ollama with the embedding
model already pulled:

    docker compose up -d
    python scripts/migrate.py
    $env:RUN_DB_TESTS = "1"; $env:RUN_OLLAMA_TESTS = "1"
    pytest tests/integration/test_rag_evaluation.py -q

Correctness is judged by the retrieved source page, never by the wording of the
LLM answer, which is not a reliable ground truth by itself.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.config.settings import settings
from app.db import repositories
from app.db.connection import connect
from app.services.embeddings import EmbeddingService
from app.services.indexing import IndexingConfig, index_pdf
from app.services.ollama import OllamaClient
from app.services.rag import AnswerGenerator
from app.services.retrieval import RetrievalConfig, RetrievalService

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1" or os.environ.get("RUN_OLLAMA_TESTS") != "1",
    reason="Set RUN_DB_TESTS=1 and RUN_OLLAMA_TESTS=1 with Postgres and Ollama running.",
)

ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = ROOT / "demo"
DOCUMENT_PDF = DEMO_DIR / "document.pdf"
EVALUATION_JSON = DEMO_DIR / "evaluation.json"

# A question whose answer is deliberately absent from the demo document.
UNANSWERABLE_QUESTION = "¿Cuál es el nombre de la misión tripulada a Marte del año 2077?"


def _load_questions() -> list[dict]:
    return json.loads(EVALUATION_JSON.read_text(encoding="utf-8"))["questions"]


def _retrieval(connection, embeddings: EmbeddingService) -> RetrievalService:
    """Build a retrieval service using the configured limits."""
    return RetrievalService(
        connection,
        embeddings,
        config=RetrievalConfig(
            top_k=settings.retrieval_top_k,
            min_score=settings.retrieval_min_score,
        ),
    )


@pytest.fixture(scope="module")
def ollama() -> OllamaClient:
    client = OllamaClient(
        base_url=settings.ollama_base_url,
        llm_model=settings.ollama_llm_model,
        embedding_model=settings.ollama_embedding_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )
    if not client.is_available():
        pytest.fail(f"RUN_OLLAMA_TESTS=1 but Ollama is not reachable at {settings.ollama_base_url}")
    client.ensure_model(settings.ollama_embedding_model)
    return client


@pytest.fixture(scope="module")
def embeddings(ollama: OllamaClient) -> EmbeddingService:
    return EmbeddingService(
        ollama,
        model=settings.ollama_embedding_model,
        version=settings.embedding_version,
        expected_dimension=settings.embedding_dimension,
    )


@pytest.fixture(scope="module")
def indexed_document(embeddings: EmbeddingService):
    """Index the demo PDF once and roll the transaction back when the module ends."""
    try:
        connection = connect()
    except Exception as exc:
        pytest.fail(f"RUN_DB_TESTS=1 but the database is not reachable: {exc}")

    config = IndexingConfig(
        max_size_bytes=settings.max_upload_size_bytes,
        chunk_size_chars=settings.chunk_size_chars,
        chunk_overlap_chars=settings.chunk_overlap_chars,
        embedding_batch_size=settings.embedding_batch_size,
    )

    data = DOCUMENT_PDF.read_bytes()
    result = index_pdf(
        connection,
        data,
        DOCUMENT_PDF.name,
        embeddings=embeddings,
        config=config,
    )
    try:
        yield connection, result
    finally:
        connection.rollback()
        connection.close()


def test_demo_document_produces_chunks(indexed_document):
    _, result = indexed_document

    assert result.page_count == 4
    assert result.chunk_count > 0


def test_known_questions_retrieve_the_expected_page(indexed_document, embeddings):
    connection, result = indexed_document
    retrieval = _retrieval(connection, embeddings)

    hits = 0
    total = 0
    for item in _load_questions():
        total += 1
        found = retrieval.retrieve(
            item["question"],
            document_ids=[result.document_id],
        )
        pages = [chunk.page_number for chunk in found.chunks]
        if item["source_page"] in pages:
            hits += 1

        assert found.has_evidence, f"{item['id']} retrieved no evidence at all"

    # The evaluation is intentionally strict but not absolute: the threshold is a
    # heuristic, so we require a clear majority of correct pages rather than 100%.
    assert hits >= total - 1, f"only {hits}/{total} questions retrieved the expected page"


def test_retrieval_scoped_to_other_document_returns_nothing(indexed_document, embeddings):
    import uuid

    connection, _ = indexed_document
    retrieval = _retrieval(connection, embeddings)

    found = retrieval.retrieve(
        "¿Cuál es la edad del Sistema Solar?",
        document_ids=[uuid.uuid4()],
    )

    assert found.chunks == []


def test_unanswerable_question_abstains(indexed_document, embeddings, ollama):
    connection, result = indexed_document
    retrieval = _retrieval(connection, embeddings)

    found = retrieval.retrieve(UNANSWERABLE_QUESTION, document_ids=[result.document_id])
    generator = AnswerGenerator(
        ollama,
        llm_model=settings.ollama_llm_model,
        max_context_chars=settings.max_context_chars,
    )
    answer = generator.generate(UNANSWERABLE_QUESTION, found.chunks)

    # Either no chunk passed the threshold (clear abstention) or the model was
    # given unrelated evidence and must have said it could not answer. In no case
    # may the system present a confident factual answer about a non-existent event.
    if not found.has_evidence:
        assert answer.abstained is True
    else:
        lowered = answer.answer.lower()
        assert any(
            marker in lowered
            for marker in ("no ", "sin ", "no puedo", "no se", "no hay")
        ), f"expected an abstention, got: {answer.answer!r}"


def test_reindexing_is_idempotent(indexed_document, embeddings):
    connection, result = indexed_document
    before = repositories.count_chunks(
        connection,
        document_id=result.document_id,
        embedding_model=settings.ollama_embedding_model,
    )

    config = IndexingConfig(
        max_size_bytes=settings.max_upload_size_bytes,
        chunk_size_chars=settings.chunk_size_chars,
        chunk_overlap_chars=settings.chunk_overlap_chars,
        embedding_batch_size=settings.embedding_batch_size,
    )
    again = index_pdf(
        connection,
        DOCUMENT_PDF.read_bytes(),
        DOCUMENT_PDF.name,
        embeddings=embeddings,
        config=config,
    )
    after = repositories.count_chunks(
        connection,
        document_id=result.document_id,
        embedding_model=settings.ollama_embedding_model,
    )

    assert again.document_id == result.document_id
    assert again.already_indexed is True
    assert after == before
