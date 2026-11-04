# Quickstart: 成本五段归集 (035)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md) | [checklists/requirements.md](./checklists/requirements.md)

本文件说明如何**启用并验证** 成本五段归集（035）。

---

## 1. 前置

- 相关服务已部署：admin-api, chat-api（视特性所属服务而定）
- MongoDB 可用（或 PanWeiDB 可选后端；`MOGO_DATA_BACKEND` 未设置即 MongoDB，行为不变）
- 后端测试需 Python 3.10+ 与对应服务 venv；前端测试需 Node/pnpm

## 2. 该特性做了什么

给 008 驾驶舱成本维补齐部门/Agent/项目三个归集维度，使成本覆盖租户/用户/部门/Agent/项目五段；核心是补数据源（`TokenUsageRecord` 增 `agent_id`/`project_id`、部门经 `end_user_org_relations` 反查）与接库函数（`attribute_cost`/`aggregate_usage`）。

关键功能需求（FR 摘要）：
- FR-001：`TokenUsageRecord`（`services/chat-api/app/token_usage/models.py`）MUST 新增 `agent_id`、`skill_id`、`project_id` 三个字段（默认空串），既有字段与默认值不变。~~原 `workspace_id` 字
- FR-002：埋点 MUST 落在 `services/chat-api/app/llm/instrumented_client.py::_submit_record` 的记录构造处：从 `output_spec`（含 `get_request_context()` 合并，`factory.py:72-76`）读
- FR-003：Agent 运行时调用链 MUST 把当前 Agent/Skill 标识传入请求上下文或 output_spec（或复用既有 Agent 执行处已设置的上下文键）；不新增独立埋点管道。
- FR-004：Agent 维度聚合 MUST 支持归属链路解析：Agent/Skill 经 018 能力资产注册表解析资产名（解析不到回落原始 ID），`skill_id` 随记录携带供链路还原。
- FR-005：`dashboard.py::_cost_section()` MUST 接入 `dashboard_metrics.attribute_cost`（admin-api 库函数）做部门/项目归集，接入等价于 `metering.aggregate_usage` 的多维聚合做 Agent 归集（adm

关键验收点（Success Criteria）：
- SC-001: 五段均可分组聚合——成本 section 返回租户/用户/部门/Agent/项目五个归集段（外加 008 既有模型分组），每维分桶合计与 `totalCost` 对账一致（`reconciles` 绿）。租户段恒为单桶（值 = `totalCost`），作为对账锚
- SC-002: 单次调用可下钻且含单条成本金额——下钻列表行与详情均含 `costUsd`（埋点值或定价兜底），且与汇总同源（汇总 1.2 时下钻合计 1.2，容差内）。
- SC-003: 对账自检保持绿——`reconciles` 在五段齐备/部分缺失/空租户三种场景下均为 True，既有 `test_dashboard_routes.py`/`test_dashboard_selfcheck.py` 相关用例全绿。
- SC-004: 空维度不伪造数值——无数据源维度 100% 返回 `available: False` + `reason`，响应中无该维度的 0 值分桶冒充（测试断言三种空场景）。业务线维度不得以任何形式回归（不返回空桶、不返回单桶"企业总部"）。

## 3. 如何启用

无显式开关，随代码落地生效；成本段自动多维度归集，缺失维度（无数据源）返回 `available:false` + `reason`，不伪造 0 值分桶。

## 4. 如何验证

### 4.1 自动化测试（首选）

逐服务运行下列实测测试文件（INDEX 记录全绿）：


**admin-api（后端）**：
```bash
cd services/admin-api && python -m pytest services/admin-api/tests/test_dashboard_routes.py services/admin-api/tests/test_dashboard_selfcheck.py services/admin-api/tests/test_dashboard_project_dimension.py services/admin-api/tests/test_cost_attribution_035.py -q
```

**chat-api（后端）**：
```bash
cd services/chat-api && python -m pytest services/chat-api/tests/llm/test_cost_attribution_035.py -q
```

## 5. 注意事项

- 标准深度审计（2026-11-04）确认本特性 `tasks.md` 已 100% 勾选、代码已落地；测试以 INDEX 记录的全绿数为准，**发布前仍建议 CI 跑一次对应服务全量 pytest 对齐计数**。
- 跨特性依赖已在 spec「跨特性关系 / 判定口径补充」节声明（如 036→001/032、037→016/018/036、041→018/034、042→020/008、046→035/042），启用时注意相关特性就绪状态。
