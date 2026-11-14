# Implementation Plan: SOP 转人工节点（050-sop-human-handoff）

**Branch**: `050-sop-human-handoff` | **Date**: 2026-11-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/050-sop-human-handoff/spec.md`

**Note**: **全新特性**（StaffDeck 整合方案 §4.1 立项，代码尚未开工）——spec 先行，tasks 全部未勾选；本特性改 010 引擎（含契约联合改动点）并新增运行持久化地基（052 消费）。

## Summary

在 010 DAG 引擎（`services/chat-api/app/orchestration/`）新增 `human_approval` 节点与编排运行持久化：

- **`human_approval.py`**（新模块）：节点执行器——挂起写快照 + 持久化长效待办；决策时经 `ApprovalRuntime.issue` 即时签发并 `validate_and_consume` 消费短 TTL 票据，随后续跑或驳回（`on_reject` 分支 / 默认终止）；超时 fail-closed。
- **`run_store.py`**（新模块）：`orchestration_runs` 集合的运行仓库——创建锁定定义版本、节点级 checkpoint、挂起/恢复/终态状态机、恢复扫描（单活租约，参照 `scheduled_tasks` 恢复范式）。
- **引擎接线**：`dispatch.py` / `engine.py` 在节点完成与挂起点写 checkpoint；含审批节点的运行经 run_store 驱动，不含审批节点的既有路径行为不变（FR-009）。
- **通知与入口**：站内审批待办（复用既有审批页数据面）+ 013 `render_reply` 渲染的应答式触达；主动推送边界待 OQ-2 clarify。
- **画布与契约**：039 画布审批节点卡片/属性面板；010 目录 `contracts/orchestration.md` 补审批节点 YAML 形态。

## Technical Context

**Language/Version**: Python 3.13（chat-api，Dockerfile 钉版）；前端 Vue 3 + TypeScript（user-web）

**Primary Dependencies**: 既有 `app.orchestration` 包、`app.governance.approval_runtime.ApprovalRuntime`、`app.im_gateway`（渲染）、027 数据门面（`MOGO_DATA_BACKEND`）；**不引入新第三方依赖**

**Storage**: 新增 `orchestration_runs` / `approval_todos` 集合（经 027 兼容门面，MongoDB 默认 / PanWeiDB 可选）；定义版本快照内嵌运行文档（避免跨集合版本漂移）

**Testing**: pytest（`services/chat-api/tests/orchestration/` 既有树 + 新增 `test_human_approval.py` / `test_run_store.py` / `test_run_recovery.py`）；既有编排测试零修改全绿；前端 SFC 编译 + vue-tsc（039 画布改动）

**Target Platform**: Docker Compose（chat-api + user-web）

**Project Type**: web-service 后端引擎扩展 + 前端画布节点

**Performance Goals**: checkpoint 写入不阻塞节点热路径超过既有审计写入口径；恢复扫描周期与 `scheduled_tasks` 同量级；挂起运行数量无进程内上限（持久化即释放协程）

**Constraints**: 既有六模式零行为改动（FR-009）；审批 fail-closed（FR-006，无超时自动批准）；引擎保持 transport-agnostic（runner 注入）；双后端同口径（FR-011）；OQ-1~OQ-4 clarify 前不进入实现

**Scale/Scope**: 2 个新模块（human_approval / run_store）+ dispatch/engine 接线 + loader 形状校验 + 待办 API + 画布节点 + 契约刷新；0 新依赖

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 三件套先于代码；七个决策点已拍板，四个 OQ 显式登记为 clarify 门禁。
- **II. Enterprise Production Readiness**: ✅ 失败路径全显式：超时/自审/已消费待办重复提交决策/无效审批人/快照写失败均 fail-closed；重启恢复有测试范式（`test_scheduler_recovery.py`）；无不可观测挂起（待办 + 审计 + 运行状态可查）。
- **III. Security and Data Protection**: ✅ 审批复用 `ApprovalRuntime`（审批与消费分离）；决策全审计（001 审计流）；待办 API 走既有鉴权与租户隔离；无新凭据面。
- **IV. Cross-Platform and i18n**: ✅ 画布节点文案中英双语（039 既有 i18n 口径）；后端错误信息沿用既有风格。
- **V. Observability and Simplicity**: ✅ 复用而非另起：票据/审计/渠道渲染全部委托既有实现；运行持久化是 052 共用的地基（一次投入两处受益）；不做分布式调度（单活租约恢复）。

## Project Structure

### Documentation (this feature)

```text
specs/050-sop-human-handoff/
├── spec.md              # 特性规约
├── plan.md              # 本文件
├── tasks.md             # 任务清单（全部未勾选）
└── checklists/requirements.md   # 需求质量门禁（未勾待审）
```

### Source Code (repository root)

```text
services/chat-api/app/orchestration/
├── human_approval.py      # 【新增】审批节点执行器 + 决策回调 + 超时判定
├── run_store.py           # 【新增】orchestration_runs 仓库 + checkpoint + 恢复扫描（租约）
├── loader.py              # 【修改】human_approval 形状校验（approver/on_reject 存在性，fail-closed）
├── dispatch.py            # 【修改】含审批节点运行经 run_store 驱动；无审批节点路径不变
├── engine.py              # 【修改】节点完成/挂起点 checkpoint 钩子（既有执行语义不变）
└── graph.py               # 【修改】节点类型常量（不改 VALID_MODES——审批是节点类型不是文档模式）

services/chat-api/app/api/endpoints/
└── orchestration_runs.py  # 【新增】运行查询/待办列表/决策提交/取消/改派（鉴权 + 租户隔离）

services/chat-api/app/governance/
└── approval_runtime.py    # 【零改动】复用 issue / validate_and_consume

apps/user-web/src/components/orchestration/
└── （039 画布节点注册处）  # 【修改】human_approval 卡片 + 属性面板 + i18n

specs/010-dag-orchestration-engine/contracts/
└── orchestration.md       # 【修改】补审批节点 YAML 形态与运行状态机语义

services/chat-api/tests/orchestration/
├── test_human_approval.py # 【新增】挂起/批准/驳回/超时/自审/重复决策
├── test_run_store.py      # 【新增】checkpoint/定义版本锁定/双后端口径
└── test_run_recovery.py   # 【新增】重启恢复/零重跑/并发恢复租约
# 【零修改】既有编排测试（回归门禁）
```

**Structure Decision**: 审批是**节点类型**而非文档级模式——`VALID_MODES` 不扩展（避免与 044 的模式语义混淆：模式描述"整图如何协作"，审批节点描述"单节点等人"），首期仅 graph 模式的图中可嵌入审批节点（其它模式声明→加载期 fail-closed，见 R-9）。运行持久化独立成 `run_store.py` 模块，052 直接消费，不内嵌进审批逻辑。

## Complexity Tracking

> 无 constitution 违规。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |

**已评估并拒绝的复杂度**：① 进程内异步等待审批（无持久化）——一次发布即丢流程，违背宪法 II，拒绝。② 分布式工作流调度器（多活恢复）——单活租约已满足恢复需求，分布式协调无场景支撑，YAGNI。③ 超时自动批准/默认放行——治理旁路，拒绝。④ 独立审批状态机——`ApprovalRuntime` 已有一次性票据与分离语义，另造必然分叉。