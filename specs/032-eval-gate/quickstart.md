# Quickstart: 评测门禁 (032)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md) | [checklists/requirements.md](./checklists/requirements.md)

本文件说明如何**启用并验证** 评测门禁（032）。

---

## 1. 前置

- 相关服务已部署：admin-api, chat-api（视特性所属服务而定）
- MongoDB 可用（或 PanWeiDB 可选后端；`MOGO_DATA_BACKEND` 未设置即 MongoDB，行为不变）
- 后端测试需 Python 3.10+ 与对应服务 venv；前端测试需 Node/pnpm

## 2. 该特性做了什么

在 Skill 发布链路 `skill_lifecycle.publish()` 写版本快照前插入硬门禁：用租户按 Skill 维护的黄金测试集对待发布草稿做发布时点评测，以引用支撑率/拒答正确率/任务成功率三项指标对照阈值策略判定，不达标直接拒绝发布（fail-closed）并落审计——把资产腐化治理从事后降权前移为事前阻断。

关键功能需求（FR 摘要）：
- FR-001：系统 MUST 提供测试集 CRUD API，按 `(tenant_id, skill_id)` 隔离；用例 MUST 含 `input` / `expectations` / `expected_refs` / `expect_refusal`，可附 `agent_tag`。
- FR-002：测试集用例数 MUST 有上限（默认 50，可配），超限创建被拒（400）。
- FR-003：`skill_lifecycle.publish()` MUST 在 release 落库前调用评测门禁；不达标时直接拒绝且**不产生 release 记录**（skill 保持已发布态不变）。
- FR-004：评测执行器 MUST 经 chat-api 模型网关（`settings.backend_base_url` + `settings.backend_service_token`）执行用例，**复用 007 韧性**隔离重试与超时，不在 admin-api 重复实现重试逻辑。
- FR-005：系统 MUST 计算三项指标——引用支撑率、拒答正确率、任务成功率——由**确定性规则判定器**产出（引用存在性、拒答话术、期望要点匹配）。

关键验收点（Success Criteria）：
- SC-001: 构造低于阈值的 Skill → `publish()` 返回 4xx 阻断，`organization_skill_releases` 无新记录，`gate_events` 可查 `eval_gate.blocked` 事件及三项指标明细。
- SC-002: 全部达标的 Skill → `publish()` 正常生成 release，`gate_events` 可查 `eval_gate.passed` 事件。
- SC-003: 默认策略 fail-closed；租户修改阈值后判定行为随之变化；全系统无"关闭门禁"入口。
- SC-004: 三条 fail-closed 路径（无测试集 / 样本不足 <5 / LLM 不可用超时）均有单测覆盖且全部阻断。

## 3. 如何启用

默认开启且 **fail-closed**，**无整体关闭开关**。租户在 `skill_eval_policies` 集合配置阈值策略（默认含三项指标阈值、门禁启用）；门禁在 `skill_lifecycle.publish()` 落库前自动执行。

## 4. 如何验证

### 4.1 自动化测试（首选）

逐服务运行下列实测测试文件（INDEX 记录全绿）：


**admin-api（后端）**：
```bash
cd services/admin-api && python -m pytest services/admin-api/tests/test_eval_gate.py -q
```

**chat-api（后端）**：
```bash
cd services/chat-api && python -m pytest services/chat-api/tests/services/test_skill_lifecycle.py -q
```

## 5. 注意事项

- 标准深度审计（2026-11-04）确认本特性 `tasks.md` 已 100% 勾选、代码已落地；测试以 INDEX 记录的全绿数为准，**发布前仍建议 CI 跑一次对应服务全量 pytest 对齐计数**。
- 跨特性依赖已在 spec「跨特性关系 / 判定口径补充」节声明（如 036→001/032、037→016/018/036、041→018/034、042→020/008、046→035/042），启用时注意相关特性就绪状态。
