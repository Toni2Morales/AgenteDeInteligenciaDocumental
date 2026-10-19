"""Unit tests for the PDF ingestion service."""

import pytest

from app.services import pdf_ingestion as pdf
from tests.pdf_factory import make_pdf


def test_multipage_pdf_extracts_text_per_page():
    data = make_pdf(["First page content", "Second page content", "Third page content"])

    result = pdf.ingest_pdf(data, "report.pdf", max_size_bytes=100_000)

    assert result.document_name == "report.pdf"
    assert result.page_count == 3
    assert [page.page_number for page in result.pages] == [1, 2, 3]
    assert "First page content" in result.pages[0].text
    assert "Second page content" in result.pages[1].text
    assert "Third page content" in result.pages[2].text


def test_document_name_is_sanitized():
    data = make_pdf(["content"])

    result = pdf.ingest_pdf(data, r"..\..\etc\passwd.pdf", max_size_bytes=100_000)

    assert result.document_name == "passwd.pdf"


def test_document_name_is_sanitized_for_posix_separators():
    data = make_pdf(["content"])

    result = pdf.ingest_pdf(data, "../../etc/passwd.pdf", max_size_bytes=100_000)

    assert result.document_name == "passwd.pdf"


def test_document_name_is_sanitized_for_absolute_windows_path():
    data = make_pdf(["content"])

    result = pdf.ingest_pdf(data, r"C:\Users\someone\report.pdf", max_size_bytes=100_000)

    assert result.document_name == "report.pdf"


def test_empty_document_name_falls_back_to_default():
    data = make_pdf(["content"])

    assert pdf.ingest_pdf(data, "", max_size_bytes=100_000).document_name == "document.pdf"
    assert pdf.ingest_pdf(data, "   ", max_size_bytes=100_000).document_name == "document.pdf"


def test_directory_only_document_name_falls_back_to_default():
    data = make_pdf(["content"])

    assert pdf.ingest_pdf(data, "../../", max_size_bytes=100_000).document_name == "document.pdf"


def test_empty_file_raises():
    with pytest.raises(pdf.EmptyFileError):
        pdf.ingest_pdf(b"", "empty.pdf", max_size_bytes=100_000)


def test_non_pdf_file_raises():
    with pytest.raises(pdf.InvalidFileTypeError):
        pdf.ingest_pdf(b"just some plain text", "notes.txt", max_size_bytes=100_000)


def test_corrupt_pdf_raises():
    with pytest.raises(pdf.CorruptPdfError):
        pdf.ingest_pdf(b"%PDF-1.4\nthis is not a real pdf body", "bad.pdf", max_size_bytes=100_000)


def test_pdf_without_extractable_text_raises():
    data = make_pdf([None, None])

    with pytest.raises(pdf.NoExtractableTextError):
        pdf.ingest_pdf(data, "blank.pdf", max_size_bytes=100_000)


def test_size_limit_exceeded_raises():
    data = make_pdf(["content"])

    with pytest.raises(pdf.FileTooLargeError):
        pdf.ingest_pdf(data, "big.pdf", max_size_bytes=len(data) - 1)


def test_extraction_error_is_wrapped(monkeypatch):
    class FakePage:
        def extract_text(self) -> str:
            raise ValueError("unexpected parser failure")

    class FakeReader:
        is_encrypted = False
        pages = [FakePage()]

    monkeypatch.setattr(pdf, "PdfReader", lambda *args, **kwargs: FakeReader())

    with pytest.raises(pdf.ExtractionError):
        pdf.ingest_pdf(b"%PDF-1.4 dummy", "doc.pdf", max_size_bytes=100_000)
