"""047-quota-discoverability T022: 两侧 get_quota_summary JSON 逐字段比对。

不 mock 数据库——直接提取两侧返回 dict 的 key 集合做静态对比，
加上对已知字段（totalPoints / remainingPoints / quotaSource 等）的语义比对。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

ADMIN_QUOTA = ROOT / "services" / "admin-api" / "app" / "core" / "quota_policy.py"
CHAT_QUOTA = ROOT / "services" / "chat-api" / "app" / "core" / "quota_policy.py"

# 期望两侧共有的核心字段（FR 要求语义一致）
EXPECTED_KEYS = {
    "tenantId", "orgName", "spaceType", "quotaSource", "period",
    "totalPoints", "usedPoints", "remainingPoints",
}


def _extract_return_keys(filepath: Path) -> set[str]:
    """Extract string keys from return dicts in get_quota_summary."""
    source = filepath.read_text()
    tree = ast.parse(source)
    keys: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_quota_summary":
            for child in ast.walk(node):
                if isinstance(child, ast.Return) and isinstance(child.value, ast.Dict):
                    for key in child.value.keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            keys.add(key.value)
    return keys


def _extract_string_values(filepath: Path, pattern: str) -> list[str]:
    """Extract string values matching a pattern from source."""
    source = filepath.read_text()
    return re.findall(pattern, source)


class TestQuotaSummaryKeyConsistency:
    """Compare get_quota_summary return keys between admin-api and chat-api."""

    def test_admin_api_has_expected_keys(self):
        keys = _extract_return_keys(ADMIN_QUOTA)
        missing = EXPECTED_KEYS - keys
        assert not missing, f"admin-api missing keys: {missing}"

    def test_chat_api_has_expected_keys(self):
        keys = _extract_return_keys(CHAT_QUOTA)
        missing = EXPECTED_KEYS - keys
        assert not missing, f"chat-api missing keys: {missing}"

    def test_both_sides_share_common_keys(self):
        admin_keys = _extract_return_keys(ADMIN_QUOTA)
        chat_keys = _extract_return_keys(CHAT_QUOTA)
        common = admin_keys & chat_keys
        missing_common = EXPECTED_KEYS - common
        assert not missing_common, (
            f"Keys in EXPECTED_KEYS but not shared: {missing_common}\n"
            f"  admin-api only: {sorted(admin_keys - chat_keys)}\n"
            f"  chat-api only: {sorted(chat_keys - admin_keys)}"
        )

    def test_report_key_differences(self):
        """T023: 记录差异清单（不作为硬断言，只打印）。"""
        admin_keys = _extract_return_keys(ADMIN_QUOTA)
        chat_keys = _extract_return_keys(CHAT_QUOTA)
        admin_only = sorted(admin_keys - chat_keys)
        chat_only = sorted(chat_keys - admin_keys)
        if admin_only or chat_only:
            print(f"\nadmin-api only keys: {admin_only}")
            print(f"chat-api only keys: {chat_only}")

    def test_quota_source_values_consistent(self):
        """Both sides should use the same quotaSource values."""
        for filepath, label in [(ADMIN_QUOTA, "admin-api"), (CHAT_QUOTA, "chat-api")]:
            values = _extract_string_values(filepath, r'"quotaSource":\s*"([^"]+)"')
            assert len(values) > 0, f"{label}: no quotaSource values found"
            for v in values:
                assert v in (
                    "registration_gift", "enterprise_allocation",
                    "unlimited", "personal",
                ), f"{label}: unexpected quotaSource '{v}'"

    def test_points_unlimited_default_consistent(self):
        """Both sides should use `points_unlimited, True` (default unlimited)."""
        for filepath, label in [(ADMIN_QUOTA, "admin-api"), (CHAT_QUOTA, "chat-api")]:
            source = filepath.read_text()
            assert re.search(r'points_unlimited["\s,]+True', source), (
                f"{label}: points_unlimited should default to True"
            )

    def test_denial_message_consistent(self):
        """Both sides use 部门额度已用尽 (not 团队)."""
        for filepath, label in [(ADMIN_QUOTA, "admin-api"), (CHAT_QUOTA, "chat-api")]:
            source = filepath.read_text()
            assert "部门额度已用尽" in source, f"{label}: should use 部门额度已用尽"
            assert "团队额度已用尽" not in source, f"{label}: should NOT use 团队额度已用尽"
