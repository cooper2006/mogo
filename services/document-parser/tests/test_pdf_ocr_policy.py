from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from app.services.pdf_ocr_policy import inspect_pdf_ocr_policy


class _FakePage:
    def __init__(self, text: str = "", *, error: Exception | None = None) -> None:
        self._text = text
        self._error = error

    def extract_text(self) -> str:
        if self._error is not None:
            raise self._error
        return self._text


def _install_fake_pypdf(monkeypatch, pages: list[_FakePage]) -> None:
    fake_module = SimpleNamespace(PdfReader=lambda _path: SimpleNamespace(pages=pages))
    monkeypatch.setitem(sys.modules, "pypdf", fake_module)


def test_all_scanned_pages_enable_full_page_ocr(monkeypatch) -> None:
    _install_fake_pypdf(monkeypatch, [_FakePage(""), _FakePage("  \n")])

    policy = inspect_pdf_ocr_policy(Path("scanned.pdf"))

    assert policy.page_count == 2
    assert policy.image_ocr_pages == frozenset({1, 2})
    assert policy.force_full_page_ocr is True


def test_digital_pdf_preserves_native_text(monkeypatch) -> None:
    _install_fake_pypdf(
        monkeypatch,
        [
            _FakePage("FusionDC1000A 是面向室外边缘数据中心的预制一体化数据中心产品。"),
            _FakePage("这一页包含完整的技术参数、产品应用场景以及部署条件说明。"),
        ],
    )

    policy = inspect_pdf_ocr_policy(Path("digital.pdf"))

    assert policy.image_ocr_pages == frozenset()
    assert policy.force_full_page_ocr is False


def test_mixed_pdf_does_not_force_ocr_over_native_text(monkeypatch) -> None:
    _install_fake_pypdf(
        monkeypatch,
        [
            _FakePage("这一页包含足够长的原生文本，应当保留而不能被整页 OCR 覆盖。"),
            _FakePage(""),
        ],
    )

    policy = inspect_pdf_ocr_policy(Path("mixed.pdf"))

    assert policy.image_ocr_pages == frozenset({2})
    assert policy.force_full_page_ocr is False


def test_pdf_inspection_failure_defaults_to_non_destructive_mode(monkeypatch) -> None:
    fake_module = SimpleNamespace(PdfReader=lambda _path: (_ for _ in ()).throw(ValueError("bad pdf")))
    monkeypatch.setitem(sys.modules, "pypdf", fake_module)

    policy = inspect_pdf_ocr_policy(Path("broken.pdf"))

    assert policy.page_count == 0
    assert policy.image_ocr_pages == frozenset()
    assert policy.force_full_page_ocr is False
