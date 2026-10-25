"""024 T030：build_sha256sums.py 单元测试（不访问 registry，monkeypatch resolve_digest）。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "release"))

import build_sha256sums as module  # noqa: E402

IMAGES = [{"suffix": "admin-api"}, {"suffix": "chat-api"}]


def _run(args, env_extra=None):
    env = {
        "ALL_IMAGES_JSON": json.dumps(IMAGES),
        "GITHUB_REF_NAME": "v1.4.0",
        "GITHUB_REPOSITORY_OWNER": "mogoai",
    }
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(module.__file__), *args],
        capture_output=True, text=True, env=env,
    )


def test_requires_env(tmp_path):
    # 缺 ALL_IMAGES_JSON 应退出
    proc = subprocess.run(
        [sys.executable, str(module.__file__), "build"],
        capture_output=True, text=True, env={},
    )
    assert proc.returncode != 0
    assert "ALL_IMAGES_JSON" in proc.stderr


def test_verify_missing_file(tmp_path):
    proc = _run(["verify", "--file", str(tmp_path / "nope.SHA256SUMS")])
    assert proc.returncode != 0
    assert "找不到" in proc.stderr


def test_build_uses_resolved_digest(tmp_path, monkeypatch):
    monkeypatch.setenv("ALL_IMAGES_JSON", json.dumps(IMAGES))
    monkeypatch.setenv("GITHUB_REF_NAME", "v1.4.0")
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "mogoai")
    calls = []

    def fake_resolve(ref):
        calls.append(ref)
        return "sha256:" + "ab" * 32

    monkeypatch.setattr(module, "resolve_digest", fake_resolve)
    sha_file = tmp_path / "SHA256SUMS"
    entries = module.build(str(sha_file), IMAGES)
    assert len(entries) == 2
    assert entries[0]["ref"] == "ghcr.io/mogoai/admin-api:v1.4.0"
    assert entries[1]["ref"] == "ghcr.io/mogoai/chat-api:v1.4.0"
    content = sha_file.read_text()
    assert content.count("ab" * 32) == 2


def test_verify_matches_and_detects_drift(tmp_path, monkeypatch):
    sha_file = tmp_path / "SHA256SUMS"
    good = "sha256:" + "cd" * 32
    sha_file.write_text(
        f"{good.split('@')[0].replace('sha256:','')}  ghcr.io/mogoai/admin-api:v1.4.0\n"
    )
    monkeypatch.setattr(module, "resolve_digest", lambda ref: good)
    ok, problems = module.verify(str(sha_file))
    assert not problems and len(ok) == 1

    bad = "sha256:" + "ef" * 32
    sha_file.write_text(
        f"{good.split('@')[0].replace('sha256:','')}  ghcr.io/mogoai/admin-api:v1.4.0\n"
    )
    monkeypatch.setattr(module, "resolve_digest", lambda ref: bad)
    ok, problems = module.verify(str(sha_file))
    assert problems and "线上=" in problems[0]


def test_verify_flag_errors(tmp_path, monkeypatch):
    sha_file = tmp_path / "SHA256SUMS"
    sha_file.write_text("aa" * 32 + "  ghcr.io/mogoai/admin-api:v1.4.0\n")

    def boom(ref):
        raise SystemExit("registry 不可达")

    monkeypatch.setattr(module, "resolve_digest", boom)
    ok, problems = module.verify(str(sha_file))
    assert any("无法解析" in p for p in problems)