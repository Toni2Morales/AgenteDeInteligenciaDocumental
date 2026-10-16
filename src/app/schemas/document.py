"""Typed schemas describing the result of ingesting a document."""

from pydantic import BaseModel, Field


class PageText(BaseModel):
    """Extracted text for a single, one-based document page."""

    page_number: int = Field(..., ge=1, description="One-based page number.")
    text: str = Field(..., description="Text extracted from the page.")


class ExtractedDocument(BaseModel):
    """Structured result of extracting text from a document."""

    document_name: str = Field(..., description="Original file name of the document.")
    page_count: int = Field(..., ge=0, description="Total number of pages in the document.")
    pages: list[PageText] = Field(
        default_factory=list,
        description="Extracted text per page, in document order.",
    )
