"""Embedding generation service.

Wraps the Ollama client and adds the metadata needed to store vectors safely:
which model produced them, their dimension and a version label. If an expected
dimension is configured, vectors of any other size are rejected so the database
never receives vectors that do not fit its column.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.ollama import OllamaClient


class EmbeddingError(Exception):
    """Base class for embedding generation failures."""


class EmbeddingDimensionMismatchError(EmbeddingError):
    """A produced vector does not match the configured/verified dimension."""


@dataclass(frozen=True)
class EmbeddingResult:
    """A single embedding vector together with its provenance."""

    values: list[float]
    model: str
    dimension: int
    version: str


class EmbeddingService:
    """Generate embeddings through Ollama and keep their metadata consistent."""

    def __init__(
        self,
        client: OllamaClient,
        *,
        model: str,
        version: str = "1",
        expected_dimension: int | None = None,
    ) -> None:
        self._client = client
        self.model = model
        self.version = version
        self.expected_dimension = expected_dimension

    def _wrap(self, values: list[float]) -> EmbeddingResult:
        dimension = len(values)
        if self.expected_dimension is not None and dimension != self.expected_dimension:
            raise EmbeddingDimensionMismatchError(
                f"Model '{self.model}' returned {dimension} values but the configured "
                f"dimension is {self.expected_dimension}. Re-verify with "
                "`python scripts/verify_ollama.py` and reindex if the model changed."
            )
        return EmbeddingResult(
            values=values,
            model=self.model,
            dimension=dimension,
            version=self.version,
        )

    def embed_text(self, text: str) -> EmbeddingResult:
        """Embed a single text."""
        return self._wrap(self._client.embed(text, model=self.model))

    def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        """Embed several texts in one call."""
        return [self._wrap(values) for values in self._client.embed_many(texts, model=self.model)]
