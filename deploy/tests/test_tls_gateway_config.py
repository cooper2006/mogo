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

import os
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


# ---------------------------------------------------------------------------
# 部署脚本侧的契约：启用 TLS 后 ./mogo up 的就绪门不能失效
# ---------------------------------------------------------------------------


def test_readiness_probe_tolerates_tls_redirect() -> None:
    """启用 TLS 后 /admin-api/ 会 301，就绪探针必须能跟过去。

    否则 ``./mogo up`` 会在健康的部署上白等 90×2s 后报
    "Services did not become ready in time" —— 这正是 2026-10-12 切 TLS 时踩到的。
    """
    text = _read("mogo")
    match = re.search(r"^status_is_ready\(\) \{.*?^\}", text, re.M | re.S)
    assert match, "mogo 里找不到 status_is_ready"
    body = match.group(0)

    assert "-fsSLk" in body, (
        "status_is_ready 未跟随 HTTP→HTTPS 跳转（-L）或未跳过自签名校验（-k），"
        "启用 TLS 后 ./mogo up 会一直等不到就绪"
    )
    assert "--no-check-certificate" in body, (
        "status_is_ready 的 wget 分支同样需要跳过自签名校验"
    )
    # 宿主端口可能被别的进程占用（实测 443 被第三方代理占用），兜底走容器内直连。
    assert "admin-api:8100" in body, (
        "status_is_ready 缺少容器内直连 admin-api 的兜底路径"
    )
    # 容器内直连的路径**不能**带网关前缀 /admin-api —— 该前缀是 nginx 路由加上的，
    # admin-api 自身只认 /api/setup/status。（这个坑已实际踩过一次。）
    assert re.search(r'direct_path="/api/setup/status"', body), (
        "容器内兜底路径应是不带 /admin-api 前缀的 /api/setup/status"
    )


# ── ./mogo 的证书保障（2026-10-13）───────────────────────────────────────
#
# 网关自 2026-10-13 起默认加载 TLS 侧配置（compose 里
# `${MOGO_NGINX_CONF:-./deploy/nginx/nginx.conf}`），而证书刻意不入库
# （`deploy/tls/.gitignore`）。全新克隆没有证书时，网关容器是 read_only 且以
# 非 root 运行，nginx 无法在运行时自建，只会
# `cannot load certificate key` 反复 crash-loop，最终表现为
# "services did not become ready in time" —— 完全看不出是缺证书。
#
# `mogo_ensure_tls_certs()` 因此负责：解析同 compose 一致的两个变量 → 缺证书时
# 用 openssl 生成自签名对 → 已存在则不动 → 指向 HTTP 侧配置则直接跳过。

_MOGO_PATH = "mogo"

# 真实执行 mogo_ensure_tls_certs 所需的桩（不碰 docker）。
_ENSURE_HARNESS = """set -Eeuo pipefail
source "$ROOT_DIR/deploy/cli/i18n.sh"
mogo_detect_locale
dotenv_value() { sed -n "s/^[[:space:]]*$1=//p" "$FAKE_ENV" 2>/dev/null | tail -n1 || true; }
mogo_compose() {
  echo "mogo_compose $*" >> "$MOCK_LOG"
  if [ "$1" = ps ] && [ "$FAKE_CONTAINER" = 1 ]; then echo fake-container-id; fi
  return 0
}
if [ "$NO_OPENSSL" = 1 ]; then
  command() {
    if [ "${1:-}" = "-v" ] && [ "${2:-}" = "openssl" ]; then return 1; fi
    builtin command "$@"
  }
fi
# mogo_ensure_tls_certs 委托 mogo_tls_is_enabled 做开关判定，两个都要抽出。
eval "$(sed -n '/^mogo_tls_is_enabled()/,/^}/p' "$ROOT_DIR/mogo")"
eval "$(sed -n '/^mogo_ensure_tls_certs()/,/^}/p' "$ROOT_DIR/mogo")"
mogo_ensure_tls_certs
"""


