"""远端部署脚本的镜像推送守卫（2026-11-05 事故回归）。

背景：``deploy-remote-push.sh`` 旧版 ``push_image`` 只判断「远端有没有同名 tag」，
有就跳过。用 ``:latest`` 部署时，本地重新构建代码后远端 tag 依旧存在，脚本显示
成功、``up -d`` 也照跑，但线上容器仍是旧镜像 —— 代码根本没上线。

现在改为按**内容指纹**比对：指纹优先取 ``RootFS.Layers``（层摘要序列），取不到层列表时
才退回镜像 ID。ID 一致才跳过；不一致默认告警并记入 ``STALE_IMAGES``，加 ``--force-push``
才覆盖。之所以不能只用 ``.Id``：本地 OrbStack 是 containerd/OCI image store，远端 Docker
Engine 是 classic graph driver，同一份内容两边 ``.Id`` 不同，只比 ID 会让每次 amd64 部署
都误报失败并诱发重复全量传输。
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
# 层摘要序列（docker inspect '{{.RootFS.Layers}}' 的原始形态：方括号 + 空格分隔）。
LOCAL_LAYERS = (
    "[sha256:3333333333333333333333333333333333333333333333333333333333333333"
    " sha256:4444444444444444444444444444444444444444444444444444444444444444]"
)
REMOTE_LAYERS = (
    "[sha256:5555555555555555555555555555555555555555555555555555555555555555"
    " sha256:6666666666666666666666666666666666666666666666666666666666666666]"
)
# 同一内容、不同排版（无方括号、换行分隔）：normalizer 应与 LOCAL_LAYERS 判等。
REMOTE_LAYERS_SAME_OTHER_FORMAT = (
    "sha256:3333333333333333333333333333333333333333333333333333333333333333\n"
    "sha256:4444444444444444444444444444444444444444444444444444444444444444"
)
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
RUN_TAR=__RUN_TAR__
PUSH_STREAM_MAX_MB=200
PUSH_KEEP_TARS=1
PUSH_TMP_DIR="__TMP_DIR__"
MOCK_LOCAL_ID="__LOCAL_ID__"
MOCK_REMOTE_ID="__REMOTE_ID__"
MOCK_LOCAL_LAYERS="__LOCAL_LAYERS__"
MOCK_REMOTE_LAYERS="__REMOTE_LAYERS__"
MOCK_ARCH="__ARCH__"
MOCK_REMOTE_SSH_LAYERS="__REMOTE_SSH_LAYERS__"

log()  { printf '[LOG] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }

LOCAL_DC=(mock_local_docker)
DC=(mock_remote_docker)
mock_local_docker()  { printf '%s\n' "$MOCK_ARCH"; }
mock_remote_docker() { :; }

__GUARD_BLOCK__

image_id_local()  { printf '%s\n' "$MOCK_LOCAL_ID"; }
image_id_remote() { printf '%s\n' "$MOCK_REMOTE_ID"; }
image_layers_local()  { printf '%s\n' "$MOCK_LOCAL_LAYERS"; }
image_layers_remote() { printf '%s\n' "$MOCK_REMOTE_LAYERS"; }
transfer_image()  { printf '[TRANSFER] %s\n' "$1"; return 0; }
# tar 路径的远端校验走 ssh（远端 daemon 可能只有 root 可见），harness 里同样 mock 掉：
# 按远端真实输出的形态决定回什么（{{.Id}} 请求回 ID，其余回层列表）。
ssh_run() {
  case "${2:-}" in
    *'{{.Id}}'*) printf '%s\n' "$MOCK_REMOTE_ID" ;;
    *) printf '%s\n' "$MOCK_REMOTE_SSH_LAYERS" ;;
  esac
}
scp_run() { return 0; }

if [[ "${RUN_TAR}" -eq 1 ]]; then
  if transfer_image_via_tar "ghcr.io/mogoai/chat-api:latest" 4096; then
    printf '[TAR] ok\n'
  else
    printf '[TAR] fail\n'
  fi
  exit 0
fi

push_image "ghcr.io/mogoai/chat-api:latest" || printf '[RC] push_image=%s\n' "$?"
report_push_summary
printf '[COUNTS] stale=%s updated=%s failed=%s unverified=%s\n' \
  "${#STALE_IMAGES[@]}" "${#UPDATED_IMAGES[@]}" "${#FAILED_IMAGES[@]}" "${#UNVERIFIED_IMAGES[@]}"
"""


