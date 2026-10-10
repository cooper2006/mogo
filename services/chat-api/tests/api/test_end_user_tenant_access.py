import asyncio

from app.services.end_user_tenant_access import load_tenant_candidates, project_tenant_candidate, resolve_space_type


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, length):
        return self.rows[:length]


class _Collection:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query, projection=None):
        tenant_ids = set(query.get("tenant_id", {}).get("$in", []))
        status = query.get("status")
        return _Cursor([
            row for row in self.rows
            if row.get("tenant_id") in tenant_ids and (status is None or row.get("status") == status)
        ])


class _Db:
    def __init__(self, organizations, admin_accounts, tenants=None):
        self.organizations = _Collection(organizations)
        self.admin_accounts = _Collection(admin_accounts)
        self.tenants = _Collection(tenants or [])

    def __getitem__(self, name):
        assert name == "tenants", f"unexpected collection in test fake: {name}"
        return self.tenants


def test_authoritative_organization_name_replaces_technical_tenant_id() -> None:
    candidate = project_tenant_candidate(
        {"_id": "u1", "tenant_id": "org_deadbeef", "login_name": "employee", "name": "普通员工"},
        {"tenant_id": "org_deadbeef", "org_name": "示例科技"},
        None,
    )
    assert candidate["orgName"] == "示例科技"
    assert candidate["spaceType"] == "enterprise"
    assert candidate["canAccessAdmin"] is False


def test_explicit_enterprise_identity_wins_over_stale_personal_organization() -> None:
    candidate = project_tenant_candidate(
        {
            "_id": "u1",
            "tenant_id": "org_1",
            "login_name": "employee",
            "name": "普通员工",
            "org_name": "示例科技",
            "space_type": "enterprise",
        },
        {"tenant_id": "org_1", "org_name": "个人空间"},
        None,
    )
    assert candidate["orgName"] == "示例科技"
    assert candidate["spaceType"] == "enterprise"


def test_admin_access_requires_active_non_member_admin_account() -> None:
    user = {"_id": "u1", "tenant_id": "org_1", "login_name": "employee"}
    organization = {"tenant_id": "org_1", "org_name": "示例科技"}
    assert project_tenant_candidate(user, organization, {"status": "active", "group_code": "member"})["canAccessAdmin"] is False
    assert project_tenant_candidate(user, organization, {"status": "disabled", "group_code": "admin"})["canAccessAdmin"] is False
    assert project_tenant_candidate(user, organization, {"status": "active", "group_code": "admin"})["canAccessAdmin"] is True


def test_explicit_personal_space_remains_personal() -> None:
    assert resolve_space_type({"space_type": "personal", "org_name": "个人空间"}) == "personal"


def test_personal_space_never_projects_admin_access() -> None:
    candidate = project_tenant_candidate(
        {"_id": "u1", "tenant_id": "personal_1", "login_name": "owner", "space_type": "personal"},
        {"tenant_id": "personal_1", "org_name": "个人空间"},
        {"status": "active", "group_code": "admin"},
    )
    assert candidate["spaceType"] == "personal"
    assert candidate["canAccessAdmin"] is False


def test_admin_org_name_is_tenant_fallback_without_granting_employee_admin_access() -> None:
    db = _Db([], [{
        "tenant_id": "org_1", "username": "owner", "org_name": "示例科技", "status": "active", "group_code": "admin",
    }])
    candidates = asyncio.run(load_tenant_candidates(db, [{
        "_id": "u1", "tenant_id": "org_1", "login_name": "employee", "org_name": "org_1",
    }]))
    assert candidates[0]["orgName"] == "示例科技"
    assert candidates[0]["canAccessAdmin"] is False


# ---------------------------------------------------------------------------
# FR-024: an archived tenant must not be selectable
# ---------------------------------------------------------------------------


def _user(tenant_id="org_1"):
    return {"_id": "u1", "tenant_id": tenant_id, "login_name": "employee", "org_name": "示例科技"}


def _db_with_status(status):
    return _Db(
        [{"tenant_id": "org_1", "org_name": "示例科技"}],
        [],
        tenants=[{"tenant_id": "org_1", "status": status}],
    )


def test_archived_tenant_is_not_a_login_candidate() -> None:
    """Regression for the audit finding: employees could still log into an archived tenant."""
    candidates = asyncio.run(load_tenant_candidates(_db_with_status("archived"), [_user()]))
    assert candidates == []


def test_disabled_and_purged_tenants_are_not_candidates() -> None:
    for status in ("disabled", "purged"):
        assert asyncio.run(load_tenant_candidates(_db_with_status(status), [_user()])) == []


def test_active_tenant_is_still_a_candidate() -> None:
    candidates = asyncio.run(load_tenant_candidates(_db_with_status("active"), [_user()]))
    assert [c["tenantId"] for c in candidates] == ["org_1"]


def test_tenant_without_registry_row_is_grandfathered() -> None:
    """A pre-020 deployment has an empty ``tenants`` collection; do not lock everyone out."""
    db = _Db([{"tenant_id": "org_1", "org_name": "示例科技"}], [], tenants=[])
    candidates = asyncio.run(load_tenant_candidates(db, [_user()]))
    assert [c["tenantId"] for c in candidates] == ["org_1"]


def test_is_tenant_selectable_matches_candidate_filtering() -> None:
    from app.services.end_user_tenant_access import is_tenant_selectable

    assert asyncio.run(is_tenant_selectable(_db_with_status("active"), "org_1")) is True
    assert asyncio.run(is_tenant_selectable(_db_with_status("archived"), "org_1")) is False
    assert asyncio.run(is_tenant_selectable(_db_with_status("null"), "org_1")) is False
