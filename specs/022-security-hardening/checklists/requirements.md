# Requirements Quality Checklist: 022 security-hardening

**Created**: 2026-10-12

**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Purpose**: 校验 022（安全加固）spec.md 的需求质量——完整性、清晰度、一致性、边界。这是"需求的单元测试"，**不校验实现是否正确**。

## 完整性（Completeness）

- [x] CHK001 US1 口令与 MFA 是否完整定义弱口令拒绝、MFA 强制、第二因子限流、TOTP 防重放、解绑通知 5 项能力及其策略数值（FR-1/FR-2/FR-3/FR-4/FR-5）？
- [x] CHK002 US2 令牌与会话生命周期是否完整定义 TTL ≤ 3600s、refresh 一次性轮换、空闲/绝对超时、服务间独立凭证、重置强制改密 5 项能力（FR-6/FR-7/FR-8/FR-9/FR-10）？
- [x] CHK003 US3 授权与权限最小化是否完整定义 4 个 Dockerfile 非 root（UID ≥ 10001）、容器只读文件系统与 cap_drop、服务身份权限最小化（FR-11/FR-12/FR-13）？
- [x] CHK004 US4 输入安全是否完整定义 SSO 令牌 POST 换票、GET 无副作用、CORS 显式白名单 3 项能力（FR-14/FR-15/FR-16）？
- [x] CHK005 US5 数据安全是否完整定义 HTTPS 强制、内部链路加密、敏感字段密文存储、KMS 托管与密钥分离、日志脱敏、响应裁剪、调试关闭、数据地图、审计防篡改 9 项能力（FR-17~FR-24）？
- [x] CHK006 US6 供应链安全是否完整定义依赖漏洞扫描阻断、构建/部署凭证分离、不可变版本与来源校验、提交钩子阻止密钥、漏洞工单与安全公告 5 项能力（FR-25~FR-29）？
- [x] CHK007 29 条 FR 是否全部可追溯到 QualityForge 审计的具体 QF 编号（QF-521~706），无孤立项（FR-1~FR-29）？
- [x] CHK008 6 个用户故事是否均为 P1、均有 Acceptance Scenarios 且可独立交付、可独立测试（US1~US6）？
- [x] CHK009 8 项 Non-Goals 是否明确排除不引入 IDS/WAF、不改变认证架构、不引入第三方 KMS、不重建权限码与审计落点等越界工作（Non-Goals）？

## 一致性（Consistency）

- [x] CHK010 与 001 gatekeeper-governance 的双向声明是否一致——022 加固后的事件 100% 过 001 门禁审计、FR-11 建立在 001 权限码模型之上（022↔001）？
- [x] CHK011 与 006 position-rbac-admin 的关系是否明确——006 岗位角色权限码是 FR-11 最小权限预设组基础，022 不重建权限码模型（022↔006）？
- [x] CHK012 与 017 three-scope-memory、020 platform-multi-tenancy 的关系是否明确——scope 可见性是跨租户越权拒绝的语义基础，租户隔离是 tenantId 一致性校验的维度基础（022↔017/020）？
- [x] CHK013 FR-12/FR-13（容器非 root 与能力最小化）与 US3/US6 Acceptance Scenarios 中"4 个 Dockerfile 均以非 root 运行"的表述是否口径一致（FR-12/FR-13）？
- [x] CHK014 FR-18（内部服务间加密）与 OQ-4 决策"首期以内网隔离 + 独立凭证满足、mTLS 可选"是否不冲突（FR-18/OQ-4）？

## 边界与歧义（Edge cases & Ambiguity）

- [x] CHK015 OQ-1 是否消解 MFA 解绑通知通道未接入时的降级路径（降级为审计事件，QF-530 以审计事件满足最小合规）（FR-5/OQ-1）？
- [x] CHK016 OQ-2 是否消解首期密钥管理边界（环境变量 + `KMSProvider` 抽象接口预留，Vault 为可选集成，数据密钥不入库不入码）（FR-19/OQ-2）？
- [x] CHK017 OQ-3 是否消解 HTTPS 终结点归属（TLS 终结在 nginx/traefik 反向代理层，应用层通过 `SECURE_PROXY_SSL_HEADER` 感知，不直接暴露 TLS）（FR-17/OQ-3）？
- [x] CHK018 OQ-5 是否消解 CORS 白名单来源（由 `CORS_ORIGINS` 环境变量配置，默认空即拒绝所有跨域，不硬编码）（FR-16/OQ-5）？

## Notes

- 本文件是**需求质量门禁**：`[x]` 表示 spec.md 对该项的定义完整、口径一致、边界明确；**不代表实现完成**，58 项任务仍待推进（见 tasks.md）。
- 首个可独立验证切片为 **Phase 0 安全基座 + US1（口令与 MFA）**：`app/security/` 模块落地后，US1 的 4 条 Acceptance Scenarios 可单独跑通（弱口令 400 / MFA 未绑无法进入 / TOTP 90s 不可重放 / 解绑通知审计）。
- 5 个 Open Question 均已在 Clarify 记录中消解（2026-10-11），OQ-4 的 mTLS 明确排除出首期范围，与 FR-18 的"或"式表述不冲突，故无保留未勾项。
