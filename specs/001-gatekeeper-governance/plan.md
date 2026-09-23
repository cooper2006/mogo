# Implementation Plan: Unified Six-Layer Gatekeeper

**Branch**: `001-gatekeeper-governance` | **Date**: 2026-07-08 | **Spec**: [specs/001-gatekeeper-governance/spec.md](./spec.md)

**Input**: Feature specification from `specs/001-gatekeeper-governance/spec.md`

## Summary

工具调用（tool invocation）在现有 admin-api 中散落在 `position_roles`（粗粒度岗位角色）与 `system_audit`（审计记录），缺少统一串行门禁、风险分级、PII 脱敏与配额计量。本特性在 `services/admin-api` 新增独立模块 `governance/`，实现六层串行门禁链（Identity → RBAC → PII Redaction → Approval → Quota → Audit），将工具风险级（R0–R4）与执行自主级别（L1–L5）的 25 格矩阵作为审批决策源，并以声明式配置驱动，使门禁层可增删无需改代码。

## Technical Context

**Language/Version**: Python 3.13（沿用 services 现有技术栈，参考 `services/admin-api` 依赖）

**Primary Dependencies**: FastAPI / SQLAlchemy（admin-api 既有框架）；无新增重型依赖，正则库用于 PII 识别（`re` 标准库足够）

**Storage**: 沿用 admin-api 现有数据库（不新增 storage 引擎）。新增表：`gatekeeper_rules`、`risk_tiers`、`autonomy_matrix`、`pii_policies`、`quota_limits`、`gate_events`（审计落库）

**Testing**: pytest + httpx（admin-api 既有测试栈，参考 services 现有测试）

**Target Platform**: Linux 自托管 Docker Compose（movo 交付形态），Windows 安装形态通过同一镜像

**Project Type**: backend-service（治理层模块，嵌入既有 admin-api）

**Performance Goals**: 单次工具调用的门禁链 p95 < 15ms（含六层短路判断，不含审批等待）；审计落库异步

**Constraints**: 门禁链不改变 DSH 运行时 Agent 执行语义；审批挂起必须可恢复（超时默认 5 分钟）；PII 脱敏对工具请求体不可逆（remove 策略）

**Scale/Scope**: 首期 10 个 resource × 5 个 action 的权限码；5 类 PII（私钥/身份证/银行卡/手机号/邮箱）；配额三维（租户/用户/工具）

## Constitution Check

| 原则 | 检查结果 |
|---|---|
| I. Specification-First | 通过：spec.md 已完成，本 plan 为规格产物 |
| II. Enterprise Production Readiness | 通过：门禁不可被绕过；审计全量；R4 红线 deny |
| III. Security and Data Protection | 通过：fail-closed；PII 策略化；凭据不进仓库 |
| IV. Cross-Platform and i18n | 通过：纯后端模块，无 UI 文案 |
| V. Observability and Simplicity | 通过：gate_events 结构化日志；声明式配置 |

## Project Structure

### Documentation (this feature)

```text
specs/001-gatekeeper-governance/
├── plan.md              # 本文件
├── research.md          # Phase 0：现有 position_roles/system_audit 集成点调研
├── data-model.md        # Phase 1：六张新表的 ER 与字段定义
├── quickstart.md        # Phase 1：门禁启用与验证步骤
├── contracts/
│   └── gatekeeper.md    # 六层门禁输入/输出契约 + 25 格矩阵定义
└── tasks.md             # Phase 2（/speckit-tasks 产出，本步骤不创建）
```

### Source Code (repository root)

```text
services/admin-api/
├── app/
│   ├── governance/                      # 新增模块
│   │   ├── __init__.py
│   │   ├── gatekeeper.py                # 六层链编排 + 短路 + 审计落点
│   │   ├── layers/                      # 六层实现
│   │   │   ├── __init__.py
│   │   │   ├── identity.py              # 层 1：调用主体解析（租户/用户/岗位角色）
│   │   │   ├── rbac.py                  # 层 2：权限码判定，fail-closed
│   │   │   ├── redaction.py             # 层 3：PII 脱敏（策略：mask/remove/hash/abstract）
│   │   │   ├── approval.py              # 层 4：审批挂起/放行（查 autonomy_matrix）
│   │   │   ├── quota.py                 # 层 5：三维配额计量
│   │   │   └── audit.py                 # 层 6：gate_events 落库
│   │   ├── risk.py                      # R0–R4 风险分级注册 + 25 格 AUTONOMY_MATRIX
│   │   ├── rbac_model.py                # 权限码 <resource>:<action>[:<target>] 三级隔离
│   │   ├── pii.py                       # PII 识别器（正则）+ 策略引擎
│   │   ├── quota.py                     # 配额存储与计量
│   │   ├── config.py                    # 声明式配置 schema（门禁层增删）
│   │   └── api/
│   │       └── routes.py                # /api/governance/* 管理端点（规则/矩阵/策略 CRUD）
│   └── api/routes/tools.py              # 既有：在工具调用入口注入 gatekeeper 调用
└── tests/
    └── test_governance/                 # 六层单元 + 集成 + 25 格矩阵测试
```

## Key Integration Points

1. **工具调用入口**：`services/admin-api/app/api/routes/tools.py` 在工具执行前调用 `gatekeeper.evaluate(tool, ctx)`；被拒返回 403/429/409，审批挂起返回 409 + 审批 token
2. **岗位角色兼容**：`position_roles/service.py` 的岗位角色视为权限码预设组，`governance/rbac_model.py` 提供 `expand_role_to_codes(role) -> set[str]`
3. **审计复用**：`system_audit/repository.py` 的写入路径复用于 `gate_events`，保持审计单一落点
4. **审批挂起**：审批表与 admin 端审批流对接（现有 approval 机制，如不存在则新增 `approval_requests` 表）

## Open Questions（需 /speckit-clarify 消解）

- OQ-1: 现有 admin-api 是否已有 approval 流程表？审批挂起的恢复机制是 poll 还是 callback？
- OQ-2: 配额计量用数据库计数还是 Redis？自托管形态是否允许引入 Redis？
- OQ-3: PII 策略默认值（手机号 mask / 私钥 remove）是否需要按租户可配置，还是全局固定？

## 下一步

按 SDD 路径：
1. `/speckit-clarify`（消解 OQ-1~3）
2. `/speckit-plan` 完成 Phase 0/1：research.md、data-model.md、contracts/gatekeeper.md、quickstart.md
3. `/speckit-checklist`（生产特性质量门禁）
4. `/speckit-tasks`
5. `/speckit-analyze`（一致性检查）
6. `/speckit-implement`
7. `/speckit-converge`
