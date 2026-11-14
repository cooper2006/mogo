"""数字员工档案（051-digital-employee-profile，B1）。

员工 = 面向业务用户的 agent 组装单元：能力白名单 + 知识库挂载 + 记忆 scope +
模型配置 + Harness profile 引用 + 状态 + 创建者/成员列表。不改造 006 岗位角色
（人的 RBAC），员工能力边界沿用其白名单范式，但绑定对象是 agent 会话。
"""

from .model import (
    EMPLOYEE_COLLECTION,
    EMPLOYEE_STATUSES,
    Employee,
    EmployeeProfile,
)
from .repository import EmployeeRepository
from .profile import materialize_employee_profile, validate_employee_references

__all__ = [
    "EMPLOYEE_COLLECTION",
    "EMPLOYEE_STATUSES",
    "Employee",
    "EmployeeProfile",
    "EmployeeRepository",
    "materialize_employee_profile",
    "validate_employee_references",
]
