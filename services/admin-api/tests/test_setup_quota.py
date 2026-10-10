from __future__ import annotations

from unittest import IsolatedAsyncioTestCase

from app.services.setup_quota import configure_setup_quotas


class SetupQuotaValidationTests(IsolatedAsyncioTestCase):
    async def test_rejects_default_employee_quota_above_org_total(self) -> None:
        with self.assertRaisesRegex(ValueError, "不能超过企业总 Token"):
            await configure_setup_quotas(
                tenant_id="test-main-id",
                total_tokens=100,
                default_user_tokens=101,
                period="monthly",
                timezone_name="Asia/Shanghai",
                operator="admin",
            )

    async def test_rejects_negative_quota_value(self) -> None:
        # T036/decision 12: 0 now means "unlimited", so only negatives are invalid.
        with self.assertRaisesRegex(ValueError, "不能为负数"):
            await configure_setup_quotas(
                tenant_id="test-main-id",
                total_tokens=-1,
                default_user_tokens=0,
                period="monthly",
                timezone_name="Asia/Shanghai",
                operator="admin",
            )

    async def test_zero_total_tokens_is_unlimited(self) -> None:
        # 0 must NOT be rejected before touching the database; it means unlimited.
        with self.assertRaises(RuntimeError):
            await configure_setup_quotas(
                tenant_id="test-main-id",
                total_tokens=0,
                default_user_tokens=0,
                period="monthly",
                timezone_name="Asia/Shanghai",
                operator="admin",
            )
