from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


MIN_MEANINGFUL_NATIVE_TEXT_CHARS = 20


@dataclass(frozen=True)
class PdfOcrPolicy:
    page_count: int
    image_ocr_pages: frozenset[int]
    force_full_page_ocr: bool


def inspect_pdf_ocr_policy(
    path: Path,
    *,
    min_native_text_chars: int = MIN_MEANINGFUL_NATIVE_TEXT_CHARS,
) -> PdfOcrPolicy:
    """Choose full-page OCR only when every PDF page lacks useful native text."""
    try:
        from pypdf import PdfReader  # type: ignore

        pages = list(PdfReader(str(path)).pages)
    except Exception:
        # If inspection fails, let Docling preserve any native text it can read.
        return PdfOcrPolicy(page_count=0, image_ocr_pages=frozenset(), force_full_page_ocr=False)

    image_ocr_pages: set[int] = set()
    for page_number, page in enumerate(pages, start=1):
        try:
            native_text = re.sub(r"\s+", "", page.extract_text() or "")
        except Exception:
            native_text = ""
        if len(native_text) < min_native_text_chars:
            image_ocr_pages.add(page_number)

    page_count = len(pages)
    return PdfOcrPolicy(
        page_count=page_count,
        image_ocr_pages=frozenset(image_ocr_pages),
        force_full_page_ocr=page_count > 0 and len(image_ocr_pages) == page_count,
    )