def _run_scenario(
    *,
    local_id: str = LOCAL_ID,
    remote_id: str = REMOTE_ID,
    local_layers: str | None = None,
    remote_layers: str | None = None,
    remote_ssh_layers: str | None = None,
    force_push: int = 0,
    arch: str = "amd64",
    run_tar: int = 0,
) -> str:
    # 未显式给层列表时，让层指纹与 ID 比对保持同一语义，旧用例结论不变。
    if local_layers is None:
        local_layers = LOCAL_LAYERS if local_id else ""
    if remote_layers is None:
        if not remote_id:
            remote_layers = ""
        elif remote_id == local_id:
            remote_layers = local_layers
        else:
            remote_layers = REMOTE_LAYERS
    if remote_ssh_layers is None:
        remote_ssh_layers = local_layers
    harness = (
        HARNESS.replace("__GUARD_BLOCK__", _guard_block())
        .replace("__FORCE_PUSH__", str(force_push))
        .replace("__RUN_TAR__", str(run_tar))
        .replace("__TMP_DIR__", PUSH_TMP_DIR_VALUE)
        .replace("__LOCAL_ID__", local_id)
        .replace("__REMOTE_ID__", remote_id)
        .replace("__LOCAL_LAYERS__", local_layers)
        .replace("__REMOTE_LAYERS__", remote_layers)
        .replace("__REMOTE_SSH_LAYERS__", remote_ssh_layers)
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
        "image_layers_local()",
        "image_layers_remote()",
        "normalize_fingerprint",
        "resolve_fingerprints",
        "{{.RootFS.Layers}}",
        "STALE_IMAGES",
        "report_push_summary",
        "verify_running_images",
        "transfer_image_via_tar",
        "PUSH_STREAM_MAX_MB",
        "scp_run",
        # dsh-runtime-host 必须跟随本次推送的版本，否则 .env 的 dev 固定 tag
        # 会被 compose 带到远端，up 直接 "No such image"。
        'export MOGO_DSH_RUNTIME_HOST_IMAGE="${MOGO_DSH_RUNTIME_HOST_IMAGE:-'
        "ghcr.io/mogoai/dsh-runtime-host:${MOGO_VERSION}}\"",
    ):
        assert needle in src, f"脚本缺少关键守卫: {needle}"
    # 内容指纹比对必须发生在 push_image 内，而不是只在别处定义。
    block = _guard_block()
    assert '"${remote_fp}" == "${local_fp}"' in block
    assert "STALE_IMAGES+=(" in block
    # .Id 只允许作为「拿不到层列表」时的兜底，不能再是直接判等依据。
    assert block.count("image_id_local") >= 1
    assert 'got}" != "${want}' in block or 'want}" != "${got}' in block


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


def test_same_layers_different_id_skips_without_push() -> None:
    """本地 containerd store 与远端 classic driver 的 .Id 必不同，层一致即内容一致。

    2026-11-07 实测：本地 chat-api ``6bd524f9…`` 对远端 ``75218173…``，18 层摘要完全
    相同。旧版按 ``.Id`` 判等 → 误报「内容不同/推送失败」，还诱发重复全量传输。
    """
    out = _run_scenario(remote_id=REMOTE_ID, remote_layers=LOCAL_LAYERS)
    assert "内容一致" in out
    assert "[TRANSFER]" not in out
    assert "内容不同" not in out
    assert "[COUNTS] stale=0 updated=0 failed=0 unverified=0" in out


def test_layer_format_differences_still_match() -> None:
    """层列表排版差异（方括号 / 换行）不影响判等。"""
    out = _run_scenario(
        remote_id=REMOTE_ID, remote_layers=REMOTE_LAYERS_SAME_OTHER_FORMAT
    )
    assert "内容一致" in out
    assert "[TRANSFER]" not in out


def test_fingerprint_falls_back_to_image_id_without_layers() -> None:
    """daemon 不输出层列表时退回 .Id 比对（一致 → 跳过；不一致 → stale）。"""
    same = _run_scenario(remote_id=LOCAL_ID, local_layers="", remote_layers="")
    assert "内容一致" in same and "[TRANSFER]" not in same
    assert "[COUNTS] stale=0 updated=0 failed=0 unverified=0" in same

    diff = _run_scenario(local_layers="", remote_layers="")
    assert "内容不同" in diff
    assert "[COUNTS] stale=1 updated=0 failed=0 unverified=0" in diff


def test_mixed_layer_availability_uses_one_kind() -> None:
    """只有一端能给出层列表时，两端一起退回 ID，不能出现「一边层一边 ID」的假不一致。"""
    out = _run_scenario(remote_id=LOCAL_ID, remote_layers="")
    assert "内容一致" in out
    assert "[TRANSFER]" not in out
    assert "[COUNTS] stale=0 updated=0 failed=0 unverified=0" in out


def test_missing_local_layers_but_present_id_still_detected() -> None:
    """本地拿不到内容（层与 ID 均空）→ 视为本地缺失，不误推。"""
    out = _run_scenario(local_id="", local_layers="")
    assert "本地缺失、远端存在" in out
    assert "[TRANSFER]" not in out


# ── 大镜像 tar 通道的远端校验 ───────────────────────────────────────────────

def test_tar_post_load_accepts_same_layers_with_different_id() -> None:
    """load 后远端 .Id 与本地不同但层一致：校验必须通过（旧版在这里误报失败）。"""
    out = _run_scenario(run_tar=1, remote_ssh_layers=LOCAL_LAYERS)
    assert "远端内容指纹校验通过" in out
    assert "[TAR] ok" in out
    assert "不一致" not in out


def test_tar_post_load_rejects_different_layers() -> None:
    out = _run_scenario(run_tar=1, remote_ssh_layers=REMOTE_LAYERS)
    assert "远端内容指纹不一致" in out
    assert "[TAR] fail" in out


def test_tar_post_load_falls_back_to_image_id() -> None:
    ok = _run_scenario(
        remote_id=LOCAL_ID, run_tar=1, remote_ssh_layers=""
    )
    assert "[TAR] ok" in ok

    bad = _run_scenario(remote_id=REMOTE_ID, run_tar=1, remote_ssh_layers="")
    assert "[TAR] fail" in bad


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
