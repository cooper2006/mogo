"""环境 profile 的静态回归守卫（dev / test / prod）。

三个环境的编码方式很「省字」，省到容易被人一眼看不出来、顺手改坏：

1. **profile 挂在数据库服务上，不挂在应用服务上**。Compose 只能「按 profile 启用
   服务」，不能「按 profile 禁用服务」，所以只有 `mongo`（dev）和 `panweidb`
   （test）带 profile，应用服务三个环境都起。谁要是把 profile 加到 chat-api
   上，`--profile prod` 就会把整个栈清空。
2. **应用服务对带 profile 的服务必须写 `required: false`**。少写一处，compose
   直接报 `service ... depends on undefined service ...`，整个文件解析失败——
   而这个错误只在不启用对应 profile 的环境里出现，arm64 开发机上永远看不到。
3. **架构靠 `platform: ${MOGO_PLATFORM:-}` 插值**，变量为空时该键整体消失，
   所以不走 CLI 的 `docker compose up` 仍然是宿主原生架构；而走 CLI 时架构必须
   由用户写明，宿主架构与 profile 目标不一致就直接拒绝启动。

     python -m pytest deploy/tests/test_env_profiles.py -q
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "docker-compose.yml"
CLI = REPO_ROOT / "mogo"
PROFILES_SH = REPO_ROOT / "deploy" / "cli" / "env-profiles.sh"
IMAGES_SH = REPO_ROOT / "deploy" / "cli" / "images.sh"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
DOC = REPO_ROOT / "docs" / "environments.md"

ENV_PROFILES = {"dev", "test", "prod"}
APP_SERVICES = (
    "chat-api",
    "admin-api",
    "document-api",
    "document-worker",
    "user-web",
    "admin-web",
    "gateway",
    "dsh-runtime-host",
)
PLATFORMED_SERVICES = APP_SERVICES


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


# ── profile 归属 ──────────────────────────────────────────────────────


def test_mongo_is_dev_only(compose: dict) -> None:
    profiles = compose["services"]["mongo"].get("profiles") or []
    assert profiles == ["dev"], (
        "mongo 只能属于 dev 环境（栈内 mongo 是开发环境的数据库），"
        f"实际：{profiles}"
    )


def test_panweidb_covers_test_and_legacy_profile(compose: dict) -> None:
    profiles = compose["services"]["panweidb"].get("profiles") or []
    assert "test" in profiles, "test 环境要靠 panweidb profile 把本地库带进拓扑"
    assert "panweidb" in profiles, (
        "保留 panweidb 名字：deploy/cli/images.sh 会按 MOGO_DATA_BACKEND 自动附加它"
    )


@pytest.mark.parametrize("service", ["redis", "weaviate"])
def test_shared_infra_has_no_env_profile(compose: dict, service: str) -> None:
    profiles = compose["services"][service].get("profiles") or []
    assert not ENV_PROFILES & set(profiles), (
        f"{service} 三个环境都在栈内（与 deploy/production 的 x86 模板一致），"
        f"不该带环境 profile，实际：{profiles}"
    )


@pytest.mark.parametrize("service", APP_SERVICES)
def test_app_services_are_profile_free(compose: dict, service: str) -> None:
    profiles = compose["services"][service].get("profiles") or []
    assert not ENV_PROFILES & set(profiles), (
        f"应用服务 {service} 不能带环境 profile：compose 只能按 profile 启用服务，"
        f"一加就会在别的环境里整套消失，实际：{profiles}"
    )


# ── 依赖：栈内数据库缺席时必须 required: false ─────────────────────────


def test_profiled_dependencies_are_optional(compose: dict) -> None:
    profiled = {
        name
        for name, service in compose["services"].items()
        if ENV_PROFILES & set(service.get("profiles") or [])
    }
    assert {"mongo", "panweidb"} <= profiled

    missing: list[str] = []
    for name, service in compose["services"].items():
        for dependency, spec in (service.get("depends_on") or {}).items():
            if dependency not in profiled:
                continue
            if not isinstance(spec, dict) or spec.get("required") is not False:
                missing.append(f"{name} -> {dependency}")
    assert not missing, (
        "这些 depends_on 指向带 profile 的服务却没有 required: false，"
        "未启用该 profile 时 compose 会报 depends on undefined service：" + ", ".join(missing)
    )


def test_external_override_keeps_dependencies_optional() -> None:
    override = yaml.safe_load(
        (REPO_ROOT / "docker-compose.external.yml").read_text(encoding="utf-8")
    )
    for name, service in (override.get("services") or {}).items():
        for dependency, spec in (service.get("depends_on") or {}).items():
            if isinstance(spec, dict):
                assert spec.get("required") is False, (
                    f"docker-compose.external.yml 里 {name} -> {dependency} 也要 required: false"
                )


# ── 架构插值 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("service", PLATFORMED_SERVICES)
def test_services_interpolate_platform(compose: dict, service: str) -> None:
    platform = compose["services"][service].get("platform")
    assert platform == "${MOGO_PLATFORM:-}", (
        f"{service} 必须写成 platform: ${{MOGO_PLATFORM:-}}：变量为空时该键消失，"
        f"保留宿主原生架构；写死 linux/arm64 会让 x86 生产机起不来，实际：{platform}"
    )


# ── CLI 与文档 ────────────────────────────────────────────────────────


def test_cli_parses_profile_flag() -> None:
    text = CLI.read_text(encoding="utf-8")
    assert "--profile)" in text or "--profile=*)" in text, "mogo CLI 需要解析 --profile"
    assert "mogo_apply_profile" in text, "mogo CLI 分发前必须调用 mogo_apply_profile"
    assert "env-profiles.sh" in text, "mogo CLI 需要 source deploy/cli/env-profiles.sh"


def test_dev_sh_participates_in_profiles() -> None:
    text = (REPO_ROOT / "dev.sh").read_text(encoding="utf-8")
    assert "--profile" in text, "dev.sh 也要接受 --profile"
    assert "env-profiles.sh" in text, "dev.sh 要 source 同一份 profile 实现"
    assert re.search(r"mogo_apply_profile\s+true\s+false", text), (
        "dev.sh 起的是宿主原生进程，调用 mogo_apply_profile 时要把 pin_platform 关掉"
    )


def test_cli_pins_platform_only_for_container_commands() -> None:
    text = CLI.read_text(encoding="utf-8")
    assert "profile_pin_platform" in text
    match = re.search(
        r"profile_pin_platform=false\ncase .*?\n\s+([a-z|]+)\)", text, re.DOTALL
    )
    assert match, "找不到 profile_pin_platform 的命令白名单"
    commands = set(match.group(1).split("|"))
    # 收拾现场 / 查看类的命令不能被架构校验挡住
    assert not commands & {"down", "status", "logs", "ps", "stop"}, (
        f"这些命令不该要求先指定架构：{commands}"
    )
    assert {"up", "build", "update"} <= commands


def test_cli_down_covers_all_environments() -> None:
    text = CLI.read_text(encoding="utf-8")
    assert "mogo_profile_cover_all_environments" in text, (
        "down 要把三个环境 profile 一起并进 COMPOSE_PROFILES，否则切环境后"
        "上一个环境起的数据库容器会留下来"
    )


def test_panweidb_profile_is_delivered_through_compose_profiles() -> None:
    """images.sh 不能用命令行 `--profile` 投递 profile。

    实测 docker compose 5.5.0：命令行 `--profile` **覆盖** COMPOSE_PROFILES，
    而不是与它取并集。`mogo_compose` 一旦带着 `--profile panweidb`，
    env-profiles.sh 导出的 dev/test/prod 就全部失效，`./mogo down` 于是漏掉
    mongo 等别的环境的数据库容器，并把所属网络报成 "Resource is still in use"。
    """
    text = IMAGES_SH.read_text(encoding="utf-8")
    assert "compose_args+=(--profile" not in text, (
        "deploy/cli/images.sh 不应把 --profile 交给 docker compose 命令行，"
        "应改成 mogo_enable_compose_profile（并入 COMPOSE_PROFILES）"
    )
    assert "mogo_enable_compose_profile panweidb" in text


@pytest.mark.skipif(shutil.which("bash") is None, reason="需要 bash 才能验证 profile 并集行为")
def test_compose_profile_union_keeps_other_environments(tmp_path: Path) -> None:
    stub = tmp_path / "docker"
    args_file = tmp_path / "args.txt"
    stub.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$FAKE_ARGS_FILE"\n', encoding="utf-8")
    stub.chmod(0o755)
    script = f"""