def _run_ensure_tls(
    tmp_path: Path,
    *,
    nginx_conf: str | None = None,
    certs_dir: str | None = None,
    no_openssl: bool = False,
    fake_container: bool = False,
    no_tls_for_dotenv_test: bool = False,
):
    """在隔离目录里真实执行 mogo 的 mogo_ensure_tls_certs（配桩，不碰 docker）。"""
    (tmp_path / ".env").write_text("", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        ROOT_DIR=str(REPO_ROOT),
        FAKE_ENV=str(tmp_path / ".env"),
        MOCK_LOG=str(tmp_path / "mock.log"),
        NO_OPENSSL="1" if no_openssl else "0",
        FAKE_CONTAINER="1" if fake_container else "0",
    )
    # 显式清空：测试不应受开发者本机 .env 影响（dotenv_value 读的是 FAKE_ENV）。
    env.pop("MOGO_NGINX_CONF", None)
    env.pop("MOGO_TLS_CERTS_DIR", None)
    # b3bf111 之后 MOGO_TLS 默认关闭，但此模块的证书保障测试需要 TLS 启用
    # 才具有验证意义；显式传 nginx_conf="deploy/docker/nginx.conf" 的测试
    # 不受影响，因为该路径会直接走 HTTP 分支跳过证书生成。
    # 使用 env[...] = ... 而非 setdefault：开发者本机 .env 可能通过
    # subprocess 的 inherit 行为把 MOGO_TLS=0 带进测试进程，setdefault
    # 在这种情况下不会生效，导致所有证书生成测试静默跳过。
    # 特殊情况下（如测试 .env 读取），允许覆盖此行为。
    if not no_tls_for_dotenv_test:
        env["MOGO_TLS"] = "1"
    if nginx_conf is not None:
        env["MOGO_NGINX_CONF"] = nginx_conf
    if certs_dir is not None:
        env["MOGO_TLS_CERTS_DIR"] = str(certs_dir)
    script = tmp_path / "harness.sh"
    script.write_text(_ENSURE_HARNESS, encoding="utf-8")
    return subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, env=env, timeout=120
    )


def test_mogo_defines_and_wires_tls_cert_guard() -> None:
    """mogo 必须定义证书保障函数，并在三个会启动网关的命令里调用。"""
    text = _read(_MOGO_PATH)
    assert "mogo_ensure_tls_certs() {" in text, "mogo 缺少 mogo_ensure_tls_certs 定义"

    for command in ("command_up()", "command_update()"):
        match = re.search(rf"{re.escape(command)} \{{.*?^\}}", text, re.M | re.S)
        assert match, f"mogo 里找不到 {command}"
        assert "mogo_ensure_tls_certs" in match.group(0), (
            f"{command} 未调用 mogo_ensure_tls_certs，缺证书仍会 crash-loop"
        )

    # restart 分支直接写在 case 里，没有独立函数。
    restart = re.search(r"^  restart\).*?^    ;;", text, re.M | re.S)
    assert restart, "mogo 的 restart 分支不存在"
    assert "mogo_ensure_tls_certs" in restart.group(0), "restart 分支未调用 mogo_ensure_tls_certs"


def test_tls_cert_guard_generates_self_signed_pair(tmp_path: Path) -> None:
    """缺证书时应生成自签名对，且私钥为 0644（容器内 UID 10001 要能读）。"""
    certs = tmp_path / "tls"
    result = _run_ensure_tls(tmp_path, certs_dir=str(certs))

    assert result.returncode == 0, f"应成功生成证书：{result.stderr}"
    for name in ("fullchain.pem", "privkey.pem"):
        assert (certs / name).is_file(), f"未生成 {name}"
    mode = (certs / "privkey.pem").stat().st_mode & 0o777
    assert mode == 0o644, f"私钥模式是 {mode:o}，容器内 UID 10001 读不到会 crash-loop"
    assert "fullchain.pem" in result.stdout or "Generated" in result.stdout


