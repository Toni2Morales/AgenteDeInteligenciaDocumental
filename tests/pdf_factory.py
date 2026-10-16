"""Helpers to build minimal, valid PDF documents in memory for tests.

Documents are generated at test time so that no binary fixtures need to be
stored in the repository.
"""

from __future__ import annotations

from collections.abc import Sequence


def _b(text: str) -> bytes:
    return text.encode("latin-1")


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: Sequence[str | None]) -> bytes:
    """Build a minimal single-font PDF with one text block per page.

    A ``None`` or empty page value produces a page with no text operators,
    which is useful to simulate a PDF without extractable text.
    """
    objects: dict[int, bytes] = {}
    font_num = 3
    next_num = 4
    page_nums: list[int] = []

    for page_text in pages:
        page_num = next_num
        content_num = next_num + 1
        next_num += 2
        page_nums.append(page_num)

        stream = _b(f"BT /F1 24 Tf 72 720 Td ({_escape(page_text)}) Tj ET") if page_text else b""
        objects[content_num] = (
            _b(f"<< /Length {len(stream)} >>\nstream\n") + stream + b"\nendstream"
        )
        objects[page_num] = _b(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_num} 0 R >> >> "
            f"/Contents {content_num} 0 R >>"
        )

    kids = " ".join(f"{num} 0 R" for num in page_nums)
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = _b(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_nums)} >>")
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    header = b"%PDF-1.4\n"
    chunks: list[bytes] = []
    offsets: dict[int, int] = {}
    position = len(header)
    for num in sorted(objects):
        offsets[num] = position
        chunk = _b(f"{num} 0 obj\n") + objects[num] + b"\nendobj\n"
        chunks.append(chunk)
        position += len(chunk)
    body = b"".join(chunks)

    max_num = max(objects)
    xref_position = len(header) + len(body)
    xref = _b(f"xref\n0 {max_num + 1}\n") + b"0000000000 65535 f \n"
    for num in range(1, max_num + 1):
        offset = offsets.get(num, 0)
        xref += _b(f"{offset:010d} 00000 n \n")

    trailer = (
        _b(f"trailer\n<< /Size {max_num + 1} /Root 1 0 R >>\nstartxref\n")
        + _b(f"{xref_position}\n")
        + b"%%EOF\n"
    )
    return header + body + xref + trailer
