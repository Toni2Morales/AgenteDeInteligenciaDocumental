"""Unit tests for the Ollama client using a mocked HTTP transport.

No real Ollama server is required: every response is simulated, so these tests
are deterministic and fast.
"""

import httpx
import pytest

from app.services.ollama import (
    OllamaClient,
    OllamaModelNotFoundError,
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)


def make_client(handler) -> OllamaClient:
    transport = httpx.MockTransport(handler)
    return OllamaClient(
        base_url="http://ollama.test:11434",
        llm_model="qwen2.5:3b",
        embedding_model="embeddinggemma",
        timeout_seconds=5,
        client=httpx.Client(transport=transport),
    )


def test_is_available_true_when_server_answers():
    client = make_client(lambda request: httpx.Response(200, json={"version": "0.40.6"}))

    assert client.is_available() is True


def test_is_available_false_when_server_is_down():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    assert make_client(handler).is_available() is False


def test_version_is_returned():
    client = make_client(lambda request: httpx.Response(200, json={"version": "0.40.6"}))

    assert client.version() == "0.40.6"


def test_list_models_reads_model_names():
    payload = {"models": [{"model": "qwen2.5:3b"}, {"name": "embeddinggemma:latest"}]}
    client = make_client(lambda request: httpx.Response(200, json=payload))

    assert client.list_models() == ["qwen2.5:3b", "embeddinggemma:latest"]


def test_has_model_allows_omitted_latest_tag():
    payload = {"models": [{"model": "embeddinggemma:latest"}]}
    client = make_client(lambda request: httpx.Response(200, json=payload))

    assert client.has_model("embeddinggemma") is True
    assert client.has_model("embeddinggemma:latest") is True
    assert client.has_model("missing") is False


def test_ensure_model_raises_with_pull_hint():
    client = make_client(lambda request: httpx.Response(200, json={"models": []}))

    with pytest.raises(OllamaModelNotFoundError) as excinfo:
        client.ensure_model("embeddinggemma")

    assert "ollama pull embeddinggemma" in str(excinfo.value)


def test_embed_returns_vector():
    payload = {"embeddings": [[0.1, 0.2, 0.3]]}
    client = make_client(lambda request: httpx.Response(200, json=payload))

    assert client.embed("hello") == [0.1, 0.2, 0.3]


def test_embedding_dimension_measures_vector_length():
    payload = {"embeddings": [[0.0] * 768]}
    client = make_client(lambda request: httpx.Response(200, json=payload))

    assert client.embedding_dimension() == 768


def test_embed_many_validates_count():
    payload = {"embeddings": [[0.1, 0.2]]}
    client = make_client(lambda request: httpx.Response(200, json=payload))

    with pytest.raises(OllamaResponseError):
        client.embed_many(["a", "b"])


def test_embed_many_with_empty_input_does_not_call_server():
    def handler(request):
        raise AssertionError("the server must not be called")

    assert make_client(handler).embed_many([]) == []


def test_timeout_is_reported_as_typed_error():
    def handler(request):
        raise httpx.ReadTimeout("too slow")

    with pytest.raises(OllamaTimeoutError):
        make_client(handler).embed("hello")


def test_connection_error_is_reported_as_unavailable():
    def handler(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(OllamaUnavailableError):
        make_client(handler).embed("hello")


def test_missing_model_http_404_is_typed():
    payload = {"error": "model 'nope' not found"}
    client = make_client(lambda request: httpx.Response(404, json=payload))

    with pytest.raises(OllamaModelNotFoundError):
        client.embed("hello", model="nope")


def test_other_http_error_is_response_error():
    client = make_client(lambda request: httpx.Response(500, json={"error": "boom"}))

    with pytest.raises(OllamaResponseError):
        client.embed("hello")


def test_non_json_response_is_reported():
    client = make_client(lambda request: httpx.Response(200, text="not json"))

    with pytest.raises(OllamaResponseError):
        client.list_models()


def test_check_reports_unavailable_when_server_is_down():
    def handler(request):
        raise httpx.ConnectError("no route")

    status = make_client(handler).check()

    assert status.available is False
    assert status.models == []


def test_check_reports_available_models():
    payload = {"models": [{"model": "qwen2.5:3b"}, {"model": "embeddinggemma:latest"}]}

    def handler(request):
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.6"})
        return httpx.Response(200, json=payload)

    status = make_client(handler).check()

    assert status.available is True
    assert status.llm_model_present is True
    assert status.embedding_model_present is True


def test_generate_returns_text():
    client = make_client(lambda request: httpx.Response(200, json={"response": "hola"}))

    assert client.generate("di hola") == "hola"
