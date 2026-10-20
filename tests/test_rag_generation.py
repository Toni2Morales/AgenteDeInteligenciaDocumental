"""Unit tests for grounded answer generation, citations and abstention.

The Ollama client is replaced by small fakes, so no model is downloaded and no
network call is made. What is checked is the contract: the Spanish system prompt
restricts the model to the retrieved evidence, citations are always rebuilt from
the retrieved chunks and never from the model output, and the generator abstains
when there is no evidence.
"""

from uuid import uuid4

import pytest

from app.schemas.chunk import RetrievedChunk
from app.services.ollama import OllamaUnavailableError
from app.services.rag import (
    INSUFFICIENT_EVIDENCE_MESSAGE,
    SYSTEM_PROMPT,
    AnswerGenerator,
    GenerationError,
    build_context,
    build_prompt,
    citations_from_chunks,
)


def _chunk(page: int, text: str, score: float = 0.8, document_id=None) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=document_id or uuid4(),
        chunk_uid=f"p{page}-c0",
        text=text,
        page_number=page,
        position=0,
        metadata={},
        score=score,
    )


class FakeClient:
    """Minimal stand-in for ``OllamaClient`` that records the last call."""

    def __init__(self, answer: str = "Respuesta [1]") -> None:
        self._answer = answer
        self.last_prompt: str | None = None
        self.last_system: str | None = None
        self.last_model: str | None = None

    def generate(self, prompt: str, *, system: str | None = None, model: str | None = None) -> str:
        self.last_prompt = prompt
        self.last_system = system
        self.last_model = model
        return self._answer


class FailingClient:
    def generate(self, prompt, *, system=None, model=None):
        raise OllamaUnavailableError("Ollama is not reachable")


# System prompt -------------------------------------------------------------


def test_system_prompt_requires_spanish_and_evidence_only():
    lowered = SYSTEM_PROMPT.lower()

    assert "espanol" in lowered
    assert "evidencia" in lowered
    assert "no inventes" in lowered
    assert "no confiable" in lowered


# Context and prompt building ----------------------------------------------


def test_build_context_numbers_chunks_and_labels_the_page():
    context = build_context([_chunk(2, "Mercurio es el mas cercano.")], max_chars=1000)

    assert "[1]" in context
    assert "pagina 2" in context
    assert "Mercurio es el mas cercano." in context


def test_build_context_respects_the_character_limit():
    chunks = [_chunk(1, "x" * 500), _chunk(2, "y" * 500)]
    context = build_context(chunks, max_chars=600)

    assert "y" * 500 not in context
    assert len(context) <= 700


def test_build_prompt_contains_question_and_context():
    prompt = build_prompt("¿Cual es el planeta mas pequeno?", "[1] (pagina 2)\nMercurio.")

    assert "¿Cual es el planeta mas pequeno?" in prompt
    assert "Mercurio." in prompt


# Citations -----------------------------------------------------------------


def test_citations_are_built_from_chunks_not_from_the_model():
    document_id = uuid4()
    chunk = _chunk(3, "Evidencia concreta.", score=0.91, document_id=document_id)

    citations = citations_from_chunks([chunk])

    assert len(citations) == 1
    assert citations[0].document_id == document_id
    assert citations[0].page_number == 3
    assert citations[0].chunk_uid == "p3-c0"
    assert citations[0].excerpt == "Evidencia concreta."
    assert citations[0].score == pytest.approx(0.91)


def test_citation_excerpt_is_truncated():
    citations = citations_from_chunks([_chunk(1, "a" * 500)], excerpt_chars=100)

    assert len(citations[0].excerpt) == 100


# Generation and abstention -------------------------------------------------


def test_generate_returns_grounded_answer_with_citations():
    client = FakeClient(answer="Mercurio [1]")
    generator = AnswerGenerator(client, llm_model="qwen2.5:3b")

    result = generator.generate("¿Planeta mas pequeno?", [_chunk(2, "Mercurio.")])

    assert result.grounded is True
    assert result.abstained is False
    assert result.answer == "Mercurio [1]"
    assert len(result.citations) == 1
    assert client.last_system == SYSTEM_PROMPT
    assert client.last_model == "qwen2.5:3b"


def test_generate_abstains_without_evidence_and_does_not_call_the_model():
    client = FakeClient()
    generator = AnswerGenerator(client, llm_model="qwen2.5:3b")

    result = generator.generate("¿Pregunta sin respuesta?", [])

    assert result.abstained is True
    assert result.grounded is False
    assert result.citations == []
    assert result.reason == "no_evidence"
    assert result.answer == INSUFFICIENT_EVIDENCE_MESSAGE
    assert client.last_prompt is None


def test_generate_abstains_when_the_model_returns_empty_text():
    generator = AnswerGenerator(FakeClient(answer="   "), llm_model="qwen2.5:3b")

    result = generator.generate("¿Pregunta?", [_chunk(1, "Algo.")])

    assert result.abstained is True
    assert result.reason == "empty_model_answer"


def test_generate_raises_typed_error_when_ollama_is_unavailable():
    generator = AnswerGenerator(FailingClient(), llm_model="qwen2.5:3b")

    with pytest.raises(GenerationError):
        generator.generate("¿Pregunta?", [_chunk(1, "Algo.")])


def test_context_sent_to_the_model_is_limited():
    client = FakeClient()
    generator = AnswerGenerator(client, llm_model="qwen2.5:3b", max_context_chars=200)
    chunks = [_chunk(1, "x" * 400), _chunk(2, "y" * 400)]

    generator.generate("¿Pregunta?", chunks)

    assert "y" * 400 not in client.last_prompt
