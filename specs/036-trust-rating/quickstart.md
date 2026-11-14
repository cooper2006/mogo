# Quickstart: 资产可信评级 (036)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md) | [checklists/requirements.md](./checklists/requirements.md)

本文件说明如何**启用并验证** 资产可信评级（036）。

---

## 1. 前置

- 相关服务已部署：admin-api（视特性所属服务而定）
- MongoDB 可用（或 PanWeiDB 可选后端；`MOGO_DATA_BACKEND` 未设置即 MongoDB，行为不变）
- 后端测试需 Python 3.10+ 与对应服务 venv；前端测试需 Node/pnpm

## 2. 该特性做了什么

给资产（Agent/Skill/工作流）打 L1–L4 可信评级并与权限强绑定：L1 仅创建者可用、L2 输出需人审、L3 可接正式业务流、L4 含写操作需双人复核；连续 3 周不达标自动降级并收缩权限。

关键功能需求（FR 摘要）：
- FR-001：系统 MUST 支持资产可信评级四档 `L1|L2|L3|L4`，语义为：L1 实验级（仅创建者本人可用）、L2 辅助级（输出必须人审后采用）、L3 生产级（可接入正式业务流）、L4 关键级（含写操作需双人复核）；评级作用于**资产级**（`asset_type ∈ {skill, agent, w
- FR-002：新注册/新发现的资产 MUST 默认 L1；除显式升级流程外，任何路径（含批量导入、同步、内部服务）不得直接写入 L2+。
- FR-003：评级 MUST 持久化于 `trust_ratings` 集合（键 `tenant_id + asset_type + asset_key`，含 `level`/`below_streak_days`/`updated_by`/`updated_at`/`last_evidence`），与 `cap
- FR-004：系统 MUST 提供评级管理 API（查询/筛选/详情/变更/开关配置），鉴权走 001 权限码模型：读 `trust:read`、写 `trust:manage`，未授权 fail-closed（403）。
- FR-005：升级 MUST 由资产 owner 或持 `trust:manage` 的管理员发起；L2→L3、L3→L4 MUST 校验质量达标证据（首期 = 016 效果分 ≥ 阈值；032 就绪后切换为 032 评测结果，切换可配置且留审计）。

关键验收点（Success Criteria）：
- SC-001: 新资产 100% 默认 L1；测试证明不存在绕过升级流程获得 L2+ 的路径（含批量/同步/内部服务写入）。
- SC-002: L2 资产以 L4+ 自主级发起的调用 100% 被门禁按 L2 上限裁定（单测 + 集成测试双重证明）。
- SC-003: L4 资产写操作在仅一名审批人批准时 100% 被拒（fail-closed），双人不同批准后才执行；001 既有单人审批用例零回归。
- SC-004: 连续 21 天不达标资产 100% 触发自动降级 + 权限收缩 + 审计；租户开关关闭时 0 触发。

## 3. 如何启用

自动降级开关**默认开启**、租户可配（关闭需管理员操作并留审计）；评级查询/变更走 001 权限码 `trust:read` / `trust:manage`，未授权 fail-closed（403）。

## 4. 如何验证

### 4.1 自动化测试（首选）

逐服务运行下列实测测试文件（INDEX 记录全绿）：


**admin-api（后端）**：
```bash
cd services/admin-api && python -m pytest services/admin-api/tests/test_trust_rating.py services/admin-api/tests/test_skill_l1_visibility.py -q
```

## 5. 注意事项

- 标准深度审计（2026-11-04）确认本特性 `tasks.md` 已 100% 勾选、代码已落地；测试以 INDEX 记录的全绿数为准，**发布前仍建议 CI 跑一次对应服务全量 pytest 对齐计数**。
- 跨特性依赖已在 spec「跨特性关系 / 判定口径补充」节声明（如 036→001/032、037→016/018/036、041→018/034、042→020/008、046→035/042），启用时注意相关特性就绪状态。
