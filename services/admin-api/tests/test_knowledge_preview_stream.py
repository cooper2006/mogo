from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.services.knowledge_preview_stream import parse_byte_range, preview_response
from app.services.knowledge_storage import LocalStorageAdapter


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("", None),
        ("bytes=0-255", (0, 255)),
        ("bytes=900-", (900, 999)),
        ("bytes=-100", (900, 999)),
    ],
)
def test_parse_byte_range(header, expected):
    assert parse_byte_range(header, 1000) == expected


def test_local_preview_supports_http_range(tmp_path):
    content = bytes(range(256)) * 8
    (tmp_path / "preview.pdf").write_bytes(content)
    storage = LocalStorageAdapter(str(tmp_path))
    app = FastAPI()

    @app.get("/preview")
    def preview():
        return preview_response(
            storage=storage,
            storage_key="preview.pdf",
            media_type="application/pdf",
            filename="preview.pdf",
        )

    response = TestClient(app).get("/preview", headers={"Range": "bytes=256-511"})

    assert response.status_code == 206
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == f"bytes 256-511/{len(content)}"
    assert response.content == content[256:512]
