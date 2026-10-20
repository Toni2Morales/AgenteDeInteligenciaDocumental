"""HTTP tests for the RAG endpoints.

The database connection, the Ollama client and the embedding service are all
replaced with fakes, so these tests run without PostgreSQL or a local model.
They check the HTTP contract: request validation, status codes, the structured
answer with citations, the abstention path and the error mapping when a local
service is unavailable.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import rag as rag_api
from app.config.settings import settings
from app.main import app
from app.services.rag import Citation, GeneratedAnswer

client = TestClient(app)

INDEX_URL = "/api/documents/index"
DOCUMENTS_URL = "/api/documents"
ASK_URL = "/api/documents/ask"
STATUS_URL = "/api/services/status"


class FakeRecord:
    def __init__(self, name: str = "doc.pdf", page_count: int = 2) -> None:
        self.id = uuid4()
        self.name = name
        self.sha256 = "a" * 64
        self.page_count = page_count
        self.created_at = datetime.now(UTC)


class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return FakeCursor()

    def commit(self):
        pass


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(settings, "embedding_dimension", 768)
    yield


@pytest.fixture()
def patch_ask(monkeypatch):
    """Make ``/ask`` return a fixed generated answer without touching services."""

    def _install(answer: GeneratedAnswer, documents=None):
        record = FakeRecord()

        monkeypatch.setattr(rag_api, "connect", lambda: FakeConnection())
        monkeypatch.setattr(
            rag_api.repositories,
            "list_documents",
            lambda conn: [record] if documents is None else documents,
        )

        class FakeRetrieval:
            def __init__(self, *args, **kwargs):
                pass

            def retrieve(self, question, *, document_ids=None, top_k=None):
                return type("R", (), {"chunks": [object()]})()

        class FakeGenerator:
            def __init__(self, *args, **kwargs):
                pass

            def generate(self, question, chunks):
                return answer

        monkeypatch.setattr(rag_api, "RetrievalService", FakeRetrieval)
        monkeypatch.setattr(rag_api, "AnswerGenerator", FakeGenerator)
        return record

    return _install


# Indexing ------------------------------------------------------------------


def test_index_requires_configuration(monkeypatch):
    monkeypatch.setattr(settings, "embedding_dimension", None)

    response = client.post(INDEX_URL, files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")})

    assert response.status_code == 503
    assert "EMBEDDING_DIMENSION" in response.json()["detail"]


def test_index_rejects_invalid_pdf(monkeypatch):
    monkeypatch.setattr(rag_api, "connect", lambda: FakeConnection())

    response = client.post(INDEX_URL, files={"file": ("doc.pdf", b"not a pdf", "application/pdf")})

    assert response.status_code == 400


def test_index_returns_indexed_document(monkeypatch):
    record = FakeRecord(page_count=3)

    monkeypatch.setattr(rag_api, "connect", lambda: FakeConnection())
    monkeypatch.setattr(rag_api, "index_pdf", lambda *a, **k: type(
        "Result",
        (),
        {"document_id": record.id, "chunk_count": 4, "already_indexed": False},
    )())
    monkeypatch.setattr(rag_api.repositories, "get_document", lambda conn, doc_id: record)
    monkeypatch.setattr(rag_api.repositories, "count_chunks", lambda conn, **kw: 4)

    response = client.post(
        INDEX_URL,
        files={"file": ("doc.pdf", b"%PDF-1.4 dummy", "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["chunk_count"] == 4
    assert body["already_indexed"] is False
    assert body["document"]["name"] == "doc.pdf"
    assert body["document"]["page_count"] == 3


def test_index_maps_embedding_failure_to_503(monkeypatch):
    from app.services.indexing import EmbeddingUnavailableError

    monkeypatch.setattr(rag_api, "connect", lambda: FakeConnection())

    def boom(*args, **kwargs):
        raise EmbeddingUnavailableError("Ollama is not reachable")

    monkeypatch.setattr(rag_api, "index_pdf", boom)

    response = client.post(
        INDEX_URL,
        files={"file": ("doc.pdf", b"%PDF-1.4 dummy", "application/pdf")},
    )

    assert response.status_code == 503


# Document listing ----------------------------------------------------------


def test_list_documents_returns_metadata(monkeypatch):
    record = FakeRecord()

    monkeypatch.setattr(rag_api, "connect", lambda: FakeConnection())
    monkeypatch.setattr(rag_api.repositories, "list_documents", lambda conn: [record])
    monkeypatch.setattr(rag_api.repositories, "count_chunks", lambda conn, **kw: 7)

    response = client.get(DOCUMENTS_URL)

    assert response.status_code == 200
    documents = response.json()["documents"]
    assert len(documents) == 1
    assert documents[0]["chunk_count"] == 7


def test_list_documents_empty(monkeypatch):
    monkeypatch.setattr(rag_api, "connect", lambda: FakeConnection())
    monkeypatch.setattr(rag_api.repositories, "list_documents", lambda conn: [])

    response = client.get(DOCUMENTS_URL)

    assert response.status_code == 200
    assert response.json()["documents"] == []


# Asking questions ----------------------------------------------------------


def test_ask_rejects_blank_question():
    response = client.post(ASK_URL, json={"question": "   "})

    assert response.status_code == 400


def test_ask_rejects_question_over_the_limit(monkeypatch):
    monkeypatch.setattr(settings, "max_question_chars", 5)

    response = client.post(ASK_URL, json={"question": "una pregunta muy larga"})

    assert response.status_code == 413


def test_ask_requires_indexed_documents(monkeypatch):
    monkeypatch.setattr(rag_api, "connect", lambda: FakeConnection())
    monkeypatch.setattr(rag_api.repositories, "list_documents", lambda conn: [])

    response = client.post(ASK_URL, json={"question": "¿Que dice el documento?"})

    assert response.status_code == 409


def test_ask_unknown_document_returns_404(patch_ask):
    patch_ask(GeneratedAnswer(answer="x", grounded=True))

    response = client.post(
        ASK_URL,
        json={"question": "¿Que dice?", "document_ids": [str(uuid4())]},
    )

    assert response.status_code == 404


def test_ask_returns_grounded_answer_with_citations(patch_ask):
    document_id = uuid4()
    answer = GeneratedAnswer(
        answer="Mercurio es el planeta mas pequeno [1].",
        citations=[
            Citation(
                document_id=document_id,
                page_number=2,
                chunk_uid="p2-c0",
                excerpt="Mercurio es el mas pequeno.",
                score=0.82,
            )
        ],
        grounded=True,
        abstained=False,
    )
    patch_ask(answer)

    response = client.post(ASK_URL, json={"question": "¿Cual es el mas pequeno?"})

    assert response.status_code == 200
    body = response.json()
    assert body["grounded"] is True
    assert body["abstained"] is False
    assert body["citations"][0]["page_number"] == 2
    assert body["citations"][0]["chunk_uid"] == "p2-c0"
    assert UUID(body["citations"][0]["document_id"]) == document_id


def test_ask_returns_abstention(patch_ask):
    patch_ask(
        GeneratedAnswer(
            answer="No he encontrado evidencia suficiente.",
            citations=[],
            grounded=False,
            abstained=True,
            reason="no_evidence",
        )
    )

    response = client.post(ASK_URL, json={"question": "¿Pregunta sin respuesta?"})

    assert response.status_code == 200
    body = response.json()
    assert body["abstained"] is True
    assert body["grounded"] is False
    assert body["reason"] == "no_evidence"


# Service status ------------------------------------------------------------


def test_services_status_reports_unavailable_services(monkeypatch):
    monkeypatch.setattr(
        rag_api,
        "_ollama_client",
        lambda: type(
            "Client",
            (),
            {
                "check": lambda self: type(
                    "Status",
                    (),
                    {
                        "available": False,
                        "llm_model_present": False,
                        "embedding_model_present": False,
                    },
                )()
            },
        )(),
    )

    def broken_connect():
        raise RuntimeError("database down")

    monkeypatch.setattr(rag_api, "connect", broken_connect)

    response = client.get(STATUS_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["ollama_available"] is False
    assert body["database_available"] is False
    assert body["embedding_dimension_configured"] is True
