# Tasks: 业务线维度删除

**Input**: Design documents from `/specs/048-business-line-removal/`

**Prerequisites**: plan.md (required), spec.md (required)；035 文档侧已于 2026-10-30 改完

**Tests**: admin-api pytest（成本归集）+ 前端 SFC 编译。**删除型改动，测试是"删对没删错"的证据**，不可省。

**Organization**: 两个 Phase（删除 / 验证与收尾）；T001 起连续编号，全部 `- [ ]`。

## Phase 1: 删除

- [x] T001 基线：`grep -rn "business_line\|businessLine" services/ apps/` 记录全部命中（预期：`dashboard.py` 3 处 + `DashboardPage.vue` 3 处 + 测试 4 处），产出清单到本文件末尾
- [x] T002 `services/admin-api/app/api/routes/dashboard.py`：删除 `_resolve_business_line()` 整个函数（`:739-763`，FR-001）
- [x] T003 `dashboard.py`：`_resolve_org_attribution()` 删除 `business_line_map` 分支，**部门归集部分一行不动**（`:765-812`，FR-002）
- [x] T004 `dashboard.py`：`_attribution_dimensions()` 删除 `business_line = _build_attribution(...)` 整块与返回字典里的 `"businessLineAttribution"` 键（`:828-880`，FR-003）
- [x] T005 [P] `apps/admin-web/src/views/dashboard/DashboardPage.vue`：删除标签 `business_line: '业务线'`（`:748`）、来源数组项（`:759`）、类型定义（`:421`）（FR-004）
- [x] T006 [P] `services/admin-api/tests/test_cost_attribution_035.py`：删除业务线相关断言与用例（`:158/190-191/202-215`），**保留并确保五段断言通过**（FR-005）
- [x] T007 复核：`grep -rn "is_business_line" services/` 应 0 命中；确认没有残留的"待补数据源"注释（FR-006）

---

## Phase 2: 验证与收尾

- [x] T008 `pytest services/admin-api/tests/test_cost_attribution_035.py` 全绿；`reconciles` 用例为 `True`（SC-004）
- [x] T009 [P] 构造一次 `/overview` 请求，断言响应中**不存在** `businessLineAttribution` 键（不是空对象），且维度数为 5（SC-001/SC-002）
- [x] T010 [P] `node scripts/check_sfc.mjs apps/admin-web/src/views/dashboard/DashboardPage.vue` + `vue-tsc --noEmit` 0 错误；`grep -rn "业务线" apps/admin-web/src` = 0（SC-005）
- [x] T011 全仓检索 `grep -rn "businessLine\|is_business_line" services/ apps/` = 0 命中（SC-003）
- [x] T012 [P] `specs/035-cost-attribution/review-...md` §4.3：把"代码未落地"标记更新为"已完成（2026-XX-XX）"，**保留删除清单原文作历史记录**（FR-007）
- [x] T013 [P] `specs/INDEX.md` 048 行更新；035 `spec.md` 的 R-1/R-2 作废说明保持不动（已声明"后续不得重新引入"）

---

## Dependencies & Execution Order

```
T001（基线）
  └─ T002 → T003 → T004（同一文件，顺序执行，避免冲突）
       ├─ T005（前端，可并行）
       └─ T006（测试，可并行）
            └─ T007 复核 → Phase 2 验证
T008–T011 ── 验证，必须全绿
T012–T013 ── 文档收尾
```

- **T002–T004 必须顺序**：同一文件同一函数区，并行会冲突。
- **T005/T006 可并行**：不同文件。
- **与 046 T028/T029 同批提交**：两者都动 `_attribution_dimensions()` 与 `DashboardPage.vue` 的维度数组，分两次改同一块容易漏。

## 删除清单（T001 产出）

| 位置 | 行号（改前） | 内容 | 状态 |
|---|---|---|---|
| `services/admin-api/app/api/routes/dashboard.py` | :739-763 | `_resolve_business_line()` 整个函数 | ✅ 已删 |
| `dashboard.py` | :765-812 | `_resolve_org_attribution()` 的 `business_line_map` 分支（部门部分保留） | ✅ 已删；函数改名 `_resolve_department` |
| `dashboard.py` | :828-880 | `business_line = _build_attribution(...)` 整块 | ✅ 已删 |
| `dashboard.py` | :866 | 返回字典的 `"businessLineAttribution"` 键 | ✅ 已删 |
| `apps/admin-web/src/views/dashboard/DashboardPage.vue` | :748 | 标签 `business_line: '业务线'` | ✅ 已删 |
| `DashboardPage.vue` | :759 | 来源数组项 `['business_line', section.businessLineAttribution]` | ✅ 已删 |
| `DashboardPage.vue` | :421 | 类型定义 `businessLineAttribution: CostAttribution` | ✅ 已删 |
| `services/admin-api/tests/test_cost_attribution_035.py` | :158 | BLINE fixture（含 `is_business_line`） | ✅ 已删 |
| `test_cost_attribution_035.py` | :190-191 | 业务线断言块 | ✅ 已删 |
| `test_cost_attribution_035.py` | :202-215 | `test_business_line_uses_highest_is_business_line_ancestor` 整用例 | ✅ 已删 |
| `test_cost_attribution_035.py` | :230 | 维度循环里的 `businessLineAttribution` | ✅ 已删 |
| `test_cost_attribution_035.py` | :246 | empty-tenant 键元组里的 `businessLineAttribution` | ✅ 已删 |

## 验证结论

| 检查项 | 结果 |
|---|---|
| `pytest services/admin-api/tests/test_cost_attribution_035.py` | 7/7 pass |
| `/overview` 成本段维度数 | 5（department / agent / space / user / enterprise） |
| `businessLineAttribution` 是否存在 | **不存在**（非空对象，键已删除） |
| `reconciles` | `True` |
| `node scripts/check_sfc.mjs DashboardPage.vue` | 1/1 通过（3.4.38） |
| `grep -rn "业务线" apps/admin-web/src` | 0 命中 |
| 全仓 `grep -rn "businessLine\|is_business_line" services/ apps/` | 0 命中 |

## Notes

- 这是**删除**，不是重构：不顺手改其他维度的命名或结构
- 前端先发或同批发布；后端先发会让旧前端读 `undefined` 渲染空卡片
- 不引入 `is_business_line` 的替代字段（Non-Goal）
- 落地日期：2026-11-01；成本段 6 段 → 5 段（租户/用户/部门/Agent/项目），`reconciles=True`，全仓 `businessLine`/`is_business_line` 0 命中
- **与 046 T028/T029 同批提交**：两者都动 `_attribution_dimensions()` 与 `DashboardPage.vue` 维度数组，分两次改同一块容易漏

## Notes

- 这是**删除**，不是重构：不顺手改其他维度的命名或结构
- 前端先发或同批发布；后端先发会让旧前端读 `undefined` 渲染空卡片
- 不引入 `is_business_line` 的替代字段（Non-Goal）
