"""022 US3 (T029) — 容器非 root 与容器加固集成测试。

覆盖三条验收线：

1. 4 个应用镜像以非 root 用户运行（``USER appuser``，UID/GID 10001）；
2. docker-compose 为每个应用容器设置 ``no-new-privileges`` / ``cap_drop ALL`` /
   ``read_only`` / tmpfs 工作区；
3. 已构建的镜像在加固参数下能真正启动并报告非 root uid。

前两条是静态检查（不依赖 docker daemon，CI 上任何平台可跑）。
第三条是运行时检查：镜像不在本地时自动 skip，本地构建后可直接跑。

用法::

    python -m pytest deploy/tests/test_container_hardening.py -q
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# 服务名 -> (Dockerfile 相对路径, compose 里的 service key)
APPLICATION_SERVICES = {
    "admin-api": ("services/admin-api/Dockerfile", "admin-api"),
    "chat-api": ("services/chat-api/Dockerfile", "chat-api"),
    "document-parser": ("services/document-parser/Dockerfile", "document-api"),
    "admin-web": ("apps/admin-web/Dockerfile", "admin-web"),
    "user-web": ("apps/user-web/Dockerfile.prod", "user-web"),
}

# 三个 nginx 服务 -> 它们各自的「非 root 主配置」。
# user-web 与 gateway 曾经漏做这一步：compose 已给它们 read_only + cap_drop ALL，
# 但镜像里仍是 root master + stock 主配置（`user nginx;` + pid 在 /var/run），
# 启动即 `chown("/var/cache/nginx/client_temp", 101) failed (1: Operation not permitted)`
# 崩溃重启。这里把三个服务一起钉住，防止再漏。
NGINX_MAIN_CONFIGS = {
    "admin-web": "apps/admin-web/nginx-main.conf",
    "user-web": "apps/user-web/nginx-main.conf",
    "gateway": "deploy/docker/nginx-main.conf",
}

# 需要 read_only + tmpfs 的全部应用/网关服务
HARDENED_SERVICES = [
    "bootstrap",
    "chat-api",
    "admin-api",
    "document-api",
    "document-worker",
    "user-web",
    "admin-web",
    "gateway",
]

# 镜像名 -> 服务。用于运行时 uid 校验（T029 的 `docker exec id` 一步）。
IMAGE_NAMES = {
    "admin-api": "ghcr.io/himovo/admin-api",
    "chat-api": "ghcr.io/himovo/chat-api",
    "document-parser": "ghcr.io/himovo/document-parser",
    "admin-web": "ghcr.io/himovo/admin-web",
    "user-web": "ghcr.io/himovo/user-web",
    "gateway": "ghcr.io/himovo/gateway",
}


def _dockerfile(name: str) -> str:
    rel = APPLICATION_SERVICES[name][0]
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _compose_config() -> dict:
    """返回 `docker compose config --format json` 解析后的结构。"""
    out = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "config", "--format", "json"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(out)


# ---------------------------------------------------------------------------
# 静态检查：Dockerfile
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(APPLICATION_SERVICES))
def test_dockerfile_declares_non_root_user(name: str) -> None:
    """4 个应用镜像都必须切到非 root 用户。"""
    text = _dockerfile(name)
    assert re.search(r"^USER\s+appuser\b", text, re.M), (
        f"{name} Dockerfile 缺少 `USER appuser`"
    )


@pytest.mark.parametrize("name", sorted(APPLICATION_SERVICES))
def test_dockerfile_uses_uid_gid_10001(name: str) -> None:
    """UID/GID 10001 是仓库统一约定，便于 host 侧按 uid 做审计与隔离。"""
    text = _dockerfile(name)
    assert "10001" in text, f"{name} Dockerfile 未出现 10001"
    assert "appuser" in text


@pytest.mark.parametrize(
    "name",
    ["admin-api", "chat-api", "document-parser"],
)
def test_python_image_chowns_writable_paths(name: str) -> None:
    """Python 服务必须 chown 可写路径，否则 named volume 是 root 属主。"""
    text = _dockerfile(name)
    assert "chown -R appuser:appuser" in text, f"{name} 缺少 chown -R appuser:appuser"
    # 数据目录必须在 chown 之前被创建
    assert re.search(r"mkdir -p\s+(\S+).*?\n.*?chown", text, re.S), (
        f"{name}: mkdir 必须在 chown 之前"
    )


def test_admin_web_creates_user_with_busybox_syntax() -> None:
    """nginx 基于 Alpine/BusyBox，必须用 addgroup/adduser 而不是 groupadd/useradd。"""
    text = _dockerfile("admin-web")
    # 只看 RUN 指令本身，注释里提到 groupadd 作为对比是允许的。
    run_lines = [
        line for line in text.splitlines()
        if line.strip().startswith(("RUN", "&&"))
    ]
    run_body = "\n".join(run_lines)
    assert "addgroup -g 10001 -S appuser" in run_body
    assert "adduser -S -H -D -G appuser" in run_body
    assert "groupadd" not in run_body
    assert "useradd " not in run_body


def test_admin_web_ships_non_root_nginx_main_config() -> None:
    """非 root master 不能用 stock 主配置（`user nginx;` + pid 在 /var/run）。"""
    conf_path = REPO_ROOT / "apps/admin-web/nginx-main.conf"
    assert conf_path.exists(), "缺少 apps/admin-web/nginx-main.conf"
    conf = conf_path.read_text(encoding="utf-8")
    assert not re.search(r"^\s*user\s+nginx\s*;", conf, re.M), (
        "非 root master 不应保留 `user nginx;` 指令"
    )
    assert re.search(r"^\s*pid\s+/tmp/nginx\.pid\s*;", conf, re.M), (
        "pid 文件必须放在非 root 可写的 /tmp"
    )


@pytest.mark.parametrize("service", sorted(NGINX_MAIN_CONFIGS))
def test_nginx_images_ship_non_root_main_config(service: str) -> None:
    """三个 nginx 服务都必须带非 root 主配置，且镜像里确实 COPY 了它。

    只断言配置文件存在是不够的：曾经存在「文件在、Dockerfile 没 COPY」的形态，
    镜像实际仍跑 stock 主配置。所以这里同时检查 Dockerfile 的 COPY 与 USER。
    """
    conf_rel = NGINX_MAIN_CONFIGS[service]
    conf_path = REPO_ROOT / conf_rel
    assert conf_path.exists(), f"缺少 {conf_rel}"

    conf = conf_path.read_text(encoding="utf-8")
    assert not re.search(r"^\s*user\s+nginx\s*;", conf, re.M), (
        f"{conf_rel}: 非 root master 不应保留 `user nginx;` 指令"
    )
    assert re.search(r"^\s*pid\s+/tmp/nginx\.pid\s*;", conf, re.M), (
        f"{conf_rel}: pid 文件必须放在非 root 可写的 /tmp"
    )

    dockerfile_rel = APPLICATION_SERVICES.get(service, (None, None))[0]
    if dockerfile_rel is None:
        # gateway 的 Dockerfile 不在 APPLICATION_SERVICES 里（它不是 Python/前端应用镜像）。
        dockerfile_rel = "deploy/docker/gateway.Dockerfile"
    text = (REPO_ROOT / dockerfile_rel).read_text(encoding="utf-8")
    conf_basename = conf_rel.rsplit("/", 1)[-1]
    assert re.search(rf"^COPY\s+{re.escape(conf_basename)}\s+/etc/nginx/nginx\.conf", text, re.M), (
        f"{dockerfile_rel}: 未把 {conf_basename} COPY 成 /etc/nginx/nginx.conf"
    )
    assert re.search(r"^USER\s+appuser\b", text, re.M), (
        f"{dockerfile_rel}: 缺少 `USER appuser`"
    )


# ---------------------------------------------------------------------------
# 静态检查：docker-compose
# ---------------------------------------------------------------------------


def test_compose_file_parses() -> None:
    cfg = _compose_config()
    assert "services" in cfg
    for service in HARDENED_SERVICES:
        assert service in cfg["services"], f"compose 缺少服务 {service}"


@pytest.mark.parametrize("service", HARDENED_SERVICES)
def test_compose_service_drops_all_capabilities(service: str) -> None:
    services = _compose_config()["services"]
    caps = services[service].get("cap_drop") or []
    assert caps == ["ALL"], f"{service}.cap_drop 应为 [ALL]，实际 {caps}"


@pytest.mark.parametrize("service", HARDENED_SERVICES)
def test_compose_service_forbids_privilege_escalation(service: str) -> None:
    services = _compose_config()["services"]
    opts = [str(o) for o in (services[service].get("security_opt") or [])]
    assert "no-new-privileges:true" in opts, f"{service} 缺少 no-new-privileges"


@pytest.mark.parametrize(
    "service", ["chat-api", "admin-api", "document-api", "document-worker", "user-web", "admin-web", "gateway"]
)
def test_compose_service_runs_read_only(service: str) -> None:
    """应用/网关容器的镜像 rootfs 必须只读，禁止运行期落地后门。"""
    assert _compose_config()["services"][service].get("read_only") is True


@pytest.mark.parametrize(
    "service", ["chat-api", "admin-api", "document-api", "document-worker", "user-web", "admin-web", "gateway"]
)
def test_compose_service_mounts_writable_tmpfs(service: str) -> None:
    tmpfs = list(_compose_config()["services"][service].get("tmpfs") or [])
    assert any(str(m).startswith("/tmp") for m in tmpfs), f"{service} 缺少 /tmp tmpfs"
    for mount in tmpfs:
        spec = str(mount)
        # 必须显式指定 mode：Docker 的 tmpfs 默认是 0755，非 root 用户写不进去。
        assert re.search(r"mode=0?\d+", spec), f"{service} tmpfs 缺少 mode={spec}"


@pytest.mark.parametrize("service", ["admin-web", "user-web", "gateway"])
def test_compose_nginx_services_mount_cache_and_logs(service: str) -> None:
    """read_only 下 nginx 的缓存/日志目录必须是 tmpfs，否则启动即退出。"""
    tmpfs = [str(m) for m in _compose_config()["services"][service].get("tmpfs") or []]
    assert any(m.startswith("/var/cache/nginx") for m in tmpfs)
    assert any(m.startswith("/var/log/nginx") for m in tmpfs)


@pytest.mark.parametrize("service", ["admin-web", "user-web", "gateway"])
def test_compose_nginx_grants_only_net_bind_service(service: str) -> None:
    caps = _compose_config()["services"][service].get("cap_add") or []
    assert caps == ["NET_BIND_SERVICE"], (
        f"{service} 只应保留 NET_BIND_SERVICE（用于绑定 80 端口），实际 {caps}"
    )


def test_compose_bootstrap_writes_world_readable_secrets() -> None:
    """应用容器以 appuser 运行，runtime.env 若为 0600 则它们读不到自己的密钥。"""
    text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "umask 022" in text, "bootstrap 必须用 umask 022 生成 0644 的 runtime.env"
    assert "umask 077" not in text


# ---------------------------------------------------------------------------
# 静态检查：服务自身的存储路径默认值必须是绝对路径
# ---------------------------------------------------------------------------
#
# read_only: true 让镜像 rootfs 不可写。任何落在 /app 下的相对路径
# （resolve 后随 WORKDIR 变化）都会在 mkdir 时以 EROFS 崩溃。


@pytest.mark.parametrize(
    ("path", "default"),
    [
        ("services/admin-api/app/core/config.py", "/data/admin-static"),
        ("services/document-parser/app/core/config.py", "/data/knowledge-documents"),
        ("services/chat-api/app/utils/report_file_manager.py", "/app/storage/reports/markdown"),
    ],
)
def test_storage_defaults_are_absolute_and_writable(path: str, default: str) -> None:
    """相对路径默认值在 read_only 容器里必然崩溃，必须是绝对路径。

    chat-api 的 ``LOCAL_STORAGE_PATH`` 例外：它保留相对默认值以便 host 侧
    dev/测试直接跑，改由 compose 显式设置绝对路径（见下一个测试）。
    """
    text = (REPO_ROOT / path).read_text(encoding="utf-8")
    assert f'"{default}"' in text, f"{path} 缺少默认值 {default!r}"
    assert default.startswith("/"), f"{path}: {default!r} 不是绝对路径"


@pytest.mark.parametrize(
    ("service", "env_var"),
    [
        ("chat-api", "LOCAL_STORAGE_PATH"),
        ("admin-api", "ASKAI_ADMIN_ADMIN_STATIC_DIR"),
        ("document-api", "MOVO_DOC_PROCESSING_LOCAL_STORAGE_DIR"),
        ("document-worker", "MOVO_DOC_PROCESSING_LOCAL_STORAGE_DIR"),
    ],
)
def test_compose_pins_storage_paths_to_mounted_volumes(service: str, env_var: str) -> None:
    """应用容器必须把存储目录指向已挂载的卷，否则 read_only 下写入必然失败。"""
    services = _compose_config()["services"]
    assert service in services
    env = services[service].get("environment") or {}
    assert env_var in env, f"{service} 未在 compose 中设置 {env_var}"
    value = str(env[env_var] or "")
    assert value.startswith("/"), f"{service}.{env_var} 应为绝对路径，实际 {value!r}"
    # 该路径必须是本服务 volumes 里挂载的卷
    volumes = services[service].get("volumes") or []
    targets = []
    for volume in volumes:
        if isinstance(volume, dict):
            targets.append(str(volume.get("target") or ""))
        else:
            # 短语法 "host:target[:mode]"
            targets.append(str(volume).split(":")[-2] if ":" in str(volume) else "")
    assert value in targets, f"{service}.{env_var}={value} 没有对应卷挂载: {targets}"


def test_admin_api_static_mount_degrades_gracefully() -> None:
    """静态目录不可写时必须告警降级，不能阻断整个 API 启动。"""
    text = (REPO_ROOT / "services/admin-api/app/main.py").read_text(encoding="utf-8")
    assert "not writable" in text
    assert "skip" in text.lower()


def test_report_file_manager_degrades_gracefully() -> None:
    """报告目录不可写时必须告警降级，不能阻断模块导入。"""
    text = (REPO_ROOT / "services/chat-api/app/utils/report_file_manager.py").read_text(
        encoding="utf-8"
    )
    assert "not writable" in text
    assert "logger.warning" in text


# ---------------------------------------------------------------------------
# 运行时检查：镜像必须真的以非 root 跑起来
# ---------------------------------------------------------------------------


def _image_present(image_ref: str) -> bool:
    try:
        out = subprocess.run(
            ["docker", "image", "inspect", image_ref],
            capture_output=True, text=True, timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0


def _version_tag() -> str:
    return os.environ.get("MOGO_VERSION") or os.environ.get("MOVO_VERSION") or "latest"


@pytest.mark.parametrize("service", sorted(IMAGE_NAMES))
def test_image_runs_as_non_root(service: str) -> None:
    """T029 的核心断言：容器内 `id -u` 不等于 0。"""
    if shutil.which("docker") is None:
        pytest.skip("docker 不可用")
    ref = f"{IMAGE_NAMES[service]}:{_version_tag()}"
    if not _image_present(ref):
        pytest.skip(f"镜像 {ref} 未在本机构建")

    flags = [
        "docker", "run", "--rm",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true",
        "--read-only",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m,mode=1777",
    ]
    if service in ("admin-web", "gateway"):
        flags += ["--cap-add", "NET_BIND_SERVICE",
                  "--tmpfs", "/var/cache/nginx:rw,nosuid,nodev,size=128m,mode=0777",
                  "--tmpfs", "/var/log/nginx:rw,nosuid,nodev,size=64m,mode=0777"]

    out = subprocess.run(
        flags + [ref, "sh", "-c", "id -u; id -Gn"],
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, f"{ref} 启动失败：{out.stderr.strip()}"
    uid = out.stdout.strip().splitlines()[0].strip()
    assert uid != "0", f"{ref} 仍以 root 运行（uid={uid}）"
