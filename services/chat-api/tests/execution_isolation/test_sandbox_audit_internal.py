import asyncio

import pytest
from fastapi import HTTPException

from app.api.endpoints.sandbox_audit_internal import get_call_text
from app.api.principal import ApiPrincipal


def test_end_user_cannot_read_admin_audit_entry() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(get_call_text(
            "message", "call", "stdout",
            principal=ApiPrincipal(kind="end_user", tenant_id="tenant", user_id="user"),
        ))
    assert error.value.status_code == 403
