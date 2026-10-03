"""Tests for XLSX / PPTX fallback parsing (003 audit fix, 2026-10-03).

These parsers are used when Docling is not installed (the common case in
production and CI). They turn spreadsheets and presentations into markdown
so the knowledge base can ingest them.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


def _make_xlsx(tmp_path: Path, *, sheets: dict[str, list[list[str]]]) -> Path:
    """Create a minimal XLSX file with the given sheet data."""
    from openpyxl import Workbook

    wb = Workbook()
    # Remove default sheet if we have our own
    default_ws = wb.active
    first = True
    for name, rows in sheets.items():
        if first:
            ws = default_ws
            ws.title = name
            first = False
        else:
            ws = wb.create_sheet(title=name)
        for row in rows:
            ws.append(row)
    path = tmp_path / "test.xlsx"
    wb.save(str(path))
    return path


def _make_pptx(tmp_path: Path, *, slides: list[tuple[str, list[str]]]) -> Path:
    """Create a minimal PPTX file with the given slide titles and bullet points."""
    from pptx import Presentation

    prs = Presentation()
    for title, bullets in slides:
        slide = prs.slides.add_slide(prs.slide_layouts[0] if not bullets else prs.slide_layouts[1])
        slide.shapes.title.text = title
        if bullets:
            body = slide.placeholders[1]
            for i, bullet in enumerate(bullets):
                if i == 0:
                    body.text_frame.text = bullet
                else:
                    p = body.text_frame.add_paragraph()
                    p.text = bullet
    path = tmp_path / "test.pptx"
    prs.save(str(path))
    return path


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------


def test_xlsx_basic_table(tmp_path: Path) -> None:
    """A simple two-column table becomes a markdown table."""
    from app.services.document_parsing_service import parse_xlsx

    path = _make_xlsx(
        tmp_path,
        sheets={
            "Data": [["Name", "Value"], ["Alice", 100], ["Bob", 200]],
        },
    )
    result = parse_xlsx(path, "xlsx")

    assert "## Sheet: Data" in result.markdown
    assert "| Name | Value |" in result.markdown
    assert "| Alice | 100 |" in result.markdown
    assert "| Bob | 200 |" in result.markdown
    assert result.raw["parser"] == "openpyxl"
    assert result.raw["format"] == "xlsx"
    assert len(result.raw["sheets"]) == 1
    assert result.raw["sheets"][0]["sheet"] == "Data"
    assert result.raw["sheets"][0]["rows"] == 3


def test_xlsx_multiple_sheets(tmp_path: Path) -> None:
    """Multiple sheets are each rendered as a separate markdown section."""
    from app.services.document_parsing_service import parse_xlsx

    path = _make_xlsx(
        tmp_path,
        sheets={
            "Sheet1": [["A", "B"], [1, 2]],
            "Sheet2": [["X"], [10], [20]],
        },
    )
    result = parse_xlsx(path, "xlsx")

    assert "## Sheet: Sheet1" in result.markdown
    assert "## Sheet: Sheet2" in result.markdown
    assert len(result.raw["sheets"]) == 2


def test_xlsx_empty_sheet(tmp_path: Path) -> None:
    """An empty sheet is marked as (empty) in markdown."""
    from app.services.document_parsing_service import parse_xlsx

    path = _make_xlsx(tmp_path, sheets={"Empty": []})
    result = parse_xlsx(path, "xlsx")

    assert "## Sheet: Empty" in result.markdown
    assert "(empty)" in result.markdown
    assert result.raw["sheets"][0]["rows"] == 0


def test_xlsx_single_row(tmp_path: Path) -> None:
    """A single row (header only) is rendered as a plain header line."""
    from app.services.document_parsing_service import parse_xlsx

    path = _make_xlsx(tmp_path, sheets={"Single": [["OnlyHeader"]]})
    result = parse_xlsx(path, "xlsx")

    assert "## Sheet: Single" in result.markdown
    assert "(empty)" in result.markdown


def test_xlsx_varied_column_counts(tmp_path: Path) -> None:
    """Rows with fewer cells than the header are padded with empty strings."""
    from app.services.document_parsing_service import parse_xlsx

    path = _make_xlsx(
        tmp_path,
        sheets={
            "Varied": [
                ["Name", "Age", "City"],
                ["Alice", 30],  # missing City
                ["Bob", 25, "NYC"],
            ],
        },
    )
    result = parse_xlsx(path, "xlsx")

    # The markdown table should have the padded row
    assert "| Alice | 30 |  |" in result.markdown


# ---------------------------------------------------------------------------
# PPTX
# ---------------------------------------------------------------------------


def test_pptx_basic_slides(tmp_path: Path) -> None:
    """Basic slides with titles and bullet points are parsed to markdown."""
    from app.services.document_parsing_service import parse_pptx

    path = _make_pptx(
        tmp_path,
        slides=[
            ("Title Slide", []),
            ("Content", ["Point 1", "Point 2"]),
        ],
    )
    result = parse_pptx(path)

    assert "## Slide 1" in result.markdown
    assert "## Slide 2" in result.markdown
    assert "Title Slide" in result.markdown
    assert "Point 1" in result.markdown
    assert "Point 2" in result.markdown
    assert result.raw["parser"] == "python-pptx"
    assert result.raw["format"] == "pptx"
    assert len(result.raw["slides"]) == 2


def test_pptx_empty_slide(tmp_path: Path) -> None:
    """A slide with no text content is marked as (empty)."""
    from app.services.document_parsing_service import parse_pptx

    path = _make_pptx(tmp_path, slides=[("", [])])
    result = parse_pptx(path)

    assert "## Slide 1" in result.markdown
    assert "(empty)" in result.markdown


def test_pptx_title_only(tmp_path: Path) -> None:
    """A title-only slide (no bullet points) is parsed correctly."""
    from app.services.document_parsing_service import parse_pptx

    path = _make_pptx(tmp_path, slides=[("Just a Title", [])])
    result = parse_pptx(path)

    assert "## Slide 1" in result.markdown
    assert "Just a Title" in result.markdown
    assert result.raw["slides"][0]["texts"] == ["Just a Title"]