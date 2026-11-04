# Quickstart: 会话回放 (043)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md) | [checklists/requirements.md](./checklists/requirements.md)

本文件说明如何**启用并验证** 会话回放（043）。

---

## 1. 前置

- 相关服务已部署：user-web（视特性所属服务而定）
- MongoDB 可用（或 PanWeiDB 可选后端；`MOGO_DATA_BACKEND` 未设置即 MongoDB，行为不变）
- 后端测试需 Python 3.10+ 与对应服务 venv；前端测试需 Node/pnpm

## 2. 该特性做了什么

把 028 轨迹只读陈列升级为可回放：Stage 1 前端纯投影 MVP——跨轮时间轴、跳转到某轮查看当时上下文、步骤下钻（输入/输出/耗时），零后端改动起步；Stage 2 真回放后置。

关键功能需求（FR 摘要）：
- FR-001：轨迹 tab MUST 提供跨轮时间轴：每个 assistant round 一个锚点，含轮次号与时间，锚点数量 = 轮数，不渲染非 assistant 消息。
- FR-002：用户 MUST 能通过时间轴跳转到任意轮次，并查看该轮完整上下文：输入（用户消息/上下文引用）、输出（`final_answer`）、工具调用、知识命中。
- FR-003：用户 MUST 能对任一步骤（item）下钻，查看其输入、输出与耗时；耗时格式化与运行中实时滚动 MUST 复用 `domain/runTiming.ts` 既有口径。
- FR-004：下钻面板的成本行 MUST 降权展示：事件流含成本数据才渲染，否则不渲染且 MUST NOT 伪造数值（035 未落地时的既定行为）。
- FR-005：轨迹 tab MUST 在会话生成过程中实时更新（新轮次/步骤即时出现），且用户的跳转/下钻操作 MUST NOT 中断流式生成（延续 028 FR-006/FR-007）。

关键验收点（Success Criteria）：
- SC-001: 任一会话可在轨迹 tab 内跳转到任意轮次并看到当轮完整上下文（输入/输出/工具调用/知识命中），跳转响应为纯前端计算、无网络请求。
- SC-002: 每个步骤可下钻看到输入/输出/耗时；成本行仅在数据存在时出现（老会话零成本行）。
- SC-003: 028 既有对话 tab 零回归：`ChatWindow.vue` 零 diff，`pnpm test` 全绿。
- SC-004: `vue-tsc` + `vite build`（user-web）通过。

## 3. 如何启用

无显式开关，随代码落地生效；纯前端投影 MVP（Stage 1），跳转/下钻为纯前端计算、无网络请求；Stage 2 真回放（状态快照序列重演）后置。

## 4. 如何验证

### 4.1 自动化测试（首选）

逐服务运行下列实测测试文件（INDEX 记录全绿）：


**user-web（前端）**：
```bash
cd apps/user-web && pnpm test session-replay.test.ts
```

## 5. 注意事项

- 标准深度审计（2026-11-04）确认本特性 `tasks.md` 已 100% 勾选、代码已落地；测试以 INDEX 记录的全绿数为准，**发布前仍建议 CI 跑一次对应服务全量 pytest 对齐计数**。
- 跨特性依赖已在 spec「跨特性关系 / 判定口径补充」节声明（如 036→001/032、037→016/018/036、041→018/034、042→020/008、046→035/042），启用时注意相关特性就绪状态。
