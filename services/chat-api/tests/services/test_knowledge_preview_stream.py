from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace

from app.services import knowledge_preview_stream
from app.services.knowledge_preview_stream import parse_byte_range


@pytest.mark.parametrize(
    ("header", "size", "expected"),
    [
        ("", 1000, None),
        ("bytes=0-255", 1000, (0, 255)),
        ("bytes=900-", 1000, (900, 999)),
        ("bytes=-100", 1000, (900, 999)),
        ("bytes=900-2000", 1000, (900, 999)),
    ],
)
def test_parse_byte_range(header, size, expected):
    assert parse_byte_range(header, size) == expected


@pytest.mark.parametrize("header", ["items=0-10", "bytes=1000-", "bytes=20-10", "bytes=0-1,4-5"])
def test_parse_byte_range_rejects_invalid_or_multi_range(header):
    with pytest.raises(ValueError):
        parse_byte_range(header, 1000)


def test_local_preview_supports_http_range(monkeypatch, tmp_path):
    content = bytes(range(256)) * 8
    (tmp_path / "preview.pdf").write_bytes(content)
    monkeypatch.setattr(
        knowledge_preview_stream,
        "get_settings",
        lambda: SimpleNamespace(KNOWLEDGE_LOCAL_STORAGE_DIR=str(tmp_path), KNOWLEDGE_STORAGE_TYPE="local"),
    )
    app = FastAPI()

    @app.get("/preview")
    def preview():
        return knowledge_preview_stream.preview_response(
            document={"preview_key": "preview.pdf", "storage_type": "local"},
            storage_field="preview_key",
            media_type="application/pdf",
        )

    response = TestClient(app).get("/preview", headers={"Range": "bytes=256-511"})

    assert response.status_code == 206
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == f"bytes 256-511/{len(content)}"
    assert response.content == content[256:512]
