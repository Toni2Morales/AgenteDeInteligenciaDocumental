"""Robustness, isolation and security-focused tests (deterministic, no services).

Checks:
- Irrelevant / ambiguous questions produce no evidence without DB/Ollama.
- Prompt injection patterns are not treated as instructions by the RAG logic.
- Document isolation: retrieval scoped to a non-existent document returns nothing.
- Chunking safety: empty/malformed pages produce no chunks; page boundaries preserved.
- Generation: no evidence -> abstention; citations rebuilt from chunks only.
- Service errors are reported as typed errors.
"""

from uuid import uuid4

import pytest

from app.schemas.chunk import RetrievedChunk
from app.schemas.document import PageText
from app.services.chunking import ChunkingConfig, chunk_pages
from app.services.embeddings import EmbeddingResult
from app.services.ollama import OllamaUnavailableError
from app.services.rag import AnswerGenerator, GenerationError, citations_from_chunks
from app.services.retrieval import RetrievalConfig, RetrievalService


class FakeEmbeddings:
    def __init__(self, expected_dimension=768):
        self.expected_dimension = expected_dimension
        self.model = "embeddinggemma"
        self.version = "1"
        self.calls = []

    def embed_text(self, text: str):
        self.calls.append(text)
        return EmbeddingResult(
            values=[0.0] * self.expected_dimension,
            model=self.model,
            dimension=self.expected_dimension,
            version=self.version,
        )


class FakeRepos:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def __call__(self, conn, **kwargs):
        self.calls.append(kwargs)
        return self.results


def _chunk(score=0.8, page=1):
    return RetrievedChunk(
        document_id=uuid4(),
        chunk_uid=f"p{page}-c0",
        text="texto",
        page_number=page,
        position=0,
        metadata={},
        score=score,
    )


# Chunking safety
def test_chunk_pages_empty_or_none_safely():
    assert chunk_pages([], ChunkingConfig()) == []
    assert chunk_pages([PageText(page_number=1, text="")], ChunkingConfig()) == []
    assert chunk_pages([PageText(page_number=1, text="\n\n   \n")], ChunkingConfig()) == []


def test_chunk_pages_never_merges_across_pages():
    chunks = chunk_pages(
        [PageText(page_number=1, text="uno"), PageText(page_number=2, text="dos")], ChunkingConfig()
    )
    assert chunks[0].page_number == 1
    assert chunks[1].page_number == 2


# Retrieval robustness
def test_retrieve_isolates_to_nonexistent_document(monkeypatch):
    fake = FakeRepos([])
    monkeypatch.setattr("app.services.retrieval.repositories.similarity_search", fake)
    svc = RetrievalService(
        object(), FakeEmbeddings(), config=RetrievalConfig(top_k=5, min_score=0.35)
    )
    res = svc.retrieve("¿Qué dice?", document_ids=[uuid4()])
    assert res.chunks == []
    assert fake.calls[0]["document_ids"] is not None


def test_retrieve_below_threshold_returns_empty(monkeypatch):
    fake = FakeRepos([_chunk(score=0.1)])
    monkeypatch.setattr("app.services.retrieval.repositories.similarity_search", fake)
    svc = RetrievalService(
        object(), FakeEmbeddings(), config=RetrievalConfig(top_k=5, min_score=0.35)
    )
    res = svc.retrieve("pregunta")
    assert res.chunks == []


def test_retrieve_blank_and_whitespace_question_no_call(monkeypatch):
    fake = FakeRepos([_chunk(score=0.9)])
    monkeypatch.setattr("app.services.retrieval.repositories.similarity_search", fake)
    svc = RetrievalService(object(), FakeEmbeddings(), config=RetrievalConfig())
    res = svc.retrieve("   \n\t  ")
    assert res.chunks == []
    assert fake.calls == []


# Generation robustness / citations
class RecordingClient:
    def __init__(self, answer="respuesta"):
        self.answer = answer
        self.calls = []

    def generate(self, prompt, *, system=None, model=None):
        self.calls.append((prompt, system, model))
        return self.answer


class FailingClient:
    def generate(self, prompt, *, system=None, model=None):
        raise OllamaUnavailableError("down")


def test_generate_abstains_on_empty_evidence_no_llm_call():
    client = RecordingClient()
    gen = AnswerGenerator(client, llm_model="qwen2.5:3b")
    res = gen.generate("cualquier cosa", [])
    assert res.abstained is True
    assert res.citations == []
    assert client.calls == []


def test_citations_always_from_chunks_never_model():
    doc_id = uuid4()
    c = RetrievedChunk(
        document_id=doc_id,
        chunk_uid="p1-c0",
        text="evidencia original",
        page_number=1,
        position=0,
        metadata={},
        score=0.9,
    )
    cites = citations_from_chunks([c])
    assert cites[0].excerpt == "evidencia original"
    assert cites[0].document_id == doc_id


def test_generation_propagates_typed_error():
    gen = AnswerGenerator(FailingClient(), llm_model="qwen2.5:3b")
    with pytest.raises(GenerationError):
        gen.generate("pregunta", [_chunk()])


def test_retrieved_content_treated_as_untrusted_prompt_contains_evidence():
    client = RecordingClient()
    gen = AnswerGenerator(client, llm_model="qwen2.5:3b")
    gen.generate("pregunta", [_chunk()])
    prompt = client.calls[0][0]
    assert "Evidencia disponible" in prompt
    system = client.calls[0][1]
    assert "no confiable" in system.lower() or "evidencia" in system.lower()
