"""远端部署脚本的镜像推送守卫（2026-11-05 事故回归）。

背景：``deploy-remote-push.sh`` 旧版 ``push_image`` 只判断「远端有没有同名 tag」，
有就跳过。用 ``:latest`` 部署时，本地重新构建代码后远端 tag 依旧存在，脚本显示
成功、``up -d`` 也照跑，但线上容器仍是旧镜像 —— 代码根本没上线。

现在改为按**镜像 ID**（内容寻址，跨 daemon 一致）比对：
ID 一致才跳过；不一致默认告警并记入 ``STALE_IMAGES``，加 ``--force-push`` 才覆盖。
大镜像另走 tar + scp + 远端本地 load，避免慢速 VPN 上 ``save|load`` 长管道断裂。

本测试把脚本里 ``[push-image-guard]`` 标记之间的函数区抽出来，注入 mock 后跑
真实分支（不连远端、不推镜像），再补静态契约与 ``bash -n`` / ``--dry-run`` 检查。

运行::

    python -m pytest deploy/tests/test_deploy_push_guard.py -q
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "deploy/production/deploy-remote-push.sh"
DOC = REPO_ROOT / "deploy/production/REMOTE-PUSH-DEPLOY.md"

LOCAL_ID = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
REMOTE_ID = "sha256:2222222222222222222222222222222222222222222222222222222222222222"
# harness 不会真导出 tar（transfer_image 被 mock），这里只要一个合法路径字符串。
PUSH_TMP_DIR_VALUE = "/tmp/mogo-push-guard-harness"


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _guard_block() -> str:
    match = re.search(
        r"# \[push-image-guard:begin\][^\n]*\n(.*?)\n# \[push-image-guard:end\]",
        _source(),
        re.S,
    )
    assert match, "脚本里缺少 [push-image-guard:begin/end] 标记，无法独立测试函数区"
    return match.group(1)


# 只覆盖依赖、不触碰网络：LOCAL_DC 仅用于架构校验，transfer_image 记录调用而不真传。
HARNESS = r"""
set -Eeuo pipefail

REMOTE_USER=bonc
REMOTE_HOST=172.17.5.96
REMOTE_USE_SUDO=0
SSHPASS_BIN=""
DOCKER_BIN=docker
DOCKER_CONTEXT=mogo-remote
OVERRIDE=docker-compose.prod-external-panweidb.yml
MOGO_VERSION=latest
DRY_RUN=0
FORCE_PUSH=__FORCE_PUSH__
PUSH_STREAM_MAX_MB=200
PUSH_KEEP_TARS=1
PUSH_TMP_DIR="__TMP_DIR__"
MOCK_LOCAL_ID="__LOCAL_ID__"
MOCK_REMOTE_ID="__REMOTE_ID__"
MOCK_ARCH="__ARCH__"

