# Quickstart: 可视化编排画布 (039)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md) | [checklists/requirements.md](./checklists/requirements.md)

本文件说明如何**启用并验证** 可视化编排画布（039）。

---

## 1. 前置

- 相关服务已部署：chat-api（视特性所属服务而定）
- MongoDB 可用（或 PanWeiDB 可选后端；`MOGO_DATA_BACKEND` 未设置即 MongoDB，行为不变）
- 后端测试需 Python 3.10+ 与对应服务 venv；前端测试需 Node/pnpm

## 2. 该特性做了什么

给 010 DAG 引擎补前端可视化画布：YAML 为权威定义、画布为投影，画布 JSON ↔ YAML 双向序列化作为唯一转换层，保存产物经 010 既有持久化通道且可被引擎真实执行。

关键功能需求（FR 摘要）：
- FR-001：系统 MUST 在 user-web 提供可视化编排画布页面（vue-flow）：节点增删、拖拽布局、连线定义依赖、缩放与概览。
- FR-002：系统 MUST 提供画布 JSON ↔ 010 YAML 的双向序列化/反序列化模块，作为**唯一转换层**；MUST NOT 新增第三种编排定义格式。
- FR-003：画布保存 MUST 走 010 既有持久化通道（`dag_definitions` 集合，`orchestration/store.py`），保存产物 MUST 能被 `load_orchestration_document` 原样装载。
- FR-004：画布搭建的流程 MUST 可被 010 引擎真实执行（同一 YAML，引擎入口不变）。
- FR-005：手工编写的 010 YAML MUST 可在画布打开，往返后拓扑信息（节点/边/模式/条件/重试）零丢失；节点位置信息（`layout`）容忍丢失。

关键验收点（Success Criteria）：
- SC-001: 画布搭建的流程保存后可被 010 引擎真实执行——E2E 中画布产物与手写 YAML 产物经同一引擎执行结果一致（顺序/并行/条件跳过/产出传递）。
- SC-002: 手工 YAML → 画布 → YAML 往返，拓扑信息保留率 100%（节点/边/模式/条件/重试；位置可丢）。
- SC-003: 画布环检测与引擎侧一致——同一含环图，画布拒绝保存的错误信息与 `topo.py` 抛出的环路径节点序列相同。
- SC-004: 010 引擎既有测试回归 0 破坏（orchestration 全模块测试全绿；`competitor_deep_dive` 案例装载/执行不变）。

## 3. 如何启用

无显式开关，随代码落地生效；**YAML 为权威定义**，画布为投影，保存产物经 010 既有持久化通道（`dag_definitions`）。

## 4. 如何验证

### 4.1 自动化测试（首选）

逐服务运行下列实测测试文件（INDEX 记录全绿）：


**chat-api（后端）**：
```bash
cd services/chat-api && python -m pytest services/chat-api/tests/orchestration/test_orchestration_canvas_api.py services/chat-api/tests/orchestration/test_orchestration_canvas_mongo_e2e.py -q
```

## 5. 注意事项

- 标准深度审计（2026-11-04）确认本特性 `tasks.md` 已 100% 勾选、代码已落地；测试以 INDEX 记录的全绿数为准，**发布前仍建议 CI 跑一次对应服务全量 pytest 对齐计数**。
- 跨特性依赖已在 spec「跨特性关系 / 判定口径补充」节声明（如 036→001/032、037→016/018/036、041→018/034、042→020/008、046→035/042），启用时注意相关特性就绪状态。
