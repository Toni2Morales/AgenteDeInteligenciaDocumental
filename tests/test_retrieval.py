"""Unit tests for semantic retrieval.

The embedding service and the repository layer are replaced by fakes, so these
tests verify the retrieval contract without a database or an Ollama server: the
similarity threshold is applied, the document filter is forwarded, the top_k can
be overridden and incompatible configurations are rejected explicitly.
"""

from uuid import uuid4

import pytest

from app.schemas.chunk import RetrievedChunk
from app.services.embeddings import EmbeddingResult
from app.services.retrieval import (
    EmbeddingModelMismatchError,
    RetrievalConfig,
    RetrievalService,
)


class FakeEmbeddings:
    def __init__(self, expected_dimension: int | None = 768) -> None:
        self.expected_dimension = expected_dimension
        self.model = "embeddinggemma"
        self.version = "1"
        self.calls: list[str] = []

    def embed_text(self, text: str) -> EmbeddingResult:
        self.calls.append(text)
        return EmbeddingResult(
            values=[0.0] * (self.expected_dimension or 4),
            model=self.model,
            dimension=self.expected_dimension or 4,
            version=self.version,
        )


def _chunk(score: float, page: int = 1) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=uuid4(),
        chunk_uid=f"p{page}-c0",
        text="texto",
        page_number=page,
        position=0,
        metadata={},
        score=score,
    )


class FakeRepositories:
    """Records the arguments ``similarity_search`` was called with."""

    def __init__(self, results: list[RetrievedChunk]) -> None:
        self.results = results
        self.calls: list[dict] = []

    def __call__(self, conn, **kwargs):
        self.calls.append(kwargs)
        return self.results


@pytest.fixture()
def patch_repositories(monkeypatch):
    def _install(results: list[RetrievedChunk]) -> FakeRepositories:
        fake = FakeRepositories(results)
        monkeypatch.setattr("app.services.retrieval.repositories.similarity_search", fake)
        return fake

    return _install


def test_retrieve_returns_chunks_above_the_threshold(patch_repositories):
    patch_repositories([_chunk(0.9), _chunk(0.5), _chunk(0.2)])
    service = RetrievalService(
        object(),
        FakeEmbeddings(),
        config=RetrievalConfig(top_k=5, min_score=0.35),
    )

    result = service.retrieve("¿pregunta?")

    assert [chunk.score for chunk in result.chunks] == [0.9, 0.5]
    assert result.has_evidence is True


def test_retrieve_returns_no_evidence_when_all_scores_are_low(patch_repositories):
    patch_repositories([_chunk(0.1), _chunk(0.05)])
    service = RetrievalService(
        object(),
        FakeEmbeddings(),
        config=RetrievalConfig(top_k=5, min_score=0.35),
    )

    result = service.retrieve("¿pregunta?")

    assert result.chunks == []
    assert result.has_evidence is False


def test_retrieve_forwards_the_document_filter(patch_repositories):
    repo = patch_repositories([_chunk(0.9)])
    service = RetrievalService(object(), FakeEmbeddings(), config=RetrievalConfig())
    document_ids = [uuid4(), uuid4()]

    service.retrieve("¿pregunta?", document_ids=document_ids)

    assert repo.calls[0]["document_ids"] == document_ids


def test_retrieve_uses_the_embedding_model_metadata(patch_repositories):
    repo = patch_repositories([_chunk(0.9)])
    service = RetrievalService(
        object(),
        FakeEmbeddings(expected_dimension=768),
        config=RetrievalConfig(),
    )

    service.retrieve("¿pregunta?")

    assert repo.calls[0]["embedding_model"] == "embeddinggemma"
    assert repo.calls[0]["embedding_dim"] == 768


def test_retrieve_honours_the_top_k_override(patch_repositories):
    repo = patch_repositories([_chunk(0.9)])
    service = RetrievalService(object(), FakeEmbeddings(), config=RetrievalConfig(top_k=5))

    service.retrieve("¿pregunta?", top_k=2)

    assert repo.calls[0]["limit"] == 2


def test_blank_question_returns_no_evidence_without_querying(patch_repositories):
    repo = patch_repositories([_chunk(0.9)])
    service = RetrievalService(object(), FakeEmbeddings(), config=RetrievalConfig())

    result = service.retrieve("   ")

    assert result.chunks == []
    assert repo.calls == []


def test_missing_embedding_dimension_is_rejected(patch_repositories):
    patch_repositories([_chunk(0.9)])
    service = RetrievalService(
        object(),
        FakeEmbeddings(expected_dimension=None),
        config=RetrievalConfig(),
    )

    with pytest.raises(EmbeddingModelMismatchError):
        service.retrieve("¿pregunta?")


def test_question_is_embedded_before_search(patch_repositories):
    patch_repositories([])
    embeddings = FakeEmbeddings()
    service = RetrievalService(object(), embeddings, config=RetrievalConfig())

    service.retrieve("  Mercurio  ")

    assert embeddings.calls == ["Mercurio"]
