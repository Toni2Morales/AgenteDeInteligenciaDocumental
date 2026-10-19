"""Unit tests for the embedding service using a stub Ollama client."""

import pytest

from app.services.embeddings import (
    EmbeddingDimensionMismatchError,
    EmbeddingService,
)


class StubClient:
    def __init__(self, vectors):
        self._vectors = vectors
        self.calls = []

    def embed(self, text, *, model=None):
        self.calls.append(("embed", text, model))
        return self._vectors[0]

    def embed_many(self, texts, *, model=None):
        self.calls.append(("embed_many", list(texts), model))
        return self._vectors


def test_embed_text_adds_provenance():
    client = StubClient([[0.0] * 768])
    service = EmbeddingService(client, model="embeddinggemma", version="1")

    result = service.embed_text("hola")

    assert result.dimension == 768
    assert result.model == "embeddinggemma"
    assert result.version == "1"
    assert len(result.values) == 768


def test_embed_text_rejects_mismatched_dimension():
    client = StubClient([[0.0] * 10])
    service = EmbeddingService(client, model="embeddinggemma", expected_dimension=768)

    with pytest.raises(EmbeddingDimensionMismatchError):
        service.embed_text("hola")


def test_embed_texts_returns_one_result_per_input():
    client = StubClient([[0.0] * 768, [0.0] * 768])
    service = EmbeddingService(client, model="embeddinggemma", expected_dimension=768)

    results = service.embed_texts(["a", "b"])

    assert len(results) == 2
    assert all(result.dimension == 768 for result in results)
    assert client.calls[0][0] == "embed_many"
