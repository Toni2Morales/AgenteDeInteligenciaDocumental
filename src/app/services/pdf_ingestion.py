"""PDF ingestion: validation and per-page text extraction.

This module is self-contained and has no knowledge of FastAPI or the HTTP
layer. It turns raw PDF bytes into a structured, typed result so that future
RAG stages (embeddings, retrieval, agents) can consume it. It never persists
the provided bytes and never executes any content found inside the document.
"""

from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.schemas.document import ExtractedDocument, PageText

_PDF_MAGIC = b"%PDF-"
_PDF_HEADER_SEARCH_WINDOW = 1024


class PdfIngestionError(Exception):
    """Base class for every explicit ingestion failure."""


class InvalidFileTypeError(PdfIngestionError):
    """The provided content is not a PDF file."""


class EmptyFileError(PdfIngestionError):
    """The provided file is empty."""


class FileTooLargeError(PdfIngestionError):
    """The provided file exceeds the configured size limit."""


class CorruptPdfError(PdfIngestionError):
    """The file looks like a PDF but cannot be opened or read."""


class NoExtractableTextError(PdfIngestionError):
    """The PDF is valid but contains no extractable text."""


class ExtractionError(PdfIngestionError):
    """An unexpected error happened while extracting text from a page."""


def _check_size(data: bytes, max_size_bytes: int) -> None:
    if len(data) > max_size_bytes:
        raise FileTooLargeError(f"File exceeds the maximum allowed size of {max_size_bytes} bytes.")


def _check_not_empty(data: bytes) -> None:
    if not data:
        raise EmptyFileError("The uploaded file is empty.")


def _check_pdf_signature(data: bytes) -> None:
    header = data[:_PDF_HEADER_SEARCH_WINDOW]
    if _PDF_MAGIC not in header:
        raise InvalidFileTypeError("The uploaded file is not a PDF.")


def _open_reader(data: bytes) -> PdfReader:
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            # Try an empty password before giving up on protected documents.
            if reader.decrypt("") == 0:
                raise CorruptPdfError("The PDF is encrypted and cannot be read.")
        return reader
    except PdfReadError as exc:
        raise CorruptPdfError("The PDF is corrupt or malformed.") from exc


def _extract_pages(reader: PdfReader) -> list[PageText]:
    pages: list[PageText] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - surfaced as a typed error below
            raise ExtractionError(f"Failed to extract text from page {index}.") from exc
        pages.append(PageText(page_number=index, text=text.strip()))
    return pages


def _ensure_text(pages: list[PageText]) -> None:
    if not pages or not any(page.text for page in pages):
        raise NoExtractableTextError("The PDF does not contain any extractable text.")


def ingest_pdf(data: bytes, filename: str, *, max_size_bytes: int) -> ExtractedDocument:
    """Validate PDF bytes and extract text page by page.

    Args:
        data: Raw bytes of the uploaded file.
        filename: Original file name (used only for reporting).
        max_size_bytes: Maximum accepted file size in bytes.

    Raises:
        FileTooLargeError: The payload is bigger than ``max_size_bytes``.
        EmptyFileError: The payload is empty.
        InvalidFileTypeError: The payload is not a PDF.
        CorruptPdfError: The PDF is corrupt, malformed or encrypted.
        NoExtractableTextError: The PDF has no extractable text.
        ExtractionError: An unexpected error happened during extraction.
    """
    _check_size(data, max_size_bytes)
    _check_not_empty(data)
    _check_pdf_signature(data)

    reader = _open_reader(data)
    pages = _extract_pages(reader)
    _ensure_text(pages)

    name = Path(filename).name if filename else "document.pdf"
    return ExtractedDocument(
        document_name=name,
        page_count=len(pages),
        pages=pages,
    )
