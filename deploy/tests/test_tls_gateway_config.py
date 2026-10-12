"""TLS 网关配置的静态回归守卫。

覆盖两类真实发生过、且**只在启用 TLS 时才暴露**的缺陷（2026-10-12 修复）：

1. ``deploy/nginx/nginx.conf``（TLS 侧配置的「唯一事实来源」）缺少
   ``map $http_upgrade $connection_upgrade`` 块，却仍在使用 ``$connection_upgrade``
   → nginx 启动即 ``[emerg] unknown "connection_upgrade" variable``，
   TLS 根本打不开。两个自称「内容等价」的 TLS 配置因此发生漂移，
   而兼容入口 ``deploy/docker/nginx-https.conf`` 一直是好的，所以只测一个文件
   或只做人工比对都发现不了。

2. 私钥 0600：网关自 022 FR-26 起以非 root(UID 10001) 运行，Linux 上 bind mount
   保留宿主 uid，0600 的私钥容器内读不到 → 启动即
   ``cannot load certificate key ... (13: Permission denied)`` 并 crash-loop。
   ``openssl req -newkey`` 与 ``cp`` 都会产出/保留 0600，所以生成脚本必须显式 chmod。

全部是静态检查，不需要 docker，任何平台可跑::

    python -m pytest deploy/tests/test_tls_gateway_config.py -q
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# TLS 侧的两份网关配置：规范文件 + 兼容入口（自称内容等价）。
TLS_CONFIGS = [
    "deploy/nginx/nginx.conf",
    "deploy/docker/nginx-https.conf",
]

COMPOSE_PATH = "docker-compose.yml"


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _strip_comments(text: str) -> list[str]:
    """去掉注释行与空行，只留可执行配置，用于语义比对。"""
    return [
        line.rstrip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _compose_config() -> dict:
    import json

    out = subprocess.run(
        ["docker", "compose", "-f", COMPOSE_PATH, "config", "--format", "json"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(out)


# ---------------------------------------------------------------------------
# 缺陷 1：$connection_upgrade 必须有 map 定义
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rel", TLS_CONFIGS)
def test_connection_upgrade_is_defined_before_use(rel: str) -> None:
    """用了 ``$connection_upgrade`` 就必须有 ``map`` 定义，否则 nginx 启动失败。"""
    text = _read(rel)
    if "$connection_upgrade" not in text:
        pytest.skip(f"{rel} 未使用 $connection_upgrade")

    assert re.search(
        r"^\s*map\s+\$http_upgrade\s+\$connection_upgrade\s*\{", text, re.M
    ), (
        f"{rel}: 使用了 $connection_upgrade 但没有定义 "
        "`map $http_upgrade $connection_upgrade { ... }`，"
        'nginx 会以 `[emerg] unknown "connection_upgrade" variable` 启动失败'
    )


def test_tls_configs_are_semantically_equivalent() -> None:
    """两份 TLS 配置必须语义等价（注释/空行差异除外）。

    ``deploy/docker/nginx-https.conf`` 的注释自称与 ``deploy/nginx/nginx.conf``
    「内容等价」；漂移正是上面那个缺陷的成因，这里把该承诺钉住。
    """
    left, right = (_strip_comments(_read(rel)) for rel in TLS_CONFIGS)
    assert left == right, (
        f"{TLS_CONFIGS[0]} 与 {TLS_CONFIGS[1]} 的配置内容已漂移；"
        "两份文件必须保持等价（差异应只存在于注释）"
    )


# ---------------------------------------------------------------------------
# 缺陷 2：私钥必须能被容器内 uid 10001 读到
# ---------------------------------------------------------------------------


def test_setup_certs_script_normalises_key_mode() -> None:
    """生成脚本必须显式 chmod：openssl 产出的 0600 与 cp 保留模式都会让容器读不到。"""
    text = _read("deploy/tls/setup-certs.sh")
    assert re.search(
        r"^chmod\s+0644\s+\"\$TLS_DIR/fullchain\.pem\"\s+\"\$TLS_DIR/privkey\.pem\"",
        text,
        re.M,
    ), (
        "deploy/tls/setup-certs.sh 未把 fullchain.pem/privkey.pem chmod 到 0644；"
        "cp 会保留 openssl 私钥的 0600，容器内 uid 10001 将读不到"
    )
    # 自检：必须验证私钥存在「非 owner 可读位」，否则等于没检查
    assert "-perm -004" in text, (
        "deploy/tls/setup-certs.sh 缺少 o+r 自检（find -perm -004）"
    )


def test_readme_documents_key_mode_requirement() -> None:
    """README 必须写明私钥模式要求与原因，否则操作者只会看到 nginx emerg。"""
    text = _read("deploy/tls/README.md")
    assert "0644" in text, "deploy/tls/README.md 未说明私钥需要 0644"
    assert "10001" in text, "deploy/tls/README.md 未说明容器以 UID 10001 运行"
    assert "Permission denied" in text, (
        "deploy/tls/README.md 未收录 Permission denied 的排查项"
    )


@pytest.mark.parametrize("rel", TLS_CONFIGS)
def test_tls_configs_warn_about_key_mode(rel: str) -> None:
    """证书指令旁必须留下模式提醒：这里是操作者排查 emerg 的第一现场。"""
    text = _read(rel)
    assert re.search(
        r"^    ssl_certificate\s+/etc/nginx/certs/fullchain\.pem;", text, re.M
    ), f"{rel}: ssl_certificate 未指向 compose 挂载的 /etc/nginx/certs/fullchain.pem"
    assert re.search(
        r"^    ssl_certificate_key\s+/etc/nginx/certs/privkey\.pem;", text, re.M
    ), f"{rel}: ssl_certificate_key 未指向 compose 挂载的 /etc/nginx/certs/privkey.pem"
    assert "10001" in text and "0644" in text, (
        f"{rel}: ssl_certificate_key 附近缺少「容器内 UID 10001 需可读 / chmod 0644」的说明"
    )


# ---------------------------------------------------------------------------
# compose 侧的契约：证书目录与配置文件的挂载方式
# ---------------------------------------------------------------------------


def test_compose_mounts_tls_certs_read_only_into_gateway() -> None:
    """gateway 必须把证书目录与配置文件都只读挂进去，且路径可被 env 覆盖。

    注意 ``docker compose config`` 会把 ``${VAR}`` 解析成实际路径，所以结构化断言
    看的是挂载目标/只读标志，env 参数化另行在原始 YAML 文本上校验。
    """
    gateway = _compose_config()["services"]["gateway"]
    mounts = {
        str(v.get("target")): v
        for v in (gateway.get("volumes") or [])
        if isinstance(v, dict)
    }

    assert "/etc/nginx/certs" in mounts, (
        f"gateway 未挂载证书目录 /etc/nginx/certs；实际 {sorted(mounts)}"
    )
    assert mounts["/etc/nginx/certs"].get("read_only") is True, (
        "/etc/nginx/certs 必须只读挂载（私钥不应可写）"
    )
    assert "/etc/nginx/conf.d/default.conf" in mounts, (
        f"gateway 未挂载 TLS 网关配置；实际 {sorted(mounts)}"
    )
    assert mounts["/etc/nginx/conf.d/default.conf"].get("read_only") is True, (
        "/etc/nginx/conf.d/default.conf 必须只读挂载"
    )

    # 路径必须由 env 参数化，否则切换证书目录/配置就只能改仓库文件。
    raw = _read(COMPOSE_PATH)
    assert "MOGO_TLS_CERTS_DIR" in raw, "compose 未用 MOGO_TLS_CERTS_DIR 参数化证书目录"
    assert "MOGO_NGINX_CONF" in raw, "compose 未用 MOGO_NGINX_CONF 参数化网关配置"


def test_compose_exposes_https_port() -> None:
    """443 必须已暴露：否则切了 TLS 配置也访问不到。"""
    gateway = _compose_config()["services"]["gateway"]
    ports = [str(p) for p in (gateway.get("ports") or [])]
    assert any("443" in p for p in ports), f"gateway 未暴露 443；实际 {ports}"
