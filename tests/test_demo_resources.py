"""Tests for the demo document, generator and evaluation dataset."""

import json
from pathlib import Path

from app.services.pdf_ingestion import ingest_pdf
from scripts.generate_demo_pdf import build_pdf, load_pages

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo"
DOCUMENT_PDF = DEMO_DIR / "document.pdf"
DOCUMENT_TXT = DEMO_DIR / "document.txt"
EVALUATION_JSON = DEMO_DIR / "evaluation.json"

# Anchor phrases that must appear on a given page (1-indexed).
EXPECTED_ANCHORS: dict[int, list[str]] = {
    1: ["99,86", "unidad astronómica", "150 millones"],
    2: ["Mercurio", "Venus", "465"],
    3: ["Júpiter", "Urano", "Neptuno"],
    4: ["cinturón de asteroides", "4.600 millones", "Titán"],
}

REQUIRED_FIELDS = {"id", "question", "expected_answer", "source_page", "source_section"}


def _load_evaluation() -> dict:
    return json.loads(EVALUATION_JSON.read_text(encoding="utf-8"))


def _extracted_pages():
    data = DOCUMENT_PDF.read_bytes()
    return ingest_pdf(data, DOCUMENT_PDF.name, max_size_bytes=10_000_000).pages


def test_demo_files_exist():
    assert DOCUMENT_TXT.is_file()
    assert DOCUMENT_PDF.is_file()
    assert EVALUATION_JSON.is_file()


def test_demo_pdf_matches_source_page_count():
    source_pages = load_pages(DOCUMENT_TXT)
    extracted = _extracted_pages()

    assert len(extracted) == len(source_pages)
    assert len(extracted) == 4


def test_demo_pdf_contains_expected_anchors():
    pages = _extracted_pages()

    for page_number, anchors in EXPECTED_ANCHORS.items():
        text = pages[page_number - 1].text
        for anchor in anchors:
            assert anchor in text, f"Missing {anchor!r} on page {page_number}"


def test_generator_output_is_reproducible():
    regenerated = build_pdf(load_pages(DOCUMENT_TXT))

    assert regenerated == DOCUMENT_PDF.read_bytes()


def test_evaluation_dataset_is_well_formed():
    data = _load_evaluation()
    questions = data["questions"]

    assert questions, "The evaluation dataset must not be empty"

    ids = [item["id"] for item in questions]
    assert len(ids) == len(set(ids)), "Question ids must be unique"

    for item in questions:
        assert REQUIRED_FIELDS <= item.keys(), f"Missing fields in {item['id']}"
        assert item["question"].strip()
        assert item["expected_answer"].strip()
        assert item["source_section"].strip()
        assert isinstance(item["source_page"], int)
        assert item["source_page"] >= 1


def test_evaluation_source_pages_are_within_document():
    page_count = len(_extracted_pages())

    for item in _load_evaluation()["questions"]:
        assert item["source_page"] <= page_count, (
            f"{item['id']} points to page {item['source_page']} of {page_count}"
        )
