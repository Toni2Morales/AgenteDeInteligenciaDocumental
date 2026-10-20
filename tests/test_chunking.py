"""Unit tests for text chunking.

They check the three properties the retrieval quality depends on: fragments fit
the configured size, page numbers are preserved and never merged, and the
process is deterministic so re-indexing produces the same chunks.
"""

from app.schemas.document import PageText
from app.services.chunking import ChunkingConfig, chunk_pages

CONFIG = ChunkingConfig(size_chars=80, overlap_chars=20)


def _page(number: int, text: str) -> PageText:
    return PageText(page_number=number, text=text)


def test_empty_pages_produce_no_chunks():
    assert chunk_pages([], CONFIG) == []
    assert chunk_pages([_page(1, "")], CONFIG) == []


def test_short_page_produces_single_chunk():
    chunks = chunk_pages([_page(1, "Contenido corto de una sola pagina.")], CONFIG)

    assert len(chunks) == 1
    assert chunks[0].page_number == 1
    assert chunks[0].position == 0
    assert chunks[0].text == "Contenido corto de una sola pagina."


def test_page_numbers_are_preserved_and_pages_are_never_merged():
    chunks = chunk_pages(
        [_page(1, "Primera pagina."), _page(2, "Segunda pagina."), _page(3, "Tercera pagina.")],
        CONFIG,
    )

    assert [chunk.page_number for chunk in chunks] == [1, 2, 3]


def test_positions_are_sequential_in_document_order():
    long_text = " ".join(f"palabra{i}" for i in range(100))
    chunks = chunk_pages([_page(1, long_text), _page(2, "final")], CONFIG)

    assert [chunk.position for chunk in chunks] == list(range(len(chunks)))
    assert chunks[-1].page_number == 2


def test_chunks_never_exceed_the_configured_size():
    long_text = " ".join(f"palabra{i}" for i in range(200))
    chunks = chunk_pages([_page(1, long_text)], CONFIG)

    assert len(chunks) > 1
    assert all(len(chunk.text) <= CONFIG.size_chars for chunk in chunks)


def test_long_paragraph_is_split_with_overlap():
    text = "a" * 200
    chunks = chunk_pages([_page(1, text)], ChunkingConfig(size_chars=100, overlap_chars=30))

    assert len(chunks) >= 2
    # Consecutive chunks share the configured overlap, so context is not lost.
    assert chunks[0].text[-30:] == chunks[1].text[:30]


def test_chunking_is_deterministic():
    pages = [_page(1, "Texto de prueba. " * 20), _page(2, "Otra pagina. " * 20)]

    first = chunk_pages(pages, CONFIG)
    second = chunk_pages(pages, CONFIG)

    assert first == second


def test_chunk_uid_encodes_page_and_position():
    chunks = chunk_pages([_page(7, "Contenido.")], CONFIG)

    assert chunks[0].chunk_uid == "p7-c0"


def test_metadata_records_character_count():
    chunks = chunk_pages([_page(1, "Contenido.")], CONFIG)

    assert chunks[0].metadata["char_count"] == len("Contenido.")


def test_empty_paragraphs_are_discarded():
    chunks = chunk_pages([_page(1, "\n\n\n   \n\nTexto real.\n\n\n")], CONFIG)

    assert len(chunks) == 1
    assert chunks[0].text == "Texto real."


def test_consecutive_paragraphs_are_joined_when_they_fit():
    chunks = chunk_pages([_page(1, "Uno.\nDos.\nTres.")], CONFIG)

    assert len(chunks) == 1
    assert chunks[0].text == "Uno.\nDos.\nTres."
