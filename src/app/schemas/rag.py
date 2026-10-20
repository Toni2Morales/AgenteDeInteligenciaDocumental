"""Pydantic models for the indexing and question-answering API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class IndexedDocument(BaseModel):
    """A document stored in the vector database."""

    id: UUID = Field(..., description="Document identifier.")
    name: str = Field(..., description="Original file name.")
    page_count: int = Field(..., ge=0, description="Number of pages.")
    created_at: datetime = Field(..., description="Indexing timestamp.")
    chunk_count: int = Field(0, ge=0, description="Stored chunks for the active model.")


class IndexResponse(BaseModel):
    """Result of indexing a PDF."""

    document: IndexedDocument
    chunk_count: int = Field(..., ge=0, description="Chunks stored for this document.")
    already_indexed: bool = Field(
        ...,
        description="True when the same content had already been indexed and was replaced.",
    )


class DocumentListResponse(BaseModel):
    """Indexed documents available for question answering."""

    documents: list[IndexedDocument]


class AskRequest(BaseModel):
    """A question about one or more indexed documents."""

    question: str = Field(..., min_length=1, max_length=1000, description="Question in Spanish.")
    document_ids: list[UUID] | None = Field(
        default=None,
        description="Restrict the search to these documents. Omit to search every document.",
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        le=20,
        description="Maximum number of chunks used as evidence.",
    )


class SourceCitation(BaseModel):
    """A page-level citation supporting an answer."""

    document_id: UUID
    page_number: int = Field(..., ge=1)
    chunk_uid: str
    excerpt: str
    score: float


class AnswerResponse(BaseModel):
    """A grounded answer with its citations, or an explicit abstention."""

    answer: str
    citations: list[SourceCitation]
    grounded: bool = Field(..., description="True when the answer rests on retrieved evidence.")
    abstained: bool = Field(..., description="True when no grounded answer could be given.")
    reason: str | None = Field(default=None, description="Why the answer abstained, if it did.")


class ServiceStatus(BaseModel):
    """Availability of the local services the RAG flow depends on."""

    ollama_available: bool
    ollama_llm_model_present: bool
    ollama_embedding_model_present: bool
    database_available: bool
    embedding_dimension_configured: bool
