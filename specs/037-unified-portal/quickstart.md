# Quickstart: 应用门户 (037)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md) | [checklists/requirements.md](./checklists/requirements.md)

本文件说明如何**启用并验证** 应用门户（037）。

---

## 1. 前置

- 相关服务已部署：admin-api, chat-api, user-web（视特性所属服务而定）
- MongoDB 可用（或 PanWeiDB 可选后端；`MOGO_DATA_BACKEND` 未设置即 MongoDB，行为不变）
- 后端测试需 Python 3.10+ 与对应服务 venv；前端测试需 Node/pnpm

## 2. 该特性做了什么

在 user-web 内新增「应用门户」：员工浏览已上架 Agent/Skill 目录→自助申领→走 001 审批流→开通即授予访问权（回收即失效），让已上架资产找得到、申得到、批得完、用得上，全程审计。

关键功能需求（FR 摘要）：
- FR-001：user-web MUST 提供「应用门户」页（目录/详情/我的申领三个视图），承载于既有 user-web SPA；**不做 H5/App/桌面端**（ADR-7）。
- FR-002：chat-api MUST 提供门户目录 API（列表/分类/搜索/详情），数据源 = `portal_listings`（上架标记）+ `skills` 集合 + `capability_assets` 集合（016/018 治理数据），按 end_user 会话租户隔离。
- FR-003：目录 MUST 仅返回已上架且 018 状态 active 的资产；上架/下架与状态变更 MUST 即时反映（无缓存延迟）。
- FR-004：资产详情 MUST 包含名称、描述、分类、owner、效果分摘要（016）；036 就绪后 MUST 追加评级字段，036 未就绪时该字段 MUST 可缺席（前端容错）。
- FR-005：登录员工 MUST 能对未开通资产发起自助申领，生成申领单（`portal_requests`：requester/asset/reason/status/applied_at）。

关键验收点（Success Criteria）：
- SC-001: 员工从「浏览目录 → 申领 → 审批 → 开通 → 调用」全链路 E2E 跑通，开通后零额外配置即可使用（user-web 与 013 IM 入口双验证）。
- SC-002: 回收后该员工下次调用被 001 门禁拒绝（fail-closed），授权移除即时生效（`permission_grants` 无缓存语义，下—次调用即验）。
- SC-003: 申领/审批/开通/回收/上架/下架操作 100% 有 022 审计事件可回查。
- SC-004: 029 SSO 免登用户进入 user-web 即可见门户目录（全程无二次登录）。

## 3. 如何启用

无单独开关；目录仅返回已上架且 018 `active` 的资产；036 评级字段在 036 就绪后自动出现（读到 `trust_ratings` 记录则追加，无记录则缺席，前端容错），两特性互不阻塞。

## 4. 如何验证

### 4.1 自动化测试（首选）

逐服务运行下列实测测试文件（INDEX 记录全绿）：


**admin-api（后端）**：
```bash
cd services/admin-api && python -m pytest services/admin-api/tests/test_portal_admin.py -q
```

**chat-api（后端）**：
```bash
cd services/chat-api && python -m pytest services/chat-api/tests/test_portal_requests.py -q
```

**user-web（前端）**：
```bash
cd apps/user-web && pnpm test portal-sso-receiver.test.ts
```

## 5. 注意事项

- 标准深度审计（2026-11-04）确认本特性 `tasks.md` 已 100% 勾选、代码已落地；测试以 INDEX 记录的全绿数为准，**发布前仍建议 CI 跑一次对应服务全量 pytest 对齐计数**。
- 跨特性依赖已在 spec「跨特性关系 / 判定口径补充」节声明（如 036→001/032、037→016/018/036、041→018/034、042→020/008、046→035/042），启用时注意相关特性就绪状态。
