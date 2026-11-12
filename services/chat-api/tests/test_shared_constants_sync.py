"""058 T014/T015/T020 — 共享常量单一来源一致性校验。

校验：

1. 权威源 ``services/common/shared_constants.py`` 与各服务 vendored 副本逐字节一致
   （P1-14 漂移防护）；
2. ``MODEL_PRICES`` / ``DEFAULT_PRICE`` / ``utc_now`` 三处引用一致；
3. chat-api 与 admin-api 的 ``quota_policy`` 均从 ``app.common.shared_constants``
   引入 ``utc_now``（无本地 naive UTC 重新定义）；
4. ``utc_now()`` 返回 timezone-aware UTC。
"""

from __future__ import annotations

import importlib.util
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


def test_quota_policy_imports_utc_now_from_shared_constants() -> None:
    for svc in ("chat-api", "admin-api"):
        qp = REPO_ROOT / "services" / svc / "app" / "core" / "quota_policy.py"
        src = qp.read_text(encoding="utf-8")
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