set -u
ROOT_DIR={REPO_ROOT}
DOCKER_BIN={stub}
export FAKE_ARGS_FILE={args_file}
source {IMAGES_SH}
export COMPOSE_PROFILES=dev,test,prod
export MOGO_DATA_BACKEND=panweidb
mogo_compose down
printf 'PROFILES=%s\\n' "${{COMPOSE_PROFILES}}"
"""
    result = subprocess.run(
        [shutil.which("bash"), "-c", script], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert "PROFILES=dev,test,prod,panweidb" in result.stdout, result.stdout
    invoked = args_file.read_text(encoding="utf-8")
    assert "--profile" not in invoked, f"命令行不应出现 --profile：{invoked}"


def test_profile_module_exports_expected_mapping() -> None:
    text = PROFILES_SH.read_text(encoding="utf-8")
    for expected in ("dev", "test", "prod", "linux/arm64", "linux/amd64", "MOGO_PLATFORM"):
        assert expected in text, f"deploy/cli/env-profiles.sh 缺少 {expected}"
    assert "mogo_apply_profile" in text


def test_example_env_and_docs_document_profiles() -> None:
    assert "MOGO_PROFILE" in ENV_EXAMPLE.read_text(encoding="utf-8")
    assert DOC.exists(), "三个环境的说明文档缺失：docs/environments.md"


# ── 行为：profile -> 后端 / 平台 / COMPOSE_PROFILES ───────────────────


BASH = shutil.which("bash")
HOST_PLATFORM = (
    "linux/arm64" if platform.machine() in ("arm64", "aarch64")
    else "linux/amd64" if platform.machine() in ("x86_64", "amd64")
    else ""
)


def _run_profile_bash(setup: str, tmp_path: Path) -> subprocess.CompletedProcess:
    script = f"""
