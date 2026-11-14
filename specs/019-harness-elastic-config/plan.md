# Implementation Plan: Thick/Thin Harness Elastic Configuration

**Branch**: `019-harness-elastic-config` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: 缺口新特性（P2 规模化生态，后置）。按场景在厚 Harness（重治理/全门禁/强审计）与薄 Harness（轻启动/快执行）间切换，推进 HaaS 思路。是特性 001（gatekeeper 六层门禁）的"弹性配置层"。

## Summary

新增 `services/chat-api/app/harness_config/` 子模块：厚度配置 schema（按场景/租户/工具维度声明启用哪些门禁层 + 审计粒度 + 超时策略）+ 层开关与 001 门禁链对接 + 底线守护（R4 红线与审计不可降档）。019 不改变 001 六层语义，只定义"启用哪几层"的开关层；默认厚模式，降级需显式配置。

## Technical Context

**Language/Version**: Python 3.13（chat-api 既有栈）

**Primary Dependencies**: 既有 001 gatekeeper 六层链（若未实现，先以 `governance/` + `enterprise_capabilities/tools` 的审批/审计为挂载点）+ 009 hooks（薄模式可跳过的非红线 Hooks）

**Storage**: 新增 `harness_profiles`（厚度配置，含 scope: scene/tenant/tool + 启用层列表 + 审计粒度）

**Testing**: pytest（层开关单测 + 底线守护测试（R4 不可降档/审计不可关）+ 配置变更审计测试）

**Target Platform**: 自托管 Docker Compose

**Project Type**: 新增模块（弹性配置层，P2 后置）

## 现有挂载点依据

- 门禁层：001 `governance`（六层链，若未实现以 `enterprise_capabilities/tools/approval_runtime` + `governance/audit` 为过渡挂载点）
- Hooks：009 `dsh_runtime/hooks`（薄模式跳过非红线 Hooks，fail_closed 底线保留）
- 红线：001 R4 工具（`risk.py` 风险分级，薄模式下仍 deny）
- 审计底线：复用 `governance/audit`（任何模式不可关闭）

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过 |
| II. Production Readiness | 通过：红线 + 审计不可降档 |
| III. Security | 通过：薄模式不绕过治理底线 |
| IV. i18n | 通过 |
| V. Observability | 通过：厚度配置变更审计 |

## Project Structure

```text
services/chat-api/app/
└── harness_config/
    ├── __init__.py
    ├── profile.py              # 厚度配置 schema（scope + 启用层 + 审计粒度）
    ├── layer_switch.py         # 与 001 门禁链对接的层开关
    ├── floor.py               # 底线守护（R4 不可降档 + 审计不可关）
    └── audit.py               # 厚度配置变更审计
services/chat-api/app/api/endpoints/
└── (新增 harness_profiles.py：厚度配置 CRUD + 作用域管理)
```

## Open Questions（已 clarify 消解）
- OQ-1 厚度维度优先级：**场景 > 租户 > 工具**（更具体覆盖更宽泛）。
- OQ-2 薄模式可省略层：**可省略 = 审批（第 4 层）+ 配额（第 5 层）**；**不可省略 = 身份（第 1）+ RBAC（第 2）+ 脱敏（第 3）+ 审计（第 6）+ R4 红线**。即薄模式 = 去掉"审批/配额"，保留"身份/RBAC/脱敏/审计/红线"。
- OQ-3 与 001 依赖顺序：**019 先挂 `governance/approval_runtime` + `governance/audit`（现有过渡挂载点），001 完成六层链后，019 层开关直接切到 001 gatekeeper**。二者不阻塞，019 可先行做配置层。
- OQ-4 审计"底线"最低粒度：**薄模式至少记录 身份主体 + 工具名 + 结果（通过/拒绝）+ 时间戳**（最小四元组，`harness_config/floor.py` 守护）。
- OQ-5 切换生效时机：**工具调用级**（每次工具调用解析当前会话 + 租户 + 工具的厚度 profile）。

## 下一步
OQ 已 clarify 消解。P2 后置，按路线图节奏推进：`/speckit-checklist` → `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement` → `/speckit-converge`。
