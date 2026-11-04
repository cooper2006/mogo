# Quickstart: 业务线维度删除 (048)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md) | [checklists/requirements.md](./checklists/requirements.md)

本文件说明如何**启用并验证** 业务线维度删除（048）。

---

## 1. 前置

- 相关服务已部署：admin-api, chat-api（视特性所属服务而定）
- MongoDB 可用（或 PanWeiDB 可选后端；`MOGO_DATA_BACKEND` 未设置即 MongoDB，行为不变）
- 后端测试需 Python 3.10+ 与对应服务 venv；前端测试需 Node/pnpm

## 2. 该特性做了什么

删除无写方且必然产出单桶假数据的“业务线”维度：后端删 `_resolve_business_line` 与 `businessLineAttribution`、前端删标签/类型、测试同步删除断言，成本段 6 段→5 段，全仓 `businessLine`/`is_business_line` 零命中。

关键功能需求（FR 摘要）：
- FR-001：`dashboard.py` MUST 删除 `_resolve_business_line()` 整个函数（`:739-763`）。
- FR-002：`_resolve_org_attribution()` MUST 删除 `business_line_map` 相关分支，**保留部门归集部分不变**（`:765-812`）。
- FR-003：`_attribution_dimensions()` MUST 不再构造业务线段，响应 MUST NOT 含 `businessLineAttribution` 键（`:828-880` 的返回字典）。
- FR-004：`DashboardPage.vue` MUST 删除维度标签 `business_line: '业务线'`（`:748`）、来源数组中的 `['business_line', section.businessLineAttribution]`（`:759`）、类型定义 `businessLineA
- FR-005：测试 MUST 同步删除业务线相关断言与用例（`tests/test_cost_attribution_035.py:158/190-191/202-215`），其余五段断言 MUST 保留并通过。

关键验收点（Success Criteria）：
- SC-001: 驾驶舱成本段维度数 = 5（租户 / 用户 / 部门 / Agent / 项目）。
- SC-002: `/overview` 响应中 `businessLineAttribution` 键不存在（`"businessLineAttribution" in resp` 为 False）。
- SC-003: 全仓 `grep -rn "is_business_line\|businessLine" services/ apps/` = 0 命中。
- SC-004: 成本归集相关测试全绿；`reconciles` 在对账用例中为 `True`。

## 3. 如何启用

无显式开关，随代码落地生效；仅删除业务线段与 `businessLineAttribution` 键，不引入 `is_business_line`，不保留占位注释。

## 4. 如何验证

### 4.1 自动化测试（首选）

逐服务运行下列实测测试文件（INDEX 记录全绿）：


**admin-api（后端）**：
```bash
cd services/admin-api && python -m pytest services/admin-api/tests/test_cost_attribution_035.py services/admin-api/tests/test_dashboard_selfcheck.py -q
```

**chat-api（后端）**：
```bash
cd services/chat-api && python -m pytest services/chat-api/tests/llm/test_cost_attribution_035.py -q
```

## 5. 注意事项

- 标准深度审计（2026-11-04）确认本特性 `tasks.md` 已 100% 勾选、代码已落地；测试以 INDEX 记录的全绿数为准，**发布前仍建议 CI 跑一次对应服务全量 pytest 对齐计数**。
- 跨特性依赖已在 spec「跨特性关系 / 判定口径补充」节声明（如 036→001/032、037→016/018/036、041→018/034、042→020/008、046→035/042），启用时注意相关特性就绪状态。
