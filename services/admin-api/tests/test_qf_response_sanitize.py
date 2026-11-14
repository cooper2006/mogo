"""QF-660 / QF-662 集成测试 — 响应权限裁剪 + 非生产数据脱敏。

验证：
- QF-660：接口响应按调用者权限裁剪敏感字段
- QF-662：非生产环境使用脱敏或合成数据
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.security.data_sanitizer import (
    generate_synthetic_account,
    generate_synthetic_accounts,
    is_non_production,
    sanitize_document,
    sanitize_value,
    seed_synthetic_data,
)
from app.security.response_policy import (
    L0_FIELDS,
    L1_FIELDS,
    L2_FIELDS,
    L3_FIELDS,
    allowed_fields_for,
    format_account_by_role,
)

# ── 测试数据 ──────────────────────────────────────────────────────────

SAMPLE_DOC = {
    "_id": "acct-001",
    "tenant_id": "tenant-abc",
    "username": "zhangsan",
    "display_name": "张三",
    "email": "zhangsan@example.com",
    "phone": "13812345678",
    "group_code": "eng",
    "role_name": "组织管理员",
    "status": "active",
    "is_protected": True,
    "password_hash": "hashed_value_123",
    "password_salt": "salt_456",
    "mfa_secret_encrypted": "encrypted_secret_789",
    "updated_at": None,
}

GROUP_NAME_MAP = {"eng": "工程组"}


# ══════════════════════════════════════════════════════════════════════
# QF-660：响应权限裁剪
# ══════════════════════════════════════════════════════════════════════


class TestFieldLevels:
    """字段分级测试。"""

    def test_L0_contains_only_base_fields(self) -> None:
        assert L0_FIELDS == frozenset({"id", "username", "displayName"})

    def test_L1_includes_L0(self) -> None:
        assert L0_FIELDS.issubset(L1_FIELDS)

    def test_L2_includes_L1(self) -> None:
        assert L1_FIELDS.issubset(L2_FIELDS)
        assert "email" in L2_FIELDS
        assert "phone" in L2_FIELDS
        assert "status" in L2_FIELDS

    def test_L3_includes_L2_and_security(self) -> None:
        assert L2_FIELDS.issubset(L3_FIELDS)
        assert "isProtected" in L3_FIELDS
        assert "password_hash" in L3_FIELDS
        assert "mfa_secret_encrypted" in L3_FIELDS

    def test_field_monotonicity(self) -> None:
        """字段集必须单调递增（高权限 = 低权限 + 更多字段）。"""
        levels = [L0_FIELDS, L1_FIELDS, L2_FIELDS, L3_FIELDS]
        for i in range(len(levels) - 1):
            assert levels[i].issubset(levels[i + 1]), (
                f"Level {i} should be subset of level {i + 1}"
            )


class TestAllowedFieldsFor:
    """角色 → 字段集映射测试。"""

    def test_platform_admin_gets_L3(self) -> None:
        caller = {"role_name": "平台管理员"}
        assert allowed_fields_for(caller) == L3_FIELDS

    def test_platform_admin_english_key(self) -> None:
        caller = {"role_name": "platform_admin"}
        assert allowed_fields_for(caller) == L3_FIELDS

    def test_tenant_admin_gets_L2(self) -> None:
        caller = {"role_name": "租户管理员"}
        assert allowed_fields_for(caller) == L2_FIELDS

    def test_org_admin_gets_L2(self) -> None:
        caller = {"role_name": "组织管理员"}
        assert allowed_fields_for(caller) == L2_FIELDS

    def test_org_member_gets_L1(self) -> None:
        caller = {"role_name": "组织成员"}
        assert allowed_fields_for(caller) == L1_FIELDS

    def test_normal_user_gets_L0(self) -> None:
        caller = {"role_name": "普通用户"}
        assert allowed_fields_for(caller) == L0_FIELDS

    def test_viewer_gets_L0(self) -> None:
        caller = {"role_name": "viewer"}
        assert allowed_fields_for(caller) == L0_FIELDS

    def test_unknown_role_gets_L0_fallback(self) -> None:
        """未知角色回退到最小字段集（fail-closed）。"""
        caller = {"role_name": "完全未知的角色"}
        assert allowed_fields_for(caller) == L0_FIELDS

    def test_none_caller_gets_L0(self) -> None:
        assert allowed_fields_for(None) == L0_FIELDS

    def test_empty_caller_gets_L0(self) -> None:
        assert allowed_fields_for({}) == L0_FIELDS

    def test_role_fallback_to_role_key(self) -> None:
        """role_name 缺失时回退到 role 字段。"""
        caller = {"role": "平台管理员"}
        assert allowed_fields_for(caller) == L3_FIELDS

    def test_role_name_takes_precedence(self) -> None:
        """role_name 优先于 role。"""
        caller = {"role_name": "普通用户", "role": "平台管理员"}
        assert allowed_fields_for(caller) == L0_FIELDS


class TestFormatAccountByRole:
    """format_account_by_role 函数测试。"""

    def test_platform_admin_sees_all_fields(self) -> None:
        caller = {"role_name": "平台管理员"}
        result = format_account_by_role(SAMPLE_DOC, caller, GROUP_NAME_MAP)
        # 应包含敏感字段
        assert "email" in result
        assert "phone" in result
        assert "isProtected" in result
        assert "status" in result

    def test_org_admin_cannot_see_security_fields(self) -> None:
        """组织管理员看不到 L3 字段（isProtected）。"""
        caller = {"role_name": "组织管理员"}
        result = format_account_by_role(SAMPLE_DOC, caller, GROUP_NAME_MAP)
        assert "isProtected" not in result
        assert "password_hash" not in result
        assert "mfa_secret_encrypted" not in result

    def test_org_admin_can_see_contact_fields(self) -> None:
        """组织管理员可以看到 L2 字段（email, phone）。"""
        caller = {"role_name": "组织管理员"}
        result = format_account_by_role(SAMPLE_DOC, caller, GROUP_NAME_MAP)
        assert "email" in result
        assert "phone" in result
        assert result["email"] == "zhangsan@example.com"
        assert result["phone"] == "13812345678"

    def test_org_member_cannot_see_contact_fields(self) -> None:
        """组织成员看不到 L2 字段（email, phone）。"""
        caller = {"role_name": "组织成员"}
        result = format_account_by_role(SAMPLE_DOC, caller, GROUP_NAME_MAP)
        assert "email" not in result
        assert "phone" not in result
        assert "status" not in result
        assert "isProtected" not in result

    def test_org_member_can_see_basic_fields(self) -> None:
        """组织成员可以看到 L1 字段。"""
        caller = {"role_name": "组织成员"}
        result = format_account_by_role(SAMPLE_DOC, caller, GROUP_NAME_MAP)
        assert result["id"] == "acct-001"
        assert result["username"] == "zhangsan"
        assert result["displayName"] == "张三"
        assert result["groupName"] == "工程组"

    def test_normal_user_sees_only_L0(self) -> None:
        """普通用户只看 L0 字段。"""
        caller = {"role_name": "普通用户"}
        result = format_account_by_role(SAMPLE_DOC, caller, GROUP_NAME_MAP)
        assert set(result.keys()) == {"id", "username", "displayName"}

    def test_no_password_fields_ever(self) -> None:
        """密码字段永远不出现在响应中（即使平台管理员）。"""
        caller = {"role_name": "平台管理员"}
        result = format_account_by_role(SAMPLE_DOC, caller, GROUP_NAME_MAP)
        assert "password_hash" not in result
        assert "password_salt" not in result
        assert "mfa_secret_encrypted" not in result


# ══════════════════════════════════════════════════════════════════════
# QF-662：非生产数据脱敏
# ══════════════════════════════════════════════════════════════════════


class TestIsNonProduction:
    """环境检测测试。"""

    def test_non_prod_environments(self) -> None:
        """常见非生产环境应被识别。"""
        for env in ("development", "dev", "staging", "test", "local", ""):
            old_env = getattr(settings, "app_env", "")
            try:
                settings.app_env = env
                assert is_non_production(), f"Should detect '{env}' as non-prod"
            finally:
                settings.app_env = old_env

    def test_production_not_detected(self) -> None:
        """生产环境不应被识别为非生产。"""
        old_env = getattr(settings, "app_env", "")
        try:
            settings.app_env = "production"
            assert not is_non_production()
        finally:
            settings.app_env = old_env


class TestSanitizeValue:
    """值脱敏测试。"""

    def test_email_masking(self) -> None:
        result = sanitize_value("zhangsan@example.com", field_hint="email")
        assert "@example.com" in result
        assert "zhangsan" not in result

    def test_phone_masking(self) -> None:
        result = sanitize_value("13812345678", field_hint="phone")
        assert "****" in result
        assert "138" in result
        assert "5678" in result

    def test_password_redaction(self) -> None:
        result = sanitize_value("supersecret123", field_hint="password")
        assert result == "[REDACTED]"

    def test_secret_redaction(self) -> None:
        result = sanitize_value("mysecrettoken", field_hint="secret")
        assert result == "[REDACTED]"

    def test_token_redaction(self) -> None:
        result = sanitize_value("ghp_1234567890", field_hint="token")
        assert result == "[REDACTED]"

    def test_hash_redaction(self) -> None:
        result = sanitize_value("sha256_hash_value", field_hint="hash")
        assert result == "[REDACTED]"

    def test_short_string_masking(self) -> None:
        """短字符串全部替换为 *。"""
        result = sanitize_value("abc", field_hint="name")
        assert result == "***"

    def test_long_string_partial_masking(self) -> None:
        """长字符串前 3 后 3 保留。"""
        result = sanitize_value("abcdefghijkl", field_hint="name")
        assert result.startswith("abc")
        assert result.endswith("jkl")
        assert "*" in result

    def test_non_string_unchanged(self) -> None:
        """非字符串类型不变。"""
        assert sanitize_value(123) == 123
        assert sanitize_value(True) is True
        assert sanitize_value(None) is None
        assert sanitize_value([]) == []

    def test_empty_string_unchanged(self) -> None:
        assert sanitize_value("", field_hint="email") == ""


class TestSanitizeDocument:
    """文档脱敏测试。"""

    def test_sensitive_fields_masked(self) -> None:
        """敏感字段应被脱敏（非生产环境）。"""
        old_env = getattr(settings, "app_env", "")
        try:
            settings.app_env = "development"
            doc = {
                "email": "test@example.com",
                "phone": "13812345678",
                "password_hash": "hashed",
                "password_salt": "salted",
                "username": "testuser",
            }
            result = sanitize_document(doc)
            assert result["username"] == "testuser"  # 不变
            assert "test@example.com" not in result["email"]  # 脱敏
            assert "****" in result["phone"]  # 脱敏
            assert result["password_hash"] == "[REDACTED]"  # 脱敏
        finally:
            settings.app_env = old_env

    def test_production_unchanged(self) -> None:
        """生产环境不脱敏。"""
        old_env = getattr(settings, "app_env", "")
        try:
            settings.app_env = "production"
            doc = {"email": "test@example.com", "username": "testuser"}
            result = sanitize_document(doc)
            assert result["email"] == "test@example.com"  # 不变
            assert result["username"] == "testuser"
        finally:
            settings.app_env = old_env

    def test_none_returns_none(self) -> None:
        assert sanitize_document(None) is None

    def test_id_fields_unchanged(self) -> None:
        """_id 等下划线开头的字段不脱敏。"""
        old_env = getattr(settings, "app_env", "")
        try:
            settings.app_env = "development"
            doc = {"_id": "acct-123", "email": "test@example.com"}
            result = sanitize_document(doc)
            assert result["_id"] == "acct-123"  # 不变
            assert "test@example.com" not in result["email"]  # 脱敏
        finally:
            settings.app_env = old_env


class TestSyntheticData:
    """合成数据生成测试。"""

    def test_generate_single_account(self) -> None:
        account = generate_synthetic_account()
        assert account["username"].startswith("user_")
        assert "@" in account["email"]
        assert account["password_hash"] == ""  # 合成数据无真实密码
        assert account["status"] == "active"
        assert account["tenant_id"] == "default"

    def test_generate_multiple_accounts(self) -> None:
        accounts = generate_synthetic_accounts(5)
        assert len(accounts) == 5
        usernames = {a["username"] for a in accounts}
        assert len(usernames) == 5  # 唯一用户名

    def test_custom_parameters(self) -> None:
        account = generate_synthetic_account(
            tenant_id="tenant-xyz",
            username="custom_user",
            display_name="自定义名称",
            role_name="自定义角色",
        )
        assert account["tenant_id"] == "tenant-xyz"
        assert account["username"] == "custom_user"
        assert account["display_name"] == "自定义名称"
        assert account["role_name"] == "自定义角色"

    def test_seed_synthetic_data(self) -> None:
        data = seed_synthetic_data()
        assert "accounts" in data
        assert "groups" in data
        assert len(data["accounts"]) == 5
        assert len(data["groups"]) == 3
        # 验证组有 code 和 name
        for group in data["groups"]:
            assert "code" in group
            assert "name" in group

    def test_synthetic_data_no_real_pii(self) -> None:
        """合成数据不包含真实 PII。"""
        accounts = generate_synthetic_accounts(10)
        for account in accounts:
            # 邮箱应为合成域名
            assert any(
                account["email"].endswith(d)
                for d in ("example.com", "example.org", "test.local")
            )
            # 密码应为空
            assert account["password_hash"] == ""
            assert account["password_salt"] == ""


# ══════════════════════════════════════════════════════════════════════
# 端到端集成测试
# ══════════════════════════════════════════════════════════════════════


class TestQF660Integration:
    """QF-660 端到端集成测试。"""

    def test_role_hierarchy_consistent(self) -> None:
        """角色层级一致性：高权限角色的字段集 ⊇ 低权限角色。"""
        callers = [
            ("普通用户", L0_FIELDS),
            ("组织成员", L1_FIELDS),
            ("组织管理员", L2_FIELDS),
            ("平台管理员", L3_FIELDS),
        ]
        for i in range(len(callers) - 1):
            low_role, low_fields = callers[i]
            high_role, high_fields = callers[i + 1]
            assert low_fields.issubset(high_fields), (
                f"{low_role} fields should be subset of {high_role} fields"
            )

    def test_response_never_contains_credential_fields(self) -> None:
        """任何角色的响应都不应包含凭证字段。"""
        sensitive = {"password_hash", "password_salt", "mfa_secret_encrypted"}
        for role_name in ("平台管理员", "组织管理员", "组织成员", "普通用户"):
            caller = {"role_name": role_name}
            result = format_account_by_role(SAMPLE_DOC, caller, GROUP_NAME_MAP)
            leaked = sensitive & set(result.keys())
            assert not leaked, f"{role_name} response leaked: {leaked}"
