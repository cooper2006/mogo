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
#
# DSH Runtime Host 池副本（dsh-runtime-host-{1,2,3}）的加固字段来自
# ``x-dsh-runtime-host-template``：副本自身只覆盖 ``environment``/``volumes``，
# 而 YAML 锚点（``<<:``）是**浅合并** —— 只要锚点带上加固，三个副本都会继承。
# 这里把副本一起钉住，避免将来有人只改锚点或只改副本而产生漂移。
DSH_RUNTIME_HOST_POOL = [
    "dsh-runtime-host-1",
    "dsh-runtime-host-2",
    "dsh-runtime-host-3",
]

HARDENED_SERVICES = [
    "bootstrap",
    "chat-api",
    "admin-api",
    "document-api",
    "document-worker",
    "user-web",
    "admin-web",
    "gateway",
    *DSH_RUNTIME_HOST_POOL,
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


def _compose_config(profile: str | None = None) -> dict:
    """返回 `docker compose config --format json` 解析后的结构。

    ``profile`` 用于渲染被 profile 门控的服务：``dsh-runtime-host`` 的单副本
    拓扑只存在于 ``--profile single-host`` 下，默认配置里根本看不到它。
    """
    cmd = ["docker", "compose", "-f", "docker-compose.yml"]
    if profile:
        cmd += ["--profile", profile]
    out = subprocess.run(
        cmd + ["config", "--format", "json"],
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
    # HARDENED_SERVICES 包含 pool 拓扑的 dsh-runtime-host-{1,2,3}，
    # 这些服务仅在 --profile pool 下可见；单副本拓扑由
    # test_dsh_runtime_host_single_host_profile_is_hardened 单独覆盖。
    cfg = _compose_config(profile="pool")
    assert "services" in cfg
    for service in HARDENED_SERVICES:
        assert service in cfg["services"], f"compose --profile pool 缺少服务 {service}"


@pytest.mark.parametrize("service", HARDENED_SERVICES)
def test_compose_service_drops_all_capabilities(service: str) -> None:
    services = _compose_config(profile="pool")["services"]
    caps = services[service].get("cap_drop") or []
    assert caps == ["ALL"], f"{service}.cap_drop 应为 [ALL]，实际 {caps}"


@pytest.mark.parametrize("service", HARDENED_SERVICES)
def test_compose_service_forbids_privilege_escalation(service: str) -> None:
    services = _compose_config(profile="pool")["services"]
    opts = [str(o) for o in (services[service].get("security_opt") or [])]
    assert "no-new-privileges:true" in opts, f"{service} 缺少 no-new-privileges"


@pytest.mark.parametrize(
    "service",
    ["chat-api", "admin-api", "document-api", "document-worker", "user-web", "admin-web", "gateway", *DSH_RUNTIME_HOST_POOL],
)
def test_compose_service_runs_read_only(service: str) -> None:
    """应用/网关容器的镜像 rootfs 必须只读，禁止运行期落地后门。"""
    assert _compose_config(profile="pool")["services"][service].get("read_only") is True


@pytest.mark.parametrize(
    "service",
    ["chat-api", "admin-api", "document-api", "document-worker", "user-web", "admin-web", "gateway", *DSH_RUNTIME_HOST_POOL],
)
def test_compose_service_mounts_writable_tmpfs(service: str) -> None:
    tmpfs = list(_compose_config(profile="pool")["services"][service].get("tmpfs") or [])
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
# DSH Runtime Host 加固（补齐 022 US3 的覆盖缺口）
# ---------------------------------------------------------------------------
#
# 池副本的 cap_drop / no-new-privileges / read_only 走
# ``x-dsh-runtime-host-template``（见 HARDENED_SERVICES 与 read_only/tmpfs 参数表），
# 但另有三处容易漏，单独钉住：
#
#   1. 镜像自身的 USER 指令 —— 它用 ``node``（UID 1000）而不是 ``appuser``
#      （10001）。正因为进程直接以非 root 启动、不需要 gosu 的
#      CAP_SETUID/CAP_SETGID，``cap_drop: ALL`` 才成立。
#   2. entrypoint 的降权分支必须是条件式的 —— ``cap_drop: ALL`` 下非 root
#      进程无权 chown，无条件执行会让容器启动即退出。
#   3. HOME 必须落在可写卷内 —— DSH 的 anonymous-user-id 插件把身份写进
#      ``$HOME/.dsh``，只读 rootfs 下 HOME 若仍是 /home/node 就会写失败。
#   4. ``--profile single-host`` 的单副本服务不能绕过加固。

DSH_RUNTIME_HOST_DOCKERFILE = "services/chat-api/dsh/runtime-host/Dockerfile"
DSH_RUNTIME_HOST_ENTRYPOINT = "services/chat-api/dsh/runtime-host/entrypoint.sh"


def test_dsh_runtime_host_image_declares_non_root_user() -> None:
    text = (REPO_ROOT / DSH_RUNTIME_HOST_DOCKERFILE).read_text(encoding="utf-8")
    assert re.search(r"^USER\s+node\b", text, re.M), (
        "dsh-runtime-host 镜像必须以 node 用户运行（USER node）"
    )
    assert not re.search(r"^USER\s+root\b", text, re.M)


def test_dsh_runtime_host_privilege_drop_is_conditional() -> None:
    """chown/gosu 只能在 uid 0 下执行，且非 root 路径要有可跑的命令。"""
    text = (REPO_ROOT / DSH_RUNTIME_HOST_ENTRYPOINT).read_text(encoding="utf-8")
    assert "gosu node" in text, "root 分支应保留 gosu 降权（兼容 docker run -u 0）"
    assert re.search(r'id -u\)"\s*=\s*"0"', text), (
        "chown/gosu 必须被 `id -u` = 0 条件包住，否则非 root 下必然失败"
    )
    assert re.search(r'^\s*exec "\$@"', text, re.M), (
        "条件块之后需要一条无条件 exec，否则非 root 路径无命令可跑"
    )


def test_dsh_runtime_host_home_is_on_a_writable_volume() -> None:
    """read_only 下 $HOME/.dsh 必须落在已挂载的可写卷里。"""
    dockerfile = (REPO_ROOT / DSH_RUNTIME_HOST_DOCKERFILE).read_text(encoding="utf-8")
    match = re.search(r"^ENV\s+HOME=(\S+)", dockerfile, re.M)
    assert match, "Dockerfile 必须显式设置 HOME（compose 锚点的 environment 会被副本覆盖）"
    home = match.group(1)
    assert home.startswith("/data/dsh-runtime/"), (
        f"HOME 应指向 dsh-runtime-data 卷内，实际 {home!r}"
    )
    for service in DSH_RUNTIME_HOST_POOL:
        # `docker compose config --format json` 渲染成长格式（dict），不是
        # 短格式字符串，所以按 target 取而不是按字符串后缀。
        # pool 拓扑的副本仅在 --profile pool 下可见。
        volumes = _compose_config(profile="pool")["services"][service].get("volumes") or []
        targets = [v.get("target") if isinstance(v, dict) else str(v).rsplit(":", 1)[-1] for v in volumes]
        assert "/data/dsh-runtime" in targets, (
            f"{service} 未把数据卷挂到 /data/dsh-runtime：{targets}"
        )


def test_dsh_runtime_host_single_host_profile_is_hardened() -> None:
    """`--profile single-host` 的单副本服务不能绕过加固。"""
    service = _compose_config(profile="single-host")["services"]["dsh-runtime-host"]
    assert service.get("cap_drop") == ["ALL"], service.get("cap_drop")
    assert "no-new-privileges:true" in [str(o) for o in service.get("security_opt") or []]
    assert service.get("read_only") is True
    tmpfs = [str(m) for m in service.get("tmpfs") or []]
    assert any(m.startswith("/tmp") for m in tmpfs), tmpfs
    assert any(m.startswith("/app/host-profile-home") for m in tmpfs), (
        f"host profile 目录必须是 tmpfs，否则 read_only 下无法重建：{tmpfs}"
    )


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
