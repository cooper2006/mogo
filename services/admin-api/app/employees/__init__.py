"""数字员工档案（051 B1）—— admin-api 侧共享集合模块。

与 chat-api ``app/employees`` 共用 ``employees`` 集合（027 门面双后端），
口径参照 049 双服务 ``quota_policy.py`` 同口径先例（共享口径测试守护）。
本模块是 admin-api 侧的同口径实现，仅暴露管理端需要的读写与校验。
"""

from .repository import EmployeeRepository, AUDIT_COLLECTION
from .profile import validate_employee_references, EmployeeReferenceError

__all__ = [
    "EmployeeRepository",
    "AUDIT_COLLECTION",
    "validate_employee_references",
    "EmployeeReferenceError",
]
