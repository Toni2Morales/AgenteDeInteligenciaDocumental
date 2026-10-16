"""HTTP tests for the document upload endpoint."""

from fastapi.testclient import TestClient

from app.config.settings import settings
from app.main import app
from app.services import pdf_ingestion as pdf
from tests.pdf_factory import make_pdf

client = TestClient(app)

UPLOAD_URL = "/api/documents/upload"


def _upload(filename: str, content: bytes, mime: str = "application/pdf"):
    return client.post(UPLOAD_URL, files={"file": (filename, content, mime)})


def test_upload_valid_pdf_returns_extracted_text():
    data = make_pdf(["Hello world", "Second page"])

    response = _upload("doc.pdf", data)

    assert response.status_code == 200
    body = response.json()
    assert body["document_name"] == "doc.pdf"
    assert body["page_count"] == 2
    assert len(body["pages"]) == 2
    assert [page["page_number"] for page in body["pages"]] == [1, 2]
    assert "Hello world" in body["pages"][0]["text"]


def test_upload_non_pdf_returns_400():
    response = _upload("notes.txt", b"plain text", mime="text/plain")

    assert response.status_code == 400
    assert "not a PDF" in response.json()["detail"]


def test_upload_empty_file_returns_400():
    response = _upload("empty.pdf", b"")

    assert response.status_code == 400


def test_upload_corrupt_pdf_returns_400():
    response = _upload("bad.pdf", b"%PDF-1.4 broken body")

    assert response.status_code == 400


def test_upload_pdf_without_text_returns_422():
    response = _upload("blank.pdf", make_pdf([None]))

    assert response.status_code == 422


def test_upload_too_large_returns_413(monkeypatch):
    monkeypatch.setattr(settings, "max_upload_size_mb", 0)

    response = _upload("doc.pdf", make_pdf(["content"]))

    assert response.status_code == 413


def test_upload_missing_file_returns_422():
    response = client.post(UPLOAD_URL)

    assert response.status_code == 422


def test_upload_extraction_error_returns_422(monkeypatch):
    class FakePage:
        def extract_text(self) -> str:
            raise ValueError("unexpected parser failure")

    class FakeReader:
        is_encrypted = False
        pages = [FakePage()]

    monkeypatch.setattr(pdf, "PdfReader", lambda *args, **kwargs: FakeReader())

    response = _upload("doc.pdf", b"%PDF-1.4 dummy")

    assert response.status_code == 422