def test_tls_cert_guard_never_overwrites_existing_pair(tmp_path: Path) -> None:
    """已存在的证书对必须原样保留（不覆盖用户放进去的 CA 证书）。"""
    certs = tmp_path / "tls"
    certs.mkdir()
    chain = certs / "fullchain.pem"
    key = certs / "privkey.pem"
    chain.write_text("EXISTING-CHAIN\n", encoding="utf-8")
    key.write_text("EXISTING-KEY\n", encoding="utf-8")

    result = _run_ensure_tls(tmp_path, certs_dir=str(certs))

    assert result.returncode == 0, result.stderr
    assert chain.read_text(encoding="utf-8") == "EXISTING-CHAIN\n", "已有证书链被覆盖"
    assert key.read_text(encoding="utf-8") == "EXISTING-KEY\n", "已有私钥被覆盖"


def test_tls_cert_guard_skips_http_side_config(tmp_path: Path) -> None:
    """指向 HTTP 侧配置时不得生成任何证书（用户明确退回 HTTP）。"""
    certs = tmp_path / "tls"
    result = _run_ensure_tls(
        tmp_path, nginx_conf="deploy/docker/nginx.conf", certs_dir=str(certs)
    )

    assert result.returncode == 0, result.stderr
    assert not certs.exists(), "HTTP 侧配置不应触发证书生成"


def test_tls_cert_guard_fails_loudly_without_openssl(tmp_path: Path) -> None:
    """没有 openssl 时必须快速失败并给出修复命令，而不是让 nginx 反复重启。"""
    certs = tmp_path / "tls"
    result = _run_ensure_tls(tmp_path, certs_dir=str(certs), no_openssl=True)

    assert result.returncode != 0, "无 openssl 时应失败"
    assert not certs.exists(), "无 openssl 时不应创建目录/文件（检查应在 mkdir 之前）"
    message = result.stdout + result.stderr
    assert "fullchain.pem" in message, "错误信息应告诉用户要放什么文件"
    assert "0644" in message, "错误信息应说明私钥权限要求"


def test_tls_cert_guard_restarts_running_gateway(tmp_path: Path) -> None:
    """生成证书后必须重启已在运行的网关：nginx 只在启动时读私钥。"""
    certs = tmp_path / "tls"
    result = _run_ensure_tls(tmp_path, certs_dir=str(certs), fake_container=True)

    assert result.returncode == 0, result.stderr
    mock = (tmp_path / "mock.log").read_text(encoding="utf-8")
    assert "mogo_compose ps -q gateway" in mock, "未探测 gateway 容器是否在运行"
    assert "mogo_compose restart gateway" in mock, (
        "生成证书后未重启网关；compose up -d 不会重建 spec 未变的容器，"
        "nginx 仍读不到新证书"
    )


def test_tls_cert_guard_reads_switch_from_dotenv(tmp_path: Path) -> None:
    """通过 .env 设置 MOGO_NGINX_CONF 指向 HTTP 侧配置时，不生成证书。"""
    (tmp_path / ".env").write_text(
        "MOGO_NGINX_CONF=./deploy/docker/nginx.conf\n", encoding="utf-8"
    )
    certs = tmp_path / "from-env"
    # no_tls_for_dotenv_test=True 允许测试控制 MOGO_TLS 状态，验证 .env 读取逻辑
    result = _run_ensure_tls(tmp_path, certs_dir=str(certs), no_tls_for_dotenv_test=True)

    assert result.returncode == 0, result.stderr
    assert not certs.exists(), ".env 指定 HTTP 侧配置时不应生成证书"


def test_i18n_covers_tls_cert_guard_messages() -> None:
    """两种语言都必须有新消息，否则默认 locale 下会打印裸键名。"""
    text = _read("deploy/cli/i18n.sh")
    for key in (
        "tls_generating_certs",
        "tls_certs_generated",
        "tls_cert_generated_without_san",
        "tls_certs_missing_no_openssl",
        "tls_cert_generation_failed",
        "tls_gateway_restart_failed",
    ):
        for locale in ("zh", "en"):
            assert f"{locale}:{key})" in text, f"i18n 缺少 {locale}:{key}"