log()  { printf '[LOG] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }

LOCAL_DC=(mock_local_docker)
DC=(mock_remote_docker)
mock_local_docker()  { printf '%s\n' "$MOCK_ARCH"; }
mock_remote_docker() { :; }

__GUARD_BLOCK__

image_id_local()  { printf '%s\n' "$MOCK_LOCAL_ID"; }
image_id_remote() { printf '%s\n' "$MOCK_REMOTE_ID"; }
transfer_image()  { printf '[TRANSFER] %s\n' "$1"; return 0; }

push_image "ghcr.io/mogoai/chat-api:latest" || printf '[RC] push_image=%s\n' "$?"
report_push_summary
printf '[COUNTS] stale=%s updated=%s failed=%s unverified=%s\n' \
  "${#STALE_IMAGES[@]}" "${#UPDATED_IMAGES[@]}" "${#FAILED_IMAGES[@]}" "${#UNVERIFIED_IMAGES[@]}"
"""


def _run_scenario(
    *,
    local_id: str = LOCAL_ID,
    remote_id: str = REMOTE_ID,
    force_push: int = 0,
    arch: str = "amd64",
) -> str:
    harness = (
        HARNESS.replace("__GUARD_BLOCK__", _guard_block())
        .replace("__FORCE_PUSH__", str(force_push))
        .replace("__TMP_DIR__", PUSH_TMP_DIR_VALUE)
        .replace("__LOCAL_ID__", local_id)
        .replace("__REMOTE_ID__", remote_id)
        .replace("__ARCH__", arch)
    )
    proc = subprocess.run(
        ["bash", "-c", harness],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, (
        f"harness 执行失败 rc={proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    return proc.stdout + proc.stderr


# ── 静态契约 ────────────────────────────────────────────────────────────────

def test_bash_syntax_and_help() -> None:
    syntax = subprocess.run(
        ["bash", "-n", str(SCRIPT)], capture_output=True, text=True, cwd=str(REPO_ROOT)
    )
    assert syntax.returncode == 0, syntax.stderr
    help_out = subprocess.run(
        ["bash", str(SCRIPT), "--help"], capture_output=True, text=True, cwd=str(REPO_ROOT)
    )
    assert help_out.returncode == 0, help_out.stderr
    for flag in ("--check", "--dry-run", "--force-push", "--remote-env"):
        assert flag in help_out.stdout, f"--help 缺少 {flag}"


def test_legacy_tag_only_skip_is_gone() -> None:
    """旧逻辑「远端有同名 tag 就 return 0」必须彻底移除。"""
    src = _source()
    assert "remote_image_present" not in src
    assert "远端已存在" not in src
    assert "（跳过）" not in src


def test_guard_contracts_present() -> None:
    src = _source()
    for needle in (
        "--force-push) FORCE_PUSH=1",
        "image_id_local()",
        "image_id_remote()",
        "STALE_IMAGES",
        "report_push_summary",
        "verify_running_images",
        "transfer_image_via_tar",
        "PUSH_STREAM_MAX_MB",
        "scp_run",
    ):
        assert needle in src, f"脚本缺少关键守卫: {needle}"
    # 镜像 ID 比对必须发生在 push_image 内，而不是只在别处定义。
    block = _guard_block()
    assert '"${remote_id}" == "${local_id}"' in block
    assert "STALE_IMAGES+=(" in block


# ── 分支行为 ────────────────────────────────────────────────────────────────

def test_same_id_skips_without_push() -> None:
    out = _run_scenario(remote_id=LOCAL_ID)
    assert "内容一致" in out
    assert "[TRANSFER]" not in out
    assert "[COUNTS] stale=0 updated=0 failed=0 unverified=0" in out


def test_stale_id_warns_and_records_without_force() -> None:
    out = _run_scenario(force_push=0)
    assert "内容不同" in out
    assert "不会" in out and "--force-push" in out
    assert "[TRANSFER]" not in out
    assert "[COUNTS] stale=1 updated=0 failed=0 unverified=0" in out


def test_force_push_overwrites_stale_tag() -> None:
    out = _run_scenario(force_push=1)
    assert "[TRANSFER] ghcr.io/mogoai/chat-api:latest" in out
    assert "已推送并校验" in out
    assert "[COUNTS] stale=0 updated=1 failed=0 unverified=0" in out


def test_missing_remote_image_is_pushed_without_force() -> None:
    out = _run_scenario(remote_id="", force_push=0)
    assert "[TRANSFER]" in out
    assert "[COUNTS] stale=0 updated=1 failed=0 unverified=0" in out


def test_missing_local_image_keeps_remote_without_push() -> None:
    """本地没构建、远端有镜像：不能校验内容，只告警并记为 unverified。"""
    out = _run_scenario(local_id="", remote_id=REMOTE_ID)
    assert "本地缺失、远端存在" in out
    assert "[TRANSFER]" not in out
    assert "[COUNTS] stale=0 updated=0 failed=0 unverified=1" in out


def test_both_missing_reports_local_build_required() -> None:
    out = _run_scenario(local_id="", remote_id="")
    assert "本地 orbstack 缺失" in out
    assert "[RC] push_image=1" in out
    assert "[TRANSFER]" not in out


def test_non_amd64_is_blocked_before_transfer() -> None:
    out = _run_scenario(remote_id="", arch="arm64")
    assert "架构非 amd64" in out
    assert "[TRANSFER]" not in out


# ── 端到端预演与文档同步 ────────────────────────────────────────────────────

def test_dry_run_has_no_side_effects_and_hides_password() -> None:
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run", "--force-push"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout + proc.stderr
    assert "PANWEIDB_PASSWORD 1qaz!QAZ" not in out, "dry-run 不得把明文密码打到日志"
    assert "PANWEIDB_PASSWORD <hidden>" in out
    assert "跳过网关配置 scp" in out, "dry-run 不得真的 scp 到远端"
    assert "是（--force-push）" in out


def test_runbook_documents_force_push() -> None:
    doc = DOC.read_text(encoding="utf-8")
    assert "--force-push" in doc
    assert "镜像 ID" in doc
    assert "代码没上线" in doc or "不会生效" in doc
