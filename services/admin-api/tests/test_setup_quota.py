from __future__ import annotations

from unittest import IsolatedAsyncioTestCase
from unittest import mock

from app.services.setup_quota import configure_setup_quotas


class _FakeCollection:
    """``update_one`` / ``insert_many`` 计数，供断言「到达 DB 层」用。"""

    def __init__(self) -> None:
        self.update_count = 0
        self.insert_count = 0

    async def update_one(self, *args, **kwargs) -> None:
        self.update_count += 1

    async def insert_many(self, *args, **kwargs) -> None:
        self.insert_count += 1


class _FakeDB(dict):
    """任意集合访问都返回同一个 ``_FakeCollection``。"""

    def __init__(self) -> None:
        super().__init__()
        self._col = _FakeCollection()

    def __getitem__(self, key: str) -> _FakeCollection:
        return self._col


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
        # 0 means "unlimited" — it must NOT be rejected in the validation layer
        # before touching the database. We mock ``get_db`` so the test is
        # independent of whether a real motor client is importable / reachable
        # (11-13 QA: on a healthy env real motor is importable, so the conftest
        # "motor stub" RuntimeError is never raised and the old test failed).
        db = _FakeDB()
        with mock.patch("app.services.setup_quota.get_db", return_value=db):
            await configure_setup_quotas(
                tenant_id="test-main-id",
                total_tokens=0,
                default_user_tokens=0,
                period="monthly",
                timezone_name="Asia/Shanghai",
                operator="admin",
            )
        # Reached the DB layer (no ValueError); quota docs were written:
        # org policy update_one + user policy update_one + user quota log
        # insert_many (setup_quota.py:50-79).
        self.assertEqual(
            db._col.update_count + db._col.insert_count, 3
        )