set -Eeuo pipefail
{setup}
dotenv_value() {{ printf ''; }}
mogo_detect_locale() {{ MOGO_LOCALE=en; }}
source "{PROFILES_SH}"
mogo_apply_profile false >/dev/null 2>&1
printf 'backend=%s\\nprofiles=%s\\nplatform=%s\\n' "$MOGO_DATA_BACKEND" "$COMPOSE_PROFILES" "${{MOGO_PLATFORM:-}}"
"""
    return subprocess.run(
        [BASH, "-c", script], capture_output=True, text=True, timeout=60, cwd=tmp_path
    )


@pytest.mark.skipif(BASH is None, reason="需要 bash")
@pytest.mark.parametrize(
    ("profile", "backend"),
    [("dev", "mongo"), ("test", "panweidb")],
)
def test_apply_profile_exports_backend_and_platform(
    tmp_path: Path, profile: str, backend: str
) -> None:
    # 显式给架构时 CLI 不得改写（用 arm64 作为哨兵值，与宿主无关）。
    result = _run_profile_bash(
        f"export MOGO_PROFILE={profile} MOGO_DATA_BACKEND=mongo "
        "MOGO_USE_EXTERNAL_DB=0 MOGO_PLATFORM=linux/arm64",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    values = dict(
        line.split("=", 1) for line in result.stdout.strip().splitlines() if "=" in line
    )
    assert values["backend"] == backend
    assert values["profiles"] == profile
    assert values["platform"] == "linux/arm64", "显式 MOGO_PLATFORM 必须原样保留"


@pytest.mark.skipif(BASH is None, reason="需要 bash")
@pytest.mark.skipif(not HOST_PLATFORM, reason="无法识别宿主架构")
def test_apply_profile_requires_explicit_arch(tmp_path: Path) -> None:
    # 目标架构与宿主不一致、又没写 MOGO_PLATFORM 时必须拒绝启动，
    # 不能悄悄退回宿主架构（用户已明确：架构要在运行前指定）。
    profile = "prod" if HOST_PLATFORM == "linux/arm64" else "dev"
    rejected = _run_profile_bash(
        f"export MOGO_PROFILE={profile} MOGO_DATA_BACKEND=panweidb "
        "MOGO_USE_EXTERNAL_DB=0 PANWEIDB_HOST=db.example.com",
        tmp_path,
    )
    assert rejected.returncode == 2, f"架构不明时应当拒绝，实际 {rejected.returncode}"

    accepted = _run_profile_bash(
        f"export MOGO_PROFILE={profile} MOGO_DATA_BACKEND=panweidb "
        f"MOGO_USE_EXTERNAL_DB=0 PANWEIDB_HOST=db.example.com MOGO_PLATFORM={HOST_PLATFORM}",
        tmp_path,
    )
    assert accepted.returncode == 0, accepted.stderr
    assert f"platform={HOST_PLATFORM}" in accepted.stdout


@pytest.mark.skipif(BASH is None, reason="需要 bash")
def test_apply_profile_rejects_bad_input(tmp_path: Path) -> None:
    cases = {
        "unknown_profile": "MOGO_PROFILE=bogus",
        # dev 固定 mongo，撞上 panweidb 后端必须直接失败，不能带着半截配置启动
        "dev_needs_mongo": "MOGO_PROFILE=dev MOGO_DATA_BACKEND=panweidb",
        # prod 要求数据库在栈外
        "prod_needs_external": "MOGO_PROFILE=prod PANWEIDB_HOST=panweidb",
    }
    for name, setup in cases.items():
        result = _run_profile_bash(setup, tmp_path)
        assert result.returncode != 0, f"{name} 应当被拒绝，但成功了"
