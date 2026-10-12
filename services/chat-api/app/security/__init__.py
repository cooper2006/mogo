"""安全基座 (022 security-hardening Phase 0).

为所有用户故事提供的基础设施：口令策略、MFA 强制策略、KMS 接口、
敏感字段加密、日志/响应脱敏、防篡改审计落点。

模块说明：
- :mod:`app.security.password_policy` — FR-1 弱口令策略
- :mod:`app.security.mfa_policy` — FR-2/3/4 MFA 强制 / 限流 / TOTP 防重放判定
- :mod:`app.security.kms` — FR-19 KMSProvider 抽象 + 环境变量实现（Vault 可选）
- :mod:`app.security.encryption` — FR-19 敏感字段 AES-256-GCM 加密
- :mod:`app.security.redaction` — FR-20/21 日志脱敏 / 响应裁剪
- :mod:`app.security.audit_events` — FR-23 防篡改审计事件（哈希链）

这些模块保持「纯逻辑 + 可注入依赖」形态：口令/MFA/加密/脱敏/哈希链的核心判定
不依赖数据库或网络，便于单元测试；只有 :class:`AuditEventRepository` 与
:class:`MongoTotpUsedStepStore` 触碰 MongoDB，且均可注入 fake。
"""

from __future__ import annotations

__all__ = [
    "audit_events",
    "encryption",
    "kms",
    "mfa_policy",
    "password_policy",
    "redaction",
]
