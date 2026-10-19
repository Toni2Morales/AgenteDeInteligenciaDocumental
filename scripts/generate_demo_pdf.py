"""Generate the reproducible demo PDF from its plain-text source.

The demo document lives in ``demo/document.txt`` as plain text split into pages
by the ``[[PAGE]]`` marker. This script renders it into ``demo/document.pdf``
deterministically: the same source always produces the same bytes, so the
committed PDF can be verified in tests.

Usage::

    python scripts/generate_demo_pdf.py
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_PATH = ROOT / "demo" / "document.txt"
OUTPUT_PATH = ROOT / "demo" / "document.pdf"

PAGE_MARKER = "[[PAGE]]"
FONT_SIZE = 11
LINE_HEIGHT = 14
MAX_LINE_WIDTH = 90
LEFT_MARGIN = 50
TOP_MARGIN = 760


def load_pages(source_path: Path = SOURCE_PATH) -> list[str]:
    """Split the text source into pages using the ``[[PAGE]]`` marker."""
    raw = source_path.read_text(encoding="utf-8")
    chunks = raw.split(PAGE_MARKER)
    pages = [chunk.strip("\n") for chunk in chunks if chunk.strip()]
    if not pages:
        raise ValueError(f"No pages found in {source_path}")
    return pages


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap(text: str, width: int = MAX_LINE_WIDTH) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        for word in paragraph.split():
            candidate = word if not current else f"{current} {word}"
            if len(candidate) <= width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _content_stream(page_text: str) -> bytes:
    parts = ["BT", f"/F1 {FONT_SIZE} Tf", f"{LEFT_MARGIN} {TOP_MARGIN} Td", f"{LINE_HEIGHT} TL"]
    for line in _wrap(page_text):
        parts.append(f"({_escape(line)}) Tj")
        parts.append("T*")
    parts.append("ET")
    return "\n".join(parts).encode("cp1252")


def build_pdf(pages: list[str]) -> bytes:
    """Build a deterministic PDF (one page per entry) as raw bytes."""
    objects: dict[int, bytes] = {}
    font_num = 3
    next_num = 4
    page_nums: list[int] = []

    for page_text in pages:
        page_num = next_num
        content_num = next_num + 1
        next_num += 2
        page_nums.append(page_num)

        stream = _content_stream(page_text)
        objects[content_num] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream"
        )
        objects[page_num] = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_num} 0 R >> >> "
            f"/Contents {content_num} 0 R >>"
        ).encode("ascii")

    kids = " ".join(f"{num} 0 R" for num in page_nums)
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_nums)} >>".encode("ascii")
    objects[3] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )

    header = b"%PDF-1.4\n"
    chunks: list[bytes] = []
    offsets: dict[int, int] = {}
    position = len(header)
    for num in sorted(objects):
        offsets[num] = position
        chunk = f"{num} 0 obj\n".encode("ascii") + objects[num] + b"\nendobj\n"
        chunks.append(chunk)
        position += len(chunk)
    body = b"".join(chunks)

    max_num = max(objects)
    xref_position = len(header) + len(body)
    xref = f"xref\n0 {max_num + 1}\n".encode("ascii") + b"0000000000 65535 f \n"
    for num in range(1, max_num + 1):
        xref += f"{offsets.get(num, 0):010d} 00000 n \n".encode("ascii")

    trailer = (
        f"trailer\n<< /Size {max_num + 1} /Root 1 0 R >>\nstartxref\n".encode("ascii")
        + f"{xref_position}\n".encode("ascii")
        + b"%%EOF\n"
    )
    return header + body + xref + trailer


def main() -> None:
    pages = load_pages()
    OUTPUT_PATH.write_bytes(build_pdf(pages))
    print(f"Wrote {OUTPUT_PATH} ({len(pages)} pages)")


if __name__ == "__main__":
    main()
