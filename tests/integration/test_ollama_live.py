"""Optional live test against a real Ollama server.

Skipped unless ``RUN_OLLAMA_TESTS=1``. It really calls Ollama, so it is only
useful once the models are downloaded AND the Ollama runtime can execute them.

    $env:RUN_OLLAMA_TESTS = "1"; pytest tests/integration -q
"""

import os

import pytest

from app.config.settings import settings
from app.services.ollama import OllamaClient

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_OLLAMA_TESTS") != "1",
    reason="Set RUN_OLLAMA_TESTS=1 with a working Ollama to run live tests.",
)


@pytest.fixture()
def client() -> OllamaClient:
    return OllamaClient(
        base_url=settings.ollama_base_url,
        llm_model=settings.ollama_llm_model,
        embedding_model=settings.ollama_embedding_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )


def test_ollama_is_available(client: OllamaClient):
    assert client.is_available(), f"Ollama is not reachable at {settings.ollama_base_url}"


def test_embedding_model_is_present(client: OllamaClient):
    client.ensure_model(settings.ollama_embedding_model)


def test_embedding_dimension_matches_configuration(client: OllamaClient):
    """The API-measured dimension must match the value stored in the schema."""
    assert settings.embedding_dimension is not None, "Set EMBEDDING_DIMENSION first."

    dimension = client.embedding_dimension(model=settings.ollama_embedding_model)

    assert dimension == settings.embedding_dimension
