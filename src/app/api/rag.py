"""HTTP endpoints for indexing documents and answering questions."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.config.settings import settings
from app.db import repositories
from app.db.connection import connect
from app.schemas.rag import (
    AnswerResponse,
    AskRequest,
    DocumentListResponse,
    IndexedDocument,
    IndexResponse,
    ServiceStatus,
    SourceCitation,
)
from app.services import pdf_ingestion as pdf
from app.services.embeddings import EmbeddingService
from app.services.indexing import (
    EmbeddingUnavailableError,
    IndexingConfig,
    IndexingError,
    index_pdf,
)
from app.services.ollama import OllamaClient
from app.services.rag import AnswerGenerator, GenerationError
from app.services.retrieval import EmbeddingModelMismatchError, RetrievalConfig, RetrievalService

router = APIRouter(prefix="/api", tags=["rag"])

_INGESTION_STATUS: dict[type[pdf.PdfIngestionError], int] = {
    pdf.InvalidFileTypeError: status.HTTP_400_BAD_REQUEST,
    pdf.EmptyFileError: status.HTTP_400_BAD_REQUEST,
    pdf.CorruptPdfError: status.HTTP_400_BAD_REQUEST,
    pdf.FileTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
    pdf.NoExtractableTextError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    pdf.ExtractionError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def _ollama_client() -> OllamaClient:
    return OllamaClient(
        base_url=settings.ollama_base_url,
        llm_model=settings.ollama_llm_model,
        embedding_model=settings.ollama_embedding_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )


def _embedding_service() -> EmbeddingService:
    return EmbeddingService(
        _ollama_client(),
        model=settings.ollama_embedding_model,
        version=settings.embedding_version,
        expected_dimension=settings.embedding_dimension,
    )


def _require_rag_configuration() -> None:
    try:
        settings.validate_for_rag()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


def _to_indexed_document(conn, record) -> IndexedDocument:
    chunk_count = repositories.count_chunks(
        conn,
        document_id=record.id,
        embedding_model=settings.ollama_embedding_model,
    )
    return IndexedDocument(
        id=record.id,
        name=record.name,
        page_count=record.page_count,
        created_at=record.created_at,
        chunk_count=chunk_count,
    )


@router.post("/documents/index", response_model=IndexResponse)
async def index_document(file: UploadFile = File(...)) -> IndexResponse:
    """Index an uploaded PDF: extract, chunk, embed and store its content."""
    _require_rag_configuration()
    data = await file.read(settings.max_upload_size_bytes + 1)
    config = IndexingConfig(
        max_size_bytes=settings.max_upload_size_bytes,
        chunk_size_chars=settings.chunk_size_chars,
        chunk_overlap_chars=settings.chunk_overlap_chars,
        embedding_batch_size=settings.embedding_batch_size,
    )

    try:
        with connect() as conn:
            result = index_pdf(
                conn,
                data,
                file.filename or "",
                embeddings=_embedding_service(),
                config=config,
            )
            record = repositories.get_document(conn, result.document_id)
            document = _to_indexed_document(conn, record)
            conn.commit()
    except pdf.PdfIngestionError as exc:
        raise HTTPException(
            status_code=_INGESTION_STATUS.get(type(exc), status.HTTP_400_BAD_REQUEST),
            detail=str(exc),
        ) from exc
    except EmbeddingUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No se pudo generar embeddings: {exc}",
        ) from exc
    except IndexingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return IndexResponse(
        document=document,
        chunk_count=result.chunk_count,
        already_indexed=result.already_indexed,
    )


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents() -> DocumentListResponse:
    """List every indexed document."""
    with connect() as conn:
        records = repositories.list_documents(conn)
        documents = [_to_indexed_document(conn, record) for record in records]
    return DocumentListResponse(documents=documents)


@router.post("/documents/ask", response_model=AnswerResponse)
async def ask_question(payload: AskRequest) -> AnswerResponse:
    """Answer a question using only the evidence retrieved from indexed documents."""
    _require_rag_configuration()
    question = payload.question.strip()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La pregunta no puede estar vacia.",
        )
    if len(question) > settings.max_question_chars:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"La pregunta supera el maximo de {settings.max_question_chars} caracteres.",
        )

    retrieval_config = RetrievalConfig(
        top_k=settings.retrieval_top_k,
        min_score=settings.retrieval_min_score,
    )

    try:
        with connect() as conn:
            documents = repositories.list_documents(conn)
            if not documents:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="No hay documentos indexados. Indexa un PDF antes de preguntar.",
                )
            requested = payload.document_ids
            known = {document.id for document in documents}
            if requested:
                unknown = [doc_id for doc_id in requested if doc_id not in known]
                if unknown:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Alguno de los documentos indicados no existe.",
                    )

            retrieval = RetrievalService(
                conn,
                _embedding_service(),
                config=retrieval_config,
            )
            result = retrieval.retrieve(
                question,
                document_ids=requested,
                top_k=payload.top_k,
            )
            generator = AnswerGenerator(
                _ollama_client(),
                llm_model=settings.ollama_llm_model,
                max_context_chars=settings.max_context_chars,
            )
            generated = generator.generate(question, result.chunks)
    except EmbeddingModelMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except GenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No se pudo generar la respuesta: {exc}",
        ) from exc

    return AnswerResponse(
        answer=generated.answer,
        citations=[
            SourceCitation(
                document_id=citation.document_id,
                page_number=citation.page_number,
                chunk_uid=citation.chunk_uid,
                excerpt=citation.excerpt,
                score=citation.score,
            )
            for citation in generated.citations
        ],
        grounded=generated.grounded,
        abstained=generated.abstained,
        reason=generated.reason,
    )


@router.get("/services/status", response_model=ServiceStatus)
async def services_status() -> ServiceStatus:
    """Report whether the local services required by the RAG flow are ready."""
    ollama = _ollama_client().check()

    database_available = True
    try:
        with connect() as conn:
            repositories.list_documents(conn)
    except Exception:  # noqa: BLE001 - reported as an unavailable service, not a crash
        database_available = False

    return ServiceStatus(
        ollama_available=ollama.available,
        ollama_llm_model_present=ollama.llm_model_present,
        ollama_embedding_model_present=ollama.embedding_model_present,
        database_available=database_available,
        embedding_dimension_configured=settings.embedding_dimension is not None,
    )
