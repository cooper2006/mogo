"""T040 OpenAPI 自动生成脚本测试（FR-25, QF-253）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.openapi.generate import (
    ARTIFACT_DIR,
    SERVICES,
    _build_openapi,
    main,
)

REPO = Path(__file__).resolve().parents[2]


def _artifact(service: str) -> Path:
    return ARTIFACT_DIR / f"{service}-openapi.json"


def test_all_three_artifacts_exist_and_are_openapi_31() -> None:
    for svc in SERVICES:
        p = _artifact(svc)
        assert p.exists(), f"{svc} artifact 缺失"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["openapi"].startswith("3.1"), f"{svc} 应为 OpenAPI 3.1，实际 {data['openapi']}"
        assert data.get("paths"), f"{svc} paths 不应为空"
        assert data.get("info", {}).get("title"), f"{svc} 缺 info.title"


@pytest.mark.parametrize("service", SERVICES)
def test_generate_service_to_tmp_dir(service: str, tmp_path) -> None:
    rc = main(["--service", service, "--out", str(tmp_path)])
    assert rc == 0, f"{service} 生成失败"
    out = tmp_path / f"{service}-openapi.json"
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["openapi"].startswith("3.1")
    assert data.get("paths")


def test_generate_check_passes_when_artifact_matches(tmp_path) -> None:
    svc = "admin-api"
    assert main(["--service", svc, "--out", str(tmp_path)]) == 0
    assert main(["--service", svc, "--out", str(tmp_path), "--check"]) == 0


def test_document_parser_builds_spec_with_celery_stub() -> None:
    """document-parser 依赖 celery，stub 后仍能生成 schema（不启动 worker）。"""
    spec = _build_openapi("document-parser")
    assert spec["openapi"].startswith("3.1")
    assert spec.get("paths")


def test_unknown_service_rejected() -> None:
    with pytest.raises(SystemExit):
        main(["--service", "not-a-service"])


def test_default_artifact_dir_under_025() -> None:
    assert ARTIFACT_DIR == REPO / "specs" / "025-api-contract-hardening" / "openapi"
