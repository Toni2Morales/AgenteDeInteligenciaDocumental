"""Internal data structures for documents, chunks and retrieval results.

These are plain dataclasses (not Pydantic) because they describe the database
layer, not HTTP payloads, and because ``metadata`` would clash with Pydantic's
reserved attribute.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class ChunkInput:
    """A fragment ready to be persisted with its embedding."""

    chunk_uid: str
    text: str
    page_number: int
    position: int
    embedding: list[float]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentRecord:
    """A stored document's metadata. Original files are never persisted."""

    id: UUID
    name: str
    sha256: str
    page_count: int
    created_at: datetime


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk returned by a similarity query, with citation metadata."""

    document_id: UUID
    chunk_uid: str
    text: str
    page_number: int
    position: int
    metadata: Mapping[str, Any]
    score: float
