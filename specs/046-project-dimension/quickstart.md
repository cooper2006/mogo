# Quickstart: 项目维度统一 (046)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md) | [checklists/requirements.md](./checklists/requirements.md)

本文件说明如何**启用并验证** 项目维度统一（046）。

---

## 1. 前置

- 相关服务已部署：admin-api, chat-api（视特性所属服务而定）
- MongoDB 可用（或 PanWeiDB 可选后端；`MOGO_DATA_BACKEND` 未设置即 MongoDB，行为不变）
- 后端测试需 Python 3.10+ 与对应服务 venv；前端测试需 Node/pnpm

## 2. 该特性做了什么

把三套同名“项目”收敛为一套（项目=工作目录）：`desktop_projects`→`projects`、默认项目 “default”、`chat_sessions.project_id`、网关反查绑定、`project_id` 全量幂等回填、侧边栏与驾驶舱切读。

关键功能需求（FR 摘要）：
- FR-001：项目实体 MUST 唯一化为集合 `projects`（原 `desktop_projects` 改名，D6）；`_id` MUST 为 workspace id（客户端生成），默认项目为保留值 `"default"`（D2）。
- FR-002：`projects` MUST 记录 `tenant_id` / `user_id` / `title` / `worktree` / `status` / 时间戳；`status ∈ {active, archived}`；MUST 建索引 `{tenant_id, user_id, status
- FR-003：系统 MUST 为每个 `(tenant_id, user_id)` 幂等生成一条 `_id = "default"` 的默认项目（重复调用不产生第二条）；默认项目 MUST NOT 被归档或删除。
- FR-004：`chat_sessions` MUST 具备 `project_id` 字段；code 会话取绑定的 workspace id，web 会话取 `"default"`；**新会话 MUST NOT 留空**。
- FR-005：用量事实 MUST 以 `project_id` 归集（`TokenUsageRecord.workspace_id` 改名 `project_id`）；单次调用下钻 MUST 返回 `projectId`（原 `workspaceId`）。

关键验收点（Success Criteria）：
- SC-001: 存量会话 `project_id` 空值率 = 0（回填后按 `{project_id: null}` 或空串查询命中 0 条）。
- SC-002: 驾驶舱成本段「项目」分组 `available = true` 且分桶合计与 `totalCost` 对账一致；「未分配」分桶占比 < 5%（迁移窗口外的稳定态）。
- SC-003: 项目 CRUD 与侧边栏分组无回归——既有项目相关接口全部通过，`/projects` 路径与字段名不变。
- SC-004: 回填脚本幂等：连续执行两次，第二次写入 0 条。

## 3. 如何启用

无显式开关；默认项目 “default” 对每个 `(tenant_id, user_id)` 幂等生成；存量 `chat_sessions.project_id` 由幂等回填脚本补齐（执行前备份，连续执行两次写入 0 条）。

## 4. 如何验证

### 4.1 自动化测试（首选）

逐服务运行下列实测测试文件（INDEX 记录全绿）：


**admin-api（后端）**：
```bash
cd services/admin-api && python -m pytest services/admin-api/tests/test_dashboard_project_dimension.py -q
```

**chat-api（后端）**：
```bash
cd services/chat-api && python -m pytest services/chat-api/tests/test_backfill_project_id.py services/chat-api/tests/test_model_gateway_project_id.py services/chat-api/tests/test_project_attribution.py services/chat-api/tests/test_desktop_project_isolation.py -q
```

## 5. 注意事项

- 标准深度审计（2026-11-04）确认本特性 `tasks.md` 已 100% 勾选、代码已落地；测试以 INDEX 记录的全绿数为准，**发布前仍建议 CI 跑一次对应服务全量 pytest 对齐计数**。
- 跨特性依赖已在 spec「跨特性关系 / 判定口径补充」节声明（如 036→001/032、037→016/018/036、041→018/034、042→020/008、046→035/042），启用时注意相关特性就绪状态。
