"""Thin, framework-independent client for a local Ollama server.

This module knows nothing about FastAPI. It only translates HTTP calls to a
local Ollama instance into typed Python results and explicit errors, so the
rest of the application never has to guess why a model call failed.

Nothing here downloads models or loads them into memory: models must be pulled
and started by the user with the Ollama CLI.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import httpx

_EMBED_ENDPOINT = "/api/embed"
_TAGS_ENDPOINT = "/api/tags"
_VERSION_ENDPOINT = "/api/version"
_GENERATE_ENDPOINT = "/api/generate"


class OllamaError(Exception):
    """Base class for every explicit Ollama integration failure."""


class OllamaUnavailableError(OllamaError):
    """Ollama is not installed, not running or not reachable."""


class OllamaTimeoutError(OllamaError):
    """Ollama did not answer within the configured timeout."""


class OllamaModelNotFoundError(OllamaError):
    """The requested model is not available in the local Ollama server."""


class OllamaResponseError(OllamaError):
    """Ollama answered with an unexpected or invalid payload."""


@dataclass
class OllamaStatus:
    """Snapshot of the local Ollama server, used for diagnostics."""

    available: bool
    version: str | None = None
    models: list[str] = field(default_factory=list)
    llm_model_present: bool = False
    embedding_model_present: bool = False


def _matches(requested: str, available: str) -> bool:
    """Compare model names allowing Ollama's implicit ``:latest`` tag."""
    if requested == available:
        return True
    return ":" not in requested and available == f"{requested}:latest"


class OllamaClient:
    """Small client around the Ollama HTTP API.

    Args:
        base_url: Base URL of the Ollama server.
        llm_model: Default language model name.
        embedding_model: Default embedding model name.
        timeout_seconds: Timeout applied to every request.
        client: Optional pre-built ``httpx.Client``. Used by tests to inject a
            mock transport. When provided it is not closed by this class.
    """

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        llm_model: str = "qwen2.5:3b",
        embedding_model: str = "embeddinggemma",
        timeout_seconds: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.llm_model = llm_model
        self.embedding_model = embedding_model
        self.timeout_seconds = timeout_seconds
        self._injected_client = client

    @contextmanager
    def _http(self) -> Iterator[httpx.Client]:
        if self._injected_client is not None:
            yield self._injected_client
            return
        with httpx.Client(timeout=self.timeout_seconds) as client:
            yield client

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            with self._http() as client:
                response = client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError(
                f"Ollama did not answer within {self.timeout_seconds:.0f}s."
            ) from exc
        except httpx.TransportError as exc:
            raise OllamaUnavailableError(
                f"Ollama is not reachable at {self.base_url}. Is the service running?"
            ) from exc

        if response.status_code >= 400:
            raise self._error_for_response(response)
        return response

    @staticmethod
    def _error_for_response(response: httpx.Response) -> OllamaError:
        detail = ""
        try:
            payload = response.json()
            detail = str(payload.get("error", "")).strip()
        except ValueError:
            detail = response.text.strip()

        if response.status_code == 404 and "not found" in detail.lower():
            return OllamaModelNotFoundError(detail or "The requested model was not found.")
        message = detail or f"Ollama returned HTTP {response.status_code}."
        return OllamaResponseError(message)

    @staticmethod
    def _parse_json(response: httpx.Response) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise OllamaResponseError("Ollama returned a non-JSON response.") from exc
        if not isinstance(payload, dict):
            raise OllamaResponseError("Ollama returned an unexpected response shape.")
        return payload

    def is_available(self) -> bool:
        """Return ``True`` when the Ollama server answers, ``False`` otherwise."""
        try:
            self._request("GET", _VERSION_ENDPOINT)
        except OllamaError:
            return False
        return True

    def version(self) -> str:
        """Return the Ollama server version."""
        payload = self._parse_json(self._request("GET", _VERSION_ENDPOINT))
        return str(payload.get("version", "unknown"))

    def list_models(self) -> list[str]:
        """Return the names of the models available locally."""
        payload = self._parse_json(self._request("GET", _TAGS_ENDPOINT))
        models = payload.get("models", [])
        if not isinstance(models, list):
            raise OllamaResponseError("Ollama returned an invalid model list.")
        names: list[str] = []
        for entry in models:
            if isinstance(entry, dict):
                name = entry.get("model") or entry.get("name")
                if name:
                    names.append(str(name))
        return names

    def has_model(self, name: str) -> bool:
        """Return ``True`` when ``name`` is available locally."""
        return any(_matches(name, available) for available in self.list_models())

    def ensure_model(self, name: str) -> None:
        """Raise ``OllamaModelNotFoundError`` when ``name`` is not available."""
        if not self.has_model(name):
            raise OllamaModelNotFoundError(
                f"Model '{name}' is not available locally. Pull it with: ollama pull {name}"
            )

    def embed(self, text: str, *, model: str | None = None) -> list[float]:
        """Return the embedding vector for a single text."""
        vectors = self.embed_many([text], model=model)
        return vectors[0]

    def embed_many(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        """Return one embedding vector per input text."""
        if not texts:
            return []
        target = model or self.embedding_model
        response = self._request(
            "POST",
            _EMBED_ENDPOINT,
            json={"model": target, "input": texts},
        )
        payload = self._parse_json(response)
        vectors = payload.get("embeddings")
        if not isinstance(vectors, list) or not all(isinstance(v, list) for v in vectors):
            raise OllamaResponseError("Ollama returned an invalid embeddings payload.")
        if len(vectors) != len(texts):
            raise OllamaResponseError(
                f"Ollama returned {len(vectors)} embeddings for {len(texts)} inputs."
            )
        return [[float(value) for value in vector] for vector in vectors]

    def embedding_dimension(self, *, model: str | None = None) -> int:
        """Measure the real embedding dimension by embedding a probe string."""
        vector = self.embed("dimension probe", model=model)
        if not vector:
            raise OllamaResponseError("Ollama returned an empty embedding vector.")
        return len(vector)

    def generate(self, prompt: str, *, system: str | None = None, model: str | None = None) -> str:
        """Ask the language model for a completion.

        This method is intentionally not wired to any HTTP endpoint yet; it is
        kept here so the future RAG pipeline can reuse it.
        """
        body: dict[str, object] = {
            "model": model or self.llm_model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            body["system"] = system
        payload = self._parse_json(self._request("POST", _GENERATE_ENDPOINT, json=body))
        response = payload.get("response")
        if not isinstance(response, str):
            raise OllamaResponseError("Ollama returned an invalid generation payload.")
        return response

    def check(self) -> OllamaStatus:
        """Collect a diagnostic snapshot without raising for a missing server."""
        try:
            version = self.version()
            models = self.list_models()
        except OllamaError:
            return OllamaStatus(available=False)
        return OllamaStatus(
            available=True,
            version=version,
            models=models,
            llm_model_present=any(_matches(self.llm_model, m) for m in models),
            embedding_model_present=any(_matches(self.embedding_model, m) for m in models),
        )
