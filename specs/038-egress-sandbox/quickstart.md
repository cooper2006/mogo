# Quickstart: 出站白名单沙箱 (038)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md) | [checklists/requirements.md](./checklists/requirements.md)

本文件说明如何**启用并验证** 出站白名单沙箱（038）。

---

## 1. 前置

- 相关服务已部署：admin-api, chat-api（视特性所属服务而定）
- MongoDB 可用（或 PanWeiDB 可选后端；`MOGO_DATA_BACKEND` 未设置即 MongoDB，行为不变）
- 后端测试需 Python 3.10+ 与对应服务 venv；前端测试需 Node/pnpm

## 2. 该特性做了什么

把脚本沙箱“网络默认拒绝”语义提升为 HTTP 工具与浏览器 Agent 两条出站路径的统一白名单管控（平台/租户/工具三层并集，默认拒绝 fail-closed），防重定向逃逸与内网/IP 字面量访问。

关键功能需求（FR 摘要）：
- FR-001：系统 MUST 提供出站白名单配置，支持三层：平台默认（`scope=platform`）、租户级（`scope=tenant`）、工具例外（`scope=tool`，绑定 `tool_id`）；三层为**并集语义**——任一层命中即放行，无任何命中即拒绝。
- FR-002：HTTP/MCP 工具调用 MUST 在真实执行前（009 PreToolUse 求值点，`services/chat-api/app/enterprise_capabilities/tools/service.py:489-494` 同一位置）过出站检查；未命中 MUST 拒绝且不得向外部发出真实
- FR-003：浏览器 Agent MUST 在 `browser_task` 入口（`services/chat-api/app/enterprise_capabilities/browser/service.py:35`）对可解析的 `target_url` 过出站检查；未命中 MUST 拒绝执行。
- FR-004：浏览器 Agent 重定向 MUST 以最终落地 URL（navigate action contract 的 `final_url`）判定；最终落地域未命中白名单时该次导航 MUST 记失败并审计（防重定向逃逸）。
- FR-005：默认策略 MUST 为拒绝；白名单为空、URL 归一化失败、判定服务异常/超时、存储不可用，一律 MUST fail-closed 拒绝，**不得提供"放行"配置项**（与 001 R4 红线恒拒同语义，`services/admin-api/app/governance/risk.py:117`）

关键验收点（Success Criteria）：
- SC-001: 未命中白名单的出站调用 100% 被拒（HTTP 工具与浏览器 Agent 两路径），且拒绝 100% 可在审计检索到（含域名/租户/工具/原因）。
- SC-002: 白名单配置保存后，下一调用即按新配置求值（热更新），全程无服务重启；管理员自助放行一个新域名的操作步数 ≤ 3（打开页 → 加一行 → 保存）。
- SC-003: 同一域名在 HTTP 工具与浏览器 Agent 两条路径下判定结果 100% 一致（共用 `EgressGuard`）。
- SC-004: 脚本沙箱既有行为回归 0 破坏（`executor.py` 现有测试全绿：隔离/限额/网络拒绝三项不回退）。

## 3. 如何启用

默认拒绝（**fail-closed**），**不提供“放行”总开关**。上线初期由平台管理员在 `egress_allowlist` 集合预写必需域名（模型/检索供应商等）；白名单为空则全部出站拒绝。

## 4. 如何验证

### 4.1 自动化测试（首选）

逐服务运行下列实测测试文件（INDEX 记录全绿）：


**admin-api（后端）**：
```bash
cd services/admin-api && python -m pytest services/admin-api/tests/test_egress_allowlist.py -q
```

**chat-api（后端）**：
```bash
cd services/chat-api && python -m pytest services/chat-api/tests/test_egress_guard.py -q
```

## 5. 注意事项

- 标准深度审计（2026-11-04）确认本特性 `tasks.md` 已 100% 勾选、代码已落地；测试以 INDEX 记录的全绿数为准，**发布前仍建议 CI 跑一次对应服务全量 pytest 对齐计数**。
- 跨特性依赖已在 spec「跨特性关系 / 判定口径补充」节声明（如 036→001/032、037→016/018/036、041→018/034、042→020/008、046→035/042），启用时注意相关特性就绪状态。
