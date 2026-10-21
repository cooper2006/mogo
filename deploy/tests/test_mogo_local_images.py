"""`./mogo` 本地镜像解析与 registry 链路停用的回归守卫。

背景（2026-10-13）：纯 registry 部署链路已确认断开。GHCR 上真实存在的包名与本仓库
生成的引用曾经拼不上（旧 `ghcr.io/himovo/movo-<service>` 形态），实测
`error from registry: denied`。更糟的是 `mogo_pull_images_serially` 对失败
**无限重试**，所以裸 `./mogo up` 会在拉取里挂住好几分钟才失败。

现在的约定：

* `./mogo up`（不带 `--build`）**只使用本地镜像**：按源码构建产出的裸名引用，
  版本同样取自 `git describe --tags --always`（与 `up --build` 一致，这样裸 `up`
  才能找到刚构建的 `chat-api:v0.2.1`），并校验镜像在位，缺失则点名报错。
* `./mogo update` 已停用并快速失败——它原本就是那条 registry 链路。
* 基础镜像（mongo / redis / weaviate / nginx / alpine）是另一条可用链路，仍由
  `mogo_prepare_base_images` 处理，`MOGO_BASE_IMAGE_POLICY=local` 可完全离线。

运行::

    python -m pytest deploy/tests/test_mogo_local_images.py -q
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_MOGO = "mogo"

# 真实执行 mogo_require_local_images 所需的桩（不碰 docker）。
_HARNESS = """set -Eeuo pipefail
source "$ROOT_DIR/deploy/cli/images.sh"
source "$ROOT_DIR/deploy/cli/i18n.sh"
mogo_detect_locale
dotenv_value() { sed -n "s/^[[:space:]]*$1=//p" "$FAKE_ENV" 2>/dev/null | tail -n1 || true; }
DOCKER_BIN="${DOCKER_BIN:-docker}"
eval "$(sed -n '/^mogo_require_local_images()/,/^}/p' "$ROOT_DIR/mogo")"
mogo_require_local_images
"""


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _top_level_block(text: str, name: str) -> str:
    """取顶层函数体：从 `name() {` 到下一个顶格 `}`（嵌套的 `}` 不终止）。"""
    match = re.search(rf"^{re.escape(name)}\(\) \{{.*?^\}}", text, re.M | re.S)
    assert match, f"{name} 未找到"
    return match.group(0)


def _else_branches(body: str) -> list[str]:
    """函数体内所有顶层 `else` 分支的正文（本仓库风格：`else` 独立成行）。"""
    blocks: list[str] = []
    rest = body
    while "\n  else\n" in rest:
        start = rest.index("\n  else\n") + len("\n  else\n")
        end = rest.index("\n  fi\n", start)
        blocks.append(rest[start:end])
        rest = rest[end:]
    return blocks


def _non_build_branch(body: str) -> str:
    """command_up 全部非构建分支的正文（不带 --build 的两条路径）。"""
    return "\n".join(_else_branches(body))


def _command_up_body(text: str) -> str:
    return _top_level_block(text, "command_up")


def _update_body(text: str) -> str:
    return _top_level_block(text, "command_update")


def _calls(text: str, name: str) -> bool:
    """函数体里是否有对 name 的**真实调用**（忽略注释与文档字符串）。"""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if name in stripped:
            return True
    return False


def test_up_never_builds_pulls_application_images() -> None:
    """非构建分支不得再调用串行拉取（那只会在 denied 上无限重试）。"""
    body = _command_up_body(_read(_MOGO))
    else_part = _non_build_branch(body)
    assert not _calls(else_part, "mogo_pull_images_serially"), (
        "command_up 的非构建分支仍在调用 mogo_pull_images_serially；"
        "GHCR 引用不存在，它会无限重试"
    )


def test_up_requires_local_images_and_uses_release_tag() -> None:
    """非构建分支必须：按 tag 版本解析、用裸名、校验本地镜像。"""
    text = _read(_MOGO)
    else_part = _non_build_branch(_command_up_body(text))

    assert _calls(else_part, "mogo_require_local_images"), (
        "command_up 非构建分支未校验本地镜像"
    )
    assert "${MOGO_VERSION:-$(mogo_default_version)}" in else_part, (
        "非构建分支的版本没有取自 git tag；裸 ./mogo up 会去找 "
        "chat-api:latest（不存在）而不是刚构建的 chat-api:v0.2.1"
    )
    # 源码构建（裸名）与「不构建但用本地镜像」必须走同一个镜像命名，
    # 否则 compose 引用的是 ghcr.io/mogoai/mogo/<svc>，本地裸名镜像对不上。
    assert "mogo_configure_images true" in else_part, (
        "非构建分支仍用 registry 前缀命名；本地构建产物是裸名，会失配"
    )


def test_update_is_retired_and_fails_fast() -> None:
    """update 是纯 registry 链路，必须快速失败而不是无限重试。"""
    body = _update_body(_read(_MOGO))
    assert "update_registry_retired" in body, "command_update 未给出明确的停用提示"
    assert not _calls(body, "mogo_pull_images_serially"), (
        "command_update 仍在调用会无限重试的 registry 拉取"
    )
    assert "return 2" in body, "command_update 应以非零码退出"


def test_base_images_still_resolved_for_up() -> None:
    """基础镜像链路保留：非构建分支仍要准备基础镜像。"""
    body = _command_up_body(_read(_MOGO))
    else_part = _non_build_branch(body)
    assert _calls(else_part, "mogo_prepare_base_images"), (
        "非构建分支不再准备基础镜像；裸 ./mogo up 会因缺 mongo/redis 等直接失败"
    )


def _run_require_local_images(
    tmp_path: Path, *, present: list[str], missing: list[str]
):
    """真实执行 mogo_require_local_images：用假 docker 桩控制 inspect 结果。"""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / ".env").write_text("", encoding="utf-8")

    # 假 docker：对 present 列表里的引用 inspect 成功，其余失败。
    present_literal = " ".join(present)
    docker_stub = fake_bin / "docker"
    docker_stub.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = image ] && [ "$2" = inspect ]; then\n'
        f'  for ref in {present_literal}; do\n'
        '    [ "$3" = "$ref" ] && exit 0\n'
        "  done\n"
        "  exit 1\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    docker_stub.chmod(0o755)

    script = tmp_path / "harness.sh"
    script.write_text(_HARNESS, encoding="utf-8")

    env = os.environ.copy()
    env.update(
        ROOT_DIR=str(REPO_ROOT),
        FAKE_ENV=str(fake_bin / ".env"),
        DOCKER_BIN=str(docker_stub),
        # 七个别名全部指向「存在」，只留 missing 里的为失败
        MOGO_DSH_RUNTIME_HOST_IMAGE="dsh-runtime-host:v0.2.1",
        MOGO_CHAT_API_IMAGE="chat-api:v0.2.1",
        MOGO_ADMIN_API_IMAGE="admin-api:v0.2.1",
        MOGO_USER_WEB_IMAGE="user-web:v0.2.1",
        MOGO_ADMIN_WEB_IMAGE="admin-web:v0.2.1",
        MOGO_GATEWAY_IMAGE="gateway:v0.2.1",
        MOGO_DOCUMENT_API_IMAGE="document-parser:v0.2.1",
    )
    for ref in missing:
        for key, value in list(env.items()):
            if value == ref:
                env[key] = "missing/" + value
    return subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, env=env, timeout=60
    )


def test_require_local_images_passes_when_all_present(tmp_path: Path) -> None:
    present = [
        "dsh-runtime-host:v0.2.1",
        "chat-api:v0.2.1",
        "admin-api:v0.2.1",
        "user-web:v0.2.1",
        "admin-web:v0.2.1",
        "gateway:v0.2.1",
        "document-parser:v0.2.1",
    ]
    result = _run_require_local_images(tmp_path, present=present, missing=[])
    assert result.returncode == 0, result.stderr


def test_require_local_images_names_the_missing_ones(tmp_path: Path) -> None:
    present = [
        "dsh-runtime-host:v0.2.1",
        "admin-api:v0.2.1",
        "user-web:v0.2.1",
        "admin-web:v0.2.1",
        "gateway:v0.2.1",
        "document-parser:v0.2.1",
    ]
    result = _run_require_local_images(
        tmp_path, present=present, missing=["chat-api:v0.2.1"]
    )
    assert result.returncode != 0, "缺镜像时应失败"
    message = result.stdout + result.stderr
    assert "chat-api:v0.2.1" in message, "未点名缺失的镜像"
    assert "./mogo up --build" in message, "未告知修复命令"
    # 只报缺失的那个，不要把在场的也列出来
    assert "admin-api" not in message, "把在场的镜像也列进去了"


def test_i18n_covers_local_image_and_update_messages() -> None:
    text = _read("deploy/cli/i18n.sh")
    for key in (
        "local_images_missing",
        "local_images_missing_hint",
        "update_registry_retired",
    ):
        for locale in ("zh", "en"):
            assert f"{locale}:{key})" in text, f"i18n 缺少 {locale}:{key}"
