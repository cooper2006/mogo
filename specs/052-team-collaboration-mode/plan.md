# Implementation Plan: 团队协作模式（052-team-collaboration-mode）

**Branch**: `052-team-collaboration-mode` | **Date**: 2026-11-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/052-team-collaboration-mode/spec.md`

**Note**: **全新特性**（StaffDeck 整合方案 §4.3 立项，代码尚未开工）——**硬依赖 050 运行持久化与审批节点**；tasks 全部未勾选。

## Summary

在 010 DAG 引擎新增第七模式 `team`（新模块 `orchestration/team.py`）：

- **领导拆解指派**：领导节点（LLM，runner 注入）产出 TeamPlan 分派表，成员节点按分派执行；拆解/聚合语义参照 `supervisor.py`（不复用其失败阈值硬编码，团队口径独立配置）。
- **团队黑板**：运行级键值材料区（作者/版本/内容），存于 050 运行快照；旧版本保留。
- **验收循环**：ReviewVerdict（accept/rework + 意见）驱动退回重做；轮次上限默认 3（1..5 钳制）；达上限 fail-closed。
- **人工接管**：接管点经 050 `human_approval` 挂起，人工决策覆盖领导判定。
- **异步与恢复**：成员执行经 050 checkpoint/恢复驱动；单成员失败不拖垮团队，重指派有上限。

分发经 044 `dispatch.execute_orchestration` 扩 team 路由；`VALID_MODES` 七模式；010 契约文档联合刷新。既有六模式零改动。

## Technical Context

**Language/Version**: Python 3.13（chat-api）

**Primary Dependencies**: 既有 `app.orchestration` 包（engine/dispatch/supervisor/loader）、050 `run_store`/`human_approval`（硬依赖）、051 员工注入（软依赖）；**不引入新第三方依赖**

**Storage**: 无新集合——TeamRunState/黑板/验收记录全部内嵌 050 `orchestration_runs` 运行快照

**Testing**: pytest（`tests/orchestration/test_team.py` 新增）：拆解指派/黑板版本/验收循环/轮次钳制/达上限失败/单成员失败/接管/恢复/子节点原子性；既有六模式测试零修改全绿

**Target Platform**: Docker Compose（chat-api）

**Project Type**: web-service 后端引擎扩展（同 044）

**Performance Goals**: 验收轮次硬上限（最坏 token = 轮次 × (成员重做 + 验收)）；成员并发受 `max_concurrency` 约束（graph 同口径）；无无上限循环

**Constraints**: 050 未落地不得 implement（硬依赖）；既有六模式零行为改动；引擎 transport-agnostic（runner 注入）；领导判定解析失败 fail-closed（OQ-1 口径）；事件与 044 R-9 同构（明细收 payload）

**Scale/Scope**: 1 新模块（team.py）+ dispatch/loader/graph 枚举扩展 + 契约刷新；0 新依赖、0 新集合

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 三件套先于代码；七决策拍板（竞标明确排除），四 OQ 登记。
- **II. Enterprise Production Readiness**: ✅ 无死循环（轮次硬上限 + 重指派上限）；达上限 fail-closed；重启恢复经 050；领导失败/分派非法均显式失败。
- **III. Security and Data Protection**: ✅ 成员执行过 001 门禁 + 007 韧性；接管决策全审计；黑板内容经既有脱敏口径（001 PII 层），无新数据出口。
- **IV. Cross-Platform and i18n**: ✅ 纯后端引擎，无界面文案；错误信息沿用既有风格。
- **V. Observability and Simplicity**: ✅ 复用 044 分发/事件/子节点口径与 050 持久化；单模块实现；不内置 prompt 库、不做竞标（YAGNI）。

## Project Structure

### Documentation (this feature)

```text
specs/052-team-collaboration-mode/
├── spec.md
├── plan.md              # 本文件
├── tasks.md             # 全部未勾选
└── checklists/requirements.md
```

### Source Code (repository root)

```text
services/chat-api/app/orchestration/
├── team.py                # 【新增】TeamPlan 拆解指派 + Blackboard + 验收循环 +
│                          #  接管接线 + TeamRunState（内嵌 050 快照）
├── graph.py               # 【修改】VALID_MODES 扩 team（七模式）
├── loader.py              # 【修改】team 形状校验（members/轮次/接管点，fail-closed）+
│                          #  payload 新键（max_review_rounds/takeover 等）
├── dispatch.py            # 【修改】team 路由（文档级 + 节点级 wrap_node_runner）
└── __init__.py            # 【修改】导出 Team* 符号

specs/010-dag-orchestration-engine/contracts/
└── orchestration.md       # 【修改】六模式 → 七模式 + team YAML 形态

services/chat-api/tests/orchestration/
└── test_team.py           # 【新增】全场景（US1–US4）
# 【零修改】既有六模式测试（回归门禁）
```

**Structure Decision**: 沿袭 044 格局——每模式一个模块（`supervisor.py`/`round_robin.py`/`debate.py` 先例），引擎核心不放模式特化逻辑；团队状态内嵌 050 运行快照而非新集合（避免双存储一致性面）。领导判定为 LLM 输出 JSON（OQ-1 schema），解析失败 fail-closed——引擎不内置评审器（044 同口径）。

## Complexity Tracking

> 无 constitution 违规。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |

**已评估并拒绝的复杂度**：① 竞标机制——能力自报 + 报价择优引入博弈语义，无首期场景支撑，整合方案已定二期。② 项目级持久黑板——跨运行共享引入权限与生命周期面，首期运行内黑板足够。③ 独立团队状态集合——与 050 快照双写必然漂移，内嵌即可。④ 内置领导 prompt 库——非确定性进引擎核心，YAML 承载。