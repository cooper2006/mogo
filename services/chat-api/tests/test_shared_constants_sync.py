"""058 T014/T015/T020 — 共享常量单一来源一致性校验。

校验：

1. 权威源 ``services/common/shared_constants.py`` 与各服务 vendored 副本逐字节一致
   （P1-14 漂移防护）；
2. ``MODEL_PRICES`` / ``DEFAULT_PRICE`` / ``utc_now`` 三处引用一致；
3. chat-api 与 admin-api 的 ``quota_policy`` **运行时**的 ``utc_now`` 确实指向
   ``app.common.shared_constants.utc_now``，且返回 timezone-aware UTC。

关于 3：曾有一版只在源码里检查 ``from ... import utc_now`` 字符串，结果两个
``quota_policy.py`` 都保留了本地 ``def utc_now()``（chat-api 返回 naive UTC），
Python 的后定义会覆盖 import，字符串断言因此假阳性通过。故这里改为在各自服务
进程内做**对象身份断言**（``is``），任何本地重新定义都会立刻失败。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL = REPO_ROOT / "services" / "common" / "shared_constants.py"
CHAT_COPY = REPO_ROOT / "services" / "chat-api" / "app" / "common" / "shared_constants.py"
ADMIN_COPY = REPO_ROOT / "services" / "admin-api" / "app" / "common" / "shared_constants.py"


def _norm(text: str) -> str:
    return text.rstrip("\n")


def test_vendored_shared_constants_identical_to_canonical() -> None:
    canonical = _norm(CANONICAL.read_text(encoding="utf-8"))
    for copy in (CHAT_COPY, ADMIN_COPY):
        assert copy.is_file(), f"缺失副本: {copy}"
        assert _norm(copy.read_text(encoding="utf-8")) == canonical, (
            f"{copy.name} 与权威源不一致（P1-14 漂移）"
        )


_RUNTIME_CHECK = """
from app.core import quota_policy as q
from app.common import shared_constants as s

assert q.utc_now is s.utc_now, (
    "quota_policy.utc_now 未指向权威源（很可能仍有本地 def utc_now 覆盖 import）"
)
assert q.utc_now.__module__ == "app.common.shared_constants", q.utc_now.__module__
value = q.utc_now()
assert value.tzinfo is not None, "utc_now() 返回 naive datetime"
assert value.utcoffset().total_seconds() == 0, "utc_now() 不是 UTC"
print("OK")
"""


def _service_root(svc: str) -> Path:
    return REPO_ROOT / "services" / svc


def test_quota_policy_utc_now_is_canonical_at_runtime() -> None:
    """两个服务在各自进程内验证 utc_now 的对象身份与时区，杜绝「假导入」。"""
    for svc in ("chat-api", "admin-api"):
        root = _service_root(svc)
        result = subprocess.run(
            [sys.executable, "-c", _RUNTIME_CHECK],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"{svc} quota_policy.utc_now 运行时校验失败:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "OK" in result.stdout


def test_quota_policy_has_no_local_utc_now_definition() -> None:
    """静态兜底：源码中不得再出现本地 def utc_now（含下划线变体）。"""
    for svc in ("chat-api", "admin-api"):
        src = (_service_root(svc) / "app" / "core" / "quota_policy.py").read_text(
            encoding="utf-8"
        )
        assert "def utc_now(" not in src, f"{svc} quota_policy 重新定义了本地 utc_now"
        assert "def _utcnow(" not in src, f"{svc} quota_policy 重新定义了本地 _utcnow"
        assert "from app.common.shared_constants import utc_now" in src, (
            f"{svc} quota_policy 未从 shared_constants 引入 utc_now"
        )


def test_shared_constants_values_consistent() -> None:
    spec = importlib.util.spec_from_file_location("shared_constants_canonical", CANONICAL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert isinstance(mod.MODEL_PRICES, dict) and mod.MODEL_PRICES
    assert mod.DEFAULT_PRICE == (10.0, 30.0)
    dt = mod.utc_now()
    assert dt.tzinfo is not None and dt.utcoffset() == timezone.utc.utcoffset(None)
