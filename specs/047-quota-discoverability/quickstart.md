# Quickstart: 配额可发现性 (047)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md) | [checklists/requirements.md](./checklists/requirements.md)

本文件说明如何**启用并验证** 配额可发现性（047）。

---

## 1. 前置

- 相关服务已部署：admin-web, admin-api（视特性所属服务而定）
- MongoDB 可用（或 PanWeiDB 可选后端；`MOGO_DATA_BACKEND` 未设置即 MongoDB，行为不变）
- 后端测试需 Python 3.10+ 与对应服务 venv；前端测试需 Node/pnpm

## 2. 该特性做了什么

让 042 已实现的部门/项目额度“找得到、配得动”：新增 admin-web 独立菜单「项目管理」(`/projects`)、修 `?open=quota` 深链、驾驶舱补「配额异常」卡片、对外文案“团队”→“部门”（标识符不变）。

关键功能需求（FR 摘要）：
- FR-001：admin-web MUST 新增独立菜单「项目管理」（路由 `/projects`），含项目列表（只读）、按项目的用量/成本、项目层额度配置；MUST NOT 提供"新建项目"或"编辑成员"入口（项目由员工在自己机器上创建）。
- FR-002：`?open=quota` MUST 落在项目配额视图；新增 `?open=tenant` MUST 落在租户额度；模型中心/驾驶舱的"去配置" MUST 按告警的 `scope_type` 分流。
- FR-003：零项目时 MUST 显示引导文案与跳转链接（指向 user-web 的项目创建入口），MUST NOT 显示空表格。
- FR-004：驾驶舱 MUST 新增「配额异常」卡片，消费 `/overview` 的 `quotaAnomalies`；`available = false` 时 MUST 显示 `reason`，MUST NOT 渲染 0 条。
- FR-005：「流量分配」页的原「团队 / 项目额度」按钮 MUST 改为跳转项目管理页；租户额度弹窗 MUST 保留可用。

关键验收点（Success Criteria）：
- SC-001: 从侧边栏进入项目配额的点击次数 = 1（现状 3）。
- SC-002: 从任意告警点"去配置"，落在正确层视图的比例 = 100%（现状 0%，全部落租户额度）。
- SC-003: 驾驶舱可见配额异常；`available = false` 时不出现 `0` 值渲染。
- SC-004: `apps/admin-web/src` 与 `services/` 的对外文案中"团队"零残留（grep 断言，标识符白名单见 042 `spec.md` 顶部对照表）。

## 3. 如何启用

无单独开关；admin-web 新增「项目管理」菜单（`/projects`）与驾驶舱「配额异常」卡片；以 `vue-tsc`/`pnpm build` + SC 手工核验（侧边栏进入项目配额点击次数=1、告警“去配置”100% 落正确层、对外文案 grep 断言“团队”零残留、标识符 `scope_type=team` 等不变）。

## 4. 如何验证

### 4.1 验证

本特性以 **admin-web 前端为主**，无独立命中单测文件；验证方式：

```bash
cd apps/admin-web && pnpm build && pnpm vue-tsc --noEmit
```

并按 §2 关键验收点（SC）做手工 UI 核验：侧边栏进入项目配额点击次数=1、任意告警点"去配置"100% 落正确层视图、对外文案 grep 断言"团队"零残留且标识符（`scope_type=team` 等）不变。

## 5. 注意事项

- 标准深度审计（2026-11-04）确认本特性 `tasks.md` 已 100% 勾选、代码已落地；测试以 INDEX 记录的全绿数为准，**发布前仍建议 CI 跑一次对应服务全量 pytest 对齐计数**。
- 跨特性依赖已在 spec「跨特性关系 / 判定口径补充」节声明（如 036→001/032、037→016/018/036、041→018/034、042→020/008、046→035/042），启用时注意相关特性就绪状态。
