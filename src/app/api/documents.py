"""HTTP endpoints for document upload and text extraction."""

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.config.settings import settings
from app.schemas.document import ExtractedDocument
from app.services import pdf_ingestion as pdf

router = APIRouter(prefix="/api/documents", tags=["documents"])

_ERROR_STATUS: dict[type[pdf.PdfIngestionError], int] = {
    pdf.InvalidFileTypeError: status.HTTP_400_BAD_REQUEST,
    pdf.EmptyFileError: status.HTTP_400_BAD_REQUEST,
    pdf.CorruptPdfError: status.HTTP_400_BAD_REQUEST,
    pdf.FileTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
    pdf.NoExtractableTextError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    pdf.ExtractionError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


@router.post("/upload", response_model=ExtractedDocument)
async def upload_document(file: UploadFile = File(...)) -> ExtractedDocument:
    """Validate an uploaded PDF and return its text extracted per page.

    The file is processed in memory and is never persisted to disk.
    """
    max_size_bytes = settings.max_upload_size_bytes
    # Read one extra byte so oversized payloads are always detected even when
    # the client does not declare a Content-Length.
    data = await file.read(max_size_bytes + 1)

    try:
        return pdf.ingest_pdf(data, file.filename or "", max_size_bytes=max_size_bytes)
    except pdf.PdfIngestionError as exc:
        http_status = _ERROR_STATUS.get(type(exc), status.HTTP_400_BAD_REQUEST)
        raise HTTPException(status_code=http_status, detail=str(exc)) from exc
