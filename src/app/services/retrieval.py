"""Semantic retrieval over indexed chunks.

Given a natural-language question, this service embeds it with the configured
local model, queries PostgreSQL + pgvector and returns the most relevant chunks
together with their page and similarity score.

It also enforces two safety properties:

* Only chunks whose ``embedding_model`` and ``embedding_dim`` match the current
  configuration are compared, so incompatible vectors are never mixed.
* Chunks below the configured similarity threshold are discarded, so weak
  matches cannot be presented as evidence.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.db import repositories
from app.schemas.chunk import RetrievedChunk
from app.services.embeddings import EmbeddingService


class RetrievalError(Exception):
    """Base class for retrieval failures."""


class EmbeddingModelMismatchError(RetrievalError):
    """The configured embedding model/dimension is not usable for retrieval."""


@dataclass(frozen=True)
class RetrievalConfig:
    """Retrieval limits applied to every query."""

    top_k: int = 5
    min_score: float = 0.35


@dataclass(frozen=True)
class RetrievalResult:
    """Chunks that passed the relevance threshold, best first."""

    chunks: list[RetrievedChunk]

    @property
    def has_evidence(self) -> bool:
        return bool(self.chunks)


class RetrievalService:
    """Retrieve the most relevant chunks for a question."""

    def __init__(
        self,
        conn,
        embeddings: EmbeddingService,
        *,
        config: RetrievalConfig,
    ) -> None:
        self._conn = conn
        self._embeddings = embeddings
        self._config = config

    def _validate_configuration(self) -> None:
        expected = self._embeddings.expected_dimension
        if expected is None:
            raise EmbeddingModelMismatchError(
                "The embedding dimension is not configured, so stored vectors "
                "cannot be matched. Verify it with `python scripts/verify_ollama.py`."
            )

    def retrieve(
        self,
        question: str,
        *,
        document_ids: Sequence[UUID] | None = None,
        top_k: int | None = None,
    ) -> RetrievalResult:
        """Return the relevant chunks for ``question``.

        Args:
            question: Natural-language question.
            document_ids: When provided, restrict the search to these documents.
            top_k: Override the configured number of results.
        """
        self._validate_configuration()
        text = question.strip()
        if not text:
            return RetrievalResult(chunks=[])

        embedding = self._embeddings.embed_text(text)
        candidates = repositories.similarity_search(
            self._conn,
            query_embedding=embedding.values,
            embedding_model=embedding.model,
            embedding_dim=embedding.dimension,
            limit=top_k or self._config.top_k,
            document_ids=document_ids,
        )
        relevant = [chunk for chunk in candidates if chunk.score >= self._config.min_score]
        return RetrievalResult(chunks=relevant)
