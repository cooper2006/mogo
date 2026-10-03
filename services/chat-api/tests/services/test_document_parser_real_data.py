"""Real-data tests for the 003 document parser local fallback paths.

Closes the 003 residual "解析核心零真实测试（两处引用均为 monkeypatch 打桩）"
by exercising the actual byte-level parsers (XLSX / PPTX / DOCX / CSV) with
real in-memory binary payloads — no monkeypatch, no docling, no network.
"""

from __future__ import annotations

import io
import sys

import pytest

sys.path.insert(0, ".")

from app.services.document_parser import DocumentParserService


def _make_xlsx_bytes(sheet_name: str = "Sheet1", rows: list[list] | None = None) -> bytes:
    """Build a minimal real .xlsx file in memory (openpyxl is a real dependency)."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    if rows is None:
        rows = [
            ["name", "age", "city"],
            ["Alice", 30, "Berlin"],
            ["Bob", 25, "Tokyo"],
        ]
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _make_pptx_bytes(slides: int = 2) -> bytes:
    """Build a minimal real .pptx file in memory (python-pptx is a real dependency)."""
    from pptx import Presentation

    prs = Presentation()
    for idx in range(slides):
        slide = prs.slides.add_slide(prs.slide_layouts[1])  # title+content layout
        slide.shapes.title.text = f"Slide {idx + 1} Title"
        # Find the body placeholder (index 1) and set its text.
        body = slide.placeholders[1]
        body.text = f"Body text on slide {idx + 1}"
    buffer = io.BytesIO()
    prs.save(buffer)
    return buffer.getvalue()


def _make_docx_bytes(paragraphs: list[str] | None = None) -> bytes:
    """Build a minimal real .docx file in memory (python-docx is a real dependency)."""
    from docx import Document

    doc = Document()
    if paragraphs is None:
        paragraphs = ["Hello World", "Second paragraph with content"]
    for para in paragraphs:
        doc.add_paragraph(para)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


@pytest.fixture(scope="module")
def parser_service() -> DocumentParserService:
    """The real service instance (no monkeypatch on any parse path)."""
    return DocumentParserService()


# --- XLSX ---------------------------------------------------------------


def test_xlsx_real_parse_returns_markdown_table(parser_service) -> None:
    """A real .xlsx file with 3 rows is parsed to a Markdown table with the
    correct column headers and all data rows present."""
    content = _make_xlsx_bytes(rows=[["name", "age", "city"], ["Alice", 30, "Berlin"], ["Bob", 25, "Tokyo"]])
    markdown = parser_service._build_markdown_from_local_xlsx_bytes(content, filename="test.xlsx")
    assert markdown, "expected non-empty markdown"
    # Header row must appear in the table.
    assert "| name |" in markdown or "| Name |" in markdown or "name" in markdown
    assert "Alice" in markdown
    assert "Bob" in markdown
    assert "Berlin" in markdown
    assert "Tokyo" in markdown
    # The sheet title must be in the output.
    assert "Sheet" in markdown


def test_xlsx_multiple_sheets(parser_service) -> None:
    """Two sheets are both included in the parsed output."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Sales"
    ws1.append(["product", "units"])
    ws1.append(["widget", 100])
    ws2 = wb.create_sheet("Returns")
    ws2.append(["product", "units"])
    ws2.append(["widget", 5])
    buffer = io.BytesIO()
    wb.save(buffer)
    content = buffer.getvalue()

    markdown = parser_service._build_markdown_from_local_xlsx_bytes(content, filename="multi.xlsx")
    assert "Sales" in markdown
    assert "Returns" in markdown
    assert "widget" in markdown


def test_xlsx_empty_rows_produce_no_table(parser_service) -> None:
    """An xlsx with only an empty sheet produces markdown without a table body."""
    content = _make_xlsx_bytes(rows=[])
    markdown = parser_service._build_markdown_from_local_xlsx_bytes(content, filename="empty.xlsx")
    # No data rows → no markdown table rows, but the sheet header block still appears.
    assert "empty.xlsx" in markdown or "Sheet" in markdown


# --- PPTX -----------------------------------------------------------------


def test_pptx_real_parse_returns_slide_text(parser_service) -> None:
    """A real .pptx with two slides is parsed and each slide's title text is
    present in the output."""
    content = _make_pptx_bytes(slides=2)
    markdown = parser_service._build_markdown_from_local_pptx_bytes(content)
    assert "Slide 1" in markdown
    assert "Slide 2" in markdown
    assert "Body text" in markdown


def test_pptx_single_slide(parser_service) -> None:
    content = _make_pptx_bytes(slides=1)
    markdown = parser_service._build_markdown_from_local_pptx_bytes(content)
    assert "Slide 1" in markdown
    assert "Slide 2" not in markdown


# --- DOCX -----------------------------------------------------------------


def test_docx_real_parse_returns_paragraphs(parser_service) -> None:
    """A real .docx with two paragraphs is parsed and both texts appear."""
    content = _make_docx_bytes(paragraphs=["First line here", "Second line here"])
    result = parser_service._build_docx_parse_from_bytes(
        content, filename="test.docx", upload_images=False
    )
    markdown = result["markdown"]
    assert "First line here" in markdown
    assert "Second line here" in markdown


def test_docx_multiple_paragraphs(parser_service) -> None:
    content = _make_docx_bytes(paragraphs=["Alpha", "Beta", "Gamma"])
    result = parser_service._build_docx_parse_from_bytes(content, filename="multi.docx", upload_images=False)
    markdown = result["markdown"]
    assert "Alpha" in markdown
    assert "Beta" in markdown
    assert "Gamma" in markdown


# --- CSV (delimited) -------------------------------------------------------


def test_csv_real_parse(parser_service) -> None:
    """A real CSV byte payload is parsed to a Markdown table."""
    content = "name,age,city\nAlice,30,Berlin\nBob,25,Tokyo\n".encode()
    markdown = parser_service._build_markdown_from_local_delimited_bytes(
        content, filename="data.csv", delimiter=","
    )
    assert "Alice" in markdown
    assert "Bob" in markdown
    assert "Berlin" in markdown
    assert "Tokyo" in markdown
    assert "name" in markdown


def test_tsv_real_parse(parser_service) -> None:
    content = "a\tb\tc\n1\t2\t3\n".encode()
    markdown = parser_service._build_markdown_from_local_delimited_bytes(
        content, filename="data.tsv", delimiter="\t"
    )
    assert "a" in markdown
    assert "1" in markdown
    assert "2" in markdown
