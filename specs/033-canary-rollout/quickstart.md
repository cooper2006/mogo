# Quickstart: 比例灰度 + 影子发布 (033)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md) | [checklists/requirements.md](./checklists/requirements.md)

本文件说明如何**启用并验证** 比例灰度 + 影子发布（033）。

---

## 1. 前置

- 相关服务已部署：admin-api, chat-api（视特性所属服务而定）
- MongoDB 可用（或 PanWeiDB 可选后端；`MOGO_DATA_BACKEND` 未设置即 MongoDB，行为不变）
- 后端测试需 Python 3.10+ 与对应服务 venv；前端测试需 Node/pnpm

## 2. 该特性做了什么

在 016 按租户 canary 之上增加按比例阶梯灰度（1%→10%→50%→100% 可配，达标自动推进）与影子发布（影子流量双跑只记录不返回），让 Agent/Skill 发布从粗粒度细化为可控渐进 + 零风险预跑，异常率超阈值自动回滚。

关键功能需求（FR 摘要）：
- FR-001：`Rollout` MUST 增加 `traffic_ratio`（0 < ratio ≤ 1）与阶梯字段（`ladder` / `current_step` / `ladder_history` / `shadow_enabled`）；既有 `target_tenants` / `state` /
- FR-002：灰度定位 MUST 支持 `target_tenants`、`traffic_ratio` 及两者叠加；两者皆空 = 100% 全量。
- FR-003：分流 MUST 按 `(tenant_id, user_id)` 确定性哈希取模实现，同一用户在整个灰度期内版本一致（粘滞）；MUST 为可单测的纯函数。
- FR-004：阶梯推进器 MUST 按默认 1%→10%→50%→100%（租户可配置）在当前档样本 ≥ `min_samples` 且异常率 ≤ `threshold` 时自动推进；样本不足 MUST NOT 推进。
- FR-005：阶梯当前档位与推进历史 MUST 落库（`skill_rollouts` 扩展字段），可查询。

关键验收点（Success Criteria）：
- SC-001: 契约测试：分流确定性（同一用户多次分配结果一致）且大样本下比例近似（偏差在统计容差内）；`target_tenants` 与 `traffic_ratio` 叠加语义正确。
- SC-002: 契约测试：阶梯按条件推进——样本不足停在当前档；达标推进 1%→10%→50%→100%；到 100% 稳定后置 `PROMOTED`；推进历史可查。
- SC-003: 契约测试：影子双跑下用户结果 100% 来自稳定版；`skill_shadow_runs` 有记录；影子执行失败不触发回滚、不影响用户请求。
- SC-004: 契约测试：错误率 >20% 且样本 ≥20 自动回滚触发；手动一键回滚一键完成；两者记录（前/后版本、原因）均可查。

## 3. 如何启用

在 admin-web 灰度配置页创建/查看灰度（租户 + 比例阶梯 + 影子开关）。**影子模式默认关闭**，需租户显式开启（承担双倍 LLM 调用成本）；比例阶梯默认四档可改。

## 4. 如何验证

### 4.1 自动化测试（首选）

逐服务运行下列实测测试文件（INDEX 记录全绿）：


**admin-api（后端）**：
```bash
cd services/admin-api && python -m pytest services/admin-api/tests/test_canary_ratio.py -q
```

**chat-api（后端）**：
```bash
cd services/chat-api && python -m pytest services/chat-api/tests/dsh_runtime/test_canary_shadow.py -q
```

## 5. 注意事项

- 标准深度审计（2026-11-04）确认本特性 `tasks.md` 已 100% 勾选、代码已落地；测试以 INDEX 记录的全绿数为准，**发布前仍建议 CI 跑一次对应服务全量 pytest 对齐计数**。
- 跨特性依赖已在 spec「跨特性关系 / 判定口径补充」节声明（如 036→001/032、037→016/018/036、041→018/034、042→020/008、046→035/042），启用时注意相关特性就绪状态。
