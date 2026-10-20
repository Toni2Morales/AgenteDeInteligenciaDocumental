"""Unit tests for the indexing service.

Ingestion, chunking, embeddings and persistence are exercised through fakes so
these tests need neither a database nor a model. They verify the properties that
protect data integrity: embeddings are sent in small batches, an embedding
failure leaves nothing written, and re-indexing the same content replaces the
previous chunks instead of duplicating them.
"""

from uuid import uuid4

import pytest

from app.services import indexing
from app.services.embeddings import EmbeddingResult
from app.services.indexing import (
    EmbeddingUnavailableError,
    IndexingConfig,
    IndexingError,
    index_pdf,
)
from app.services.ollama import OllamaUnavailableError
from tests.pdf_factory import make_pdf

CONFIG = IndexingConfig(
    max_size_bytes=10 * 1024 * 1024,
    chunk_size_chars=200,
    chunk_overlap_chars=20,
    embedding_batch_size=2,
)


class FakeEmbeddings:
    def __init__(self, dimension: int = 8, fail: bool = False) -> None:
        self.expected_dimension = dimension
        self.model = "embeddinggemma"
        self.version = "1"
        self.fail = fail
        self.batch_sizes: list[int] = []

    def _result(self, count: int) -> list[EmbeddingResult]:
        return [
            EmbeddingResult(
                values=[0.1] * self.expected_dimension,
                model=self.model,
                dimension=self.expected_dimension,
                version=self.version,
            )
            for _ in range(count)
        ]

    def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        if self.fail:
            raise OllamaUnavailableError("Ollama is not reachable")
        self.batch_sizes.append(len(texts))
        return self._result(len(texts))


class FakeConnection:
    """Minimal connection placeholder passed through to the patched repo calls."""


def _install_repositories(monkeypatch, existing_document_id=None):
    state = {
        "upserted": None,
        "replaced": None,
        "existing": existing_document_id,
    }

    def find_document_by_sha256(conn, sha256):
        if state["existing"] is None:
            return None
        return type("Doc", (), {"id": state["existing"], "sha256": sha256})()

    def upsert_document(conn, *, name, sha256, page_count):
        document_id = state["existing"] or uuid4()
        state["upserted"] = {
            "id": document_id,
            "name": name,
            "sha256": sha256,
            "page_count": page_count,
        }
        return document_id

    def replace_chunks(conn, *, document_id, chunks, embedding_model, embedding_dim, **kwargs):
        state["replaced"] = {
            "document_id": document_id,
            "chunks": chunks,
            "embedding_model": embedding_model,
            "embedding_dim": embedding_dim,
        }
        return len(chunks)

    monkeypatch.setattr(indexing.repositories, "find_document_by_sha256", find_document_by_sha256)
    monkeypatch.setattr(indexing.repositories, "upsert_document", upsert_document)
    monkeypatch.setattr(indexing.repositories, "replace_chunks", replace_chunks)
    return state


@pytest.fixture()
def patched(monkeypatch):
    def _install(existing_document_id=None):
        return _install_repositories(monkeypatch, existing_document_id)

    return _install


def test_index_pdf_stores_chunks_with_embeddings(patched):
    state = patched()
    data = make_pdf(["El Sol concentra la mayor parte de la masa.", "Mercurio es pequeno."])

    result = index_pdf(
        FakeConnection(), data, "doc.pdf", embeddings=FakeEmbeddings(), config=CONFIG
    )

    assert result.document_name == "doc.pdf"
    assert result.page_count == 2
    assert result.chunk_count >= 2
    assert result.already_indexed is False
    stored = state["replaced"]
    assert stored["embedding_model"] == "embeddinggemma"
    assert stored["embedding_dim"] == 8
    assert all(len(chunk.embedding) == 8 for chunk in stored["chunks"])


def test_embeddings_are_sent_in_small_batches(patched):
    patched()
    data = make_pdf([" ".join(f"palabra{i}" for i in range(400))])
    embeddings = FakeEmbeddings()

    index_pdf(FakeConnection(), data, "doc.pdf", embeddings=embeddings, config=CONFIG)

    assert embeddings.batch_sizes
    assert all(size <= CONFIG.embedding_batch_size for size in embeddings.batch_sizes)


def test_reindexing_the_same_content_is_reported_and_uses_the_same_document(patched):
    existing_id = uuid4()
    state = patched(existing_document_id=existing_id)
    data = make_pdf(["Contenido repetido."])

    result = index_pdf(
        FakeConnection(), data, "doc.pdf", embeddings=FakeEmbeddings(), config=CONFIG
    )

    assert result.already_indexed is True
    assert result.document_id == existing_id
    assert state["replaced"]["document_id"] == existing_id


def test_replace_existing_false_raises_for_known_content(patched):
    patched(existing_document_id=uuid4())
    data = make_pdf(["Contenido repetido."])

    with pytest.raises(IndexingError):
        index_pdf(
            FakeConnection(),
            data,
            "doc.pdf",
            embeddings=FakeEmbeddings(),
            config=CONFIG,
            replace_existing=False,
        )


def test_embedding_failure_prevents_any_write(patched, monkeypatch):
    state = patched()
    upsert_calls = []
    monkeypatch.setattr(
        indexing.repositories,
        "upsert_document",
        lambda *args, **kwargs: upsert_calls.append(1),
    )
    data = make_pdf(["Contenido."])

    with pytest.raises(EmbeddingUnavailableError):
        index_pdf(
            FakeConnection(),
            data,
            "doc.pdf",
            embeddings=FakeEmbeddings(fail=True),
            config=CONFIG,
        )

    assert upsert_calls == []
    assert state["replaced"] is None


def test_invalid_document_is_rejected_before_any_write(patched):
    patched()

    with pytest.raises(indexing.pdf.PdfIngestionError):
        index_pdf(
            FakeConnection(),
            b"not a pdf",
            "doc.pdf",
            embeddings=FakeEmbeddings(),
            config=CONFIG,
        )


def test_embedding_dimension_comes_from_the_service(patched):
    state = patched()
    data = make_pdf(["Contenido."])

    index_pdf(
        FakeConnection(),
        data,
        "doc.pdf",
        embeddings=FakeEmbeddings(dimension=16),
        config=CONFIG,
    )

    assert state["replaced"]["embedding_dim"] == 16


def test_content_checksum_is_stable_for_identical_bytes():
    data = make_pdf(["Contenido."])

    assert indexing.content_sha256(data) == indexing.content_sha256(data)
    assert indexing.content_sha256(data) != indexing.content_sha256(b"other")
