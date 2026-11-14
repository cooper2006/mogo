import asyncio

from app.services.employee_tenant_identity import authoritative_tenant_names, employee_tenant_fields, repair_employee_tenant_identities
from app.position_roles.repository import PositionRoleRepository
from app.system_audit.repository import SystemAuditRepository
from app.system_audit.query import SystemAuditQuery


class DatabaseWithoutTruthValue:
    def __bool__(self):
        raise NotImplementedError("Database objects do not support boolean evaluation")

    def __init__(self):
        self.organizations = self
        self.admin_accounts = self

    def find(self, *_args):
        return self

    async def to_list(self, *, length):
        return []


def test_enterprise_employee_identity_uses_display_name() -> None:
    assert employee_tenant_fields("org_deadbeef", "示例科技") == {
        "org_name": "示例科技",
        "space_type": "enterprise",
    }


def test_personal_space_identity_is_preserved() -> None:
    assert employee_tenant_fields("personal_1", "个人空间")["space_type"] == "personal"


def test_admin_identity_wins_over_stale_billing_organization_name() -> None:
    names = authoritative_tenant_names(
        [{"tenant_id": "org_1", "org_name": "个人空间"}],
        [{"tenant_id": "org_1", "org_name": "示例科技"}],
    )
    assert names["org_1"] == "示例科技"


def test_repair_accepts_database_without_boolean_evaluation() -> None:
    assert asyncio.run(repair_employee_tenant_identities(DatabaseWithoutTruthValue())) == 0


def test_repositories_accept_database_without_boolean_evaluation() -> None:
    database = DatabaseWithoutTruthValue()
    assert PositionRoleRepository(database).db is database
    assert SystemAuditRepository(database).db is database
    assert SystemAuditQuery(database).db is database
