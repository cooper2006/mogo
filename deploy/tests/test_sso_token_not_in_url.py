"""T030/T031（022 FR-14 / QF-634）：SSO 令牌不得出现在 URL 查询串。

审计发现（QF-634）：chat-api 签发的 SSO 令牌原先被前端拼进
``?sso_token=`` 再作为跳转目标打开，导致令牌进入浏览器地址栏、浏览历史、
书签与分享链接，任何能读到 URL 的地方都能拿到有效的管理端凭证。

改造后：
- user-web 只生成管理台基础 URL，令牌通过 ``window.open`` 的 state 参数传递；
- admin-web 从 ``window.history.state`` 读取令牌，POST 到
  ``/api/auth/sso/exchange`` 换正式 access token（一次性幂等）；
- 服务端 SSO 令牌 TTL 收敛到 60 秒。

本测试用静态扫描兜底：仓库里任何前端代码再次把 SSO 令牌拼进 URL 查询串，
或后端再次把 SSO 令牌放进响应体里让前端走 URL，测试都会失败。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

FRONTEND_SOURCES = [
    REPO_ROOT / "apps/user-web/src",
    REPO_ROOT / "apps/admin-web/src",
]

BACKEND_SOURCES = [
    REPO_ROOT / "services/chat-api/app",
    REPO_ROOT / "services/admin-api/app",
]

# 前端把 SSO 令牌拼进 URL 的写法（查询串 / hash）。
_URL_TOKEN_PATTERNS = [
    re.compile(r"searchParams\.set\s*\(\s*['\"]sso_?token['\"]", re.I),
    re.compile(r"['\"`]sso_?token\s*=", re.I),       # ?sso_token= 字面拼接
    re.compile(r"#sso_?token", re.I),
]


def _files_under(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    if not root.is_dir():
        return []
    return [
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix in suffixes and "__pycache__" not in p.parts
    ]


# ---------------------------------------------------------------------------
# 前端：不得把 SSO 令牌拼进 URL
# ---------------------------------------------------------------------------


def test_frontend_does_not_put_sso_token_in_url() -> None:
    """前端任何源码不得把 sso_token 写进 URL 查询串或 hash。"""
    offenders: list[str] = []
    for root in FRONTEND_SOURCES:
        for path in _files_under(root, (".ts", ".tsx", ".vue", ".js")):
            text = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                # 允许出现在"说明历史问题"的注释里
                if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("#"):
                    continue
                for pattern in _URL_TOKEN_PATTERNS:
                    if pattern.search(line):
                        offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "以下前端代码把 SSO 令牌拼进了 URL，违反 022 FR-14：\n" + "\n".join(offenders)
    )


def test_user_web_passes_sso_token_via_window_state() -> None:
    """user-web 必须用 window.open 的 state 参数传递令牌，而不是 URL。"""
    src = REPO_ROOT / "apps/user-web/src/utils/adminUrl.ts"
    assert src.exists()
    text = src.read_text(encoding="utf-8")
    assert "state=" in text, "缺少 state= 传递约定"
    assert "encodeURIComponent" in text, "state 参数必须编码"
    # buildAdminSsoUrl 不再接收令牌参数
    assert re.search(r"export function buildAdminSsoUrl\(\)", text), (
        "buildAdminSsoUrl 仍接收 ssoToken 参数"
    )


def test_admin_web_reads_token_from_history_state() -> None:
    """admin-web 必须从 window.history.state 读令牌，不从 location.search 读。"""
    src = REPO_ROOT / "apps/admin-web/src/stores/auth.ts"
    assert src.exists()
    text = src.read_text(encoding="utf-8")
    assert "window.history.state" in text, "未从 window.history.state 读取 SSO 令牌"
    assert "params.get('sso_token')" not in text and 'params.get("sso_token")' not in text, (
        "仍在从 URL 查询串读取 sso_token"
    )
    assert "exchangeSsoToken" in text, "未调用 SSO 换票 API"


def test_admin_web_exchanges_token_via_post() -> None:
    """换票必须走 POST，令牌在请求体里，不在 URL 里。"""
    src = REPO_ROOT / "apps/admin-web/src/api/auth.ts"
    assert src.exists()
    text = src.read_text(encoding="utf-8")
    assert "post<", "缺少 POST 调用" in text or "post<" in text
    # 2026-10-27 b6055c89 将 214 处旧路径统一迁到 /api/v1（消除每次请求的 301
    # 往返）；SSO 换票路径随之变为 /api/v1/auth/sso/exchange，本断言同步当前路径。
    assert "/api/v1/auth/sso/exchange" in text
    assert "sso_token: ssoToken" in text, "请求体必须携带 sso_token 字段"


# ---------------------------------------------------------------------------
# 后端：SSO 令牌一次性幂等 + 短 TTL
# ---------------------------------------------------------------------------


def test_backend_sso_token_ttl_is_short() -> None:
    """SSO 票据 TTL 必须收敛到分钟级（<= 300 秒），不能是小时级。"""
    src = REPO_ROOT / "services/chat-api/app/api/endpoints/auth.py"
    text = src.read_text(encoding="utf-8")

    # 解析模块级常量定义，例如 ADMIN_SSO_TOKEN_TTL_SECONDS = 60
    constants = {name: int(value) for name, value in re.findall(
        r"^([A-Z][A-Z_0-9]+)\s*=\s*(\d+)\s*$", text, re.M
    )}
    assert constants, "auth.py 中未找到任何大写常量定义"

    sig = re.search(r"def _create_admin_token\(([^)]*)\)", text, re.S)
    assert sig is not None, "未找到 _create_admin_token 定义"
    default = re.search(
        r"expires_in_seconds\s*:\s*int\s*=\s*([0-9A-Za-z_\s*]+)", sig.group(1)
    )
    assert default is not None, "_create_admin_token 缺少 expires_in_seconds 默认值"

    ttl = int(eval(default.group(1).strip(), {}, constants))
    assert ttl <= 300, (
        f"SSO 票据 TTL 为 {ttl} 秒，超过 300 秒上限；"
        "票据是一次性换票凭证，窗口过长等于长期可用的管理端凭证"
    )



def test_admin_api_exchange_marks_token_consumed() -> None:
    """admin-api 换票必须标记票据已消费，保证 accept-once 幂等。"""
    src = REPO_ROOT / "services/admin-api/app/api/routes/auth.py"
    text = src.read_text(encoding="utf-8")
    assert "exchanged" in text, "缺少 exchanged 消费标记"
    assert re.search(r'upsert\s*=\s*True', text), (
        "消费标记必须 upsert，否则会话文档缺失时重放检查会失效"
    )
    assert "compare_digest" in text, "签名校验必须用 hmac.compare_digest（常数时间比较）"
