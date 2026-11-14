# Quickstart: 资产中心 (045)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md) | [checklists/requirements.md](./checklists/requirements.md)

本文件说明如何**启用并验证** 资产中心（045）。

---

## 1. 前置

- 相关服务已部署：admin-api（视特性所属服务而定）
- MongoDB 可用（或 PanWeiDB 可选后端；`MOGO_DATA_BACKEND` 未设置即 MongoDB，行为不变）
- 后端测试需 Python 3.10+ 与对应服务 venv；前端测试需 Node/pnpm

## 2. 该特性做了什么

把技能/评级/门户上架/门户审批/资产使用五个割裂功能点，用一个资产中心枢纽页 + 四类资产统一坐标 `(asset_type, asset_key)` 串成生命周期；后端只补一个能力资产只读列表接口。

关键功能需求（FR 摘要）：

关键验收点（Success Criteria）：
- 资产中心页在 1000 资产规模下首屏加载 < 2s（4 个接口并发，后端 `capabilities/list` 索引命中）。
- 五块互链全部可达：技能页评级徽标 → 评级页定位；评级页 → 门户上架/审批；门户上架 → 资产中心；门户审批 → 资产中心；资产中心 → 四块。
- capability_asset 评级缺失时资产中心不阻塞（"未评级"占位）。
- 后端新增接口有单测覆盖（admin JWT 鉴权 / 列表返回 / kind·state 过滤）。

## 3. 如何启用

无显式开关，随代码落地生效；后端仅新增 `GET /api/v1/capabilities/list` 只读列表接口，前端 join 五块功能点。

## 4. 如何验证

### 4.1 自动化测试（首选）

逐服务运行下列实测测试文件（INDEX 记录全绿）：


**admin-api（后端）**：
```bash
cd services/admin-api && python -m pytest services/admin-api/tests/test_capability_assets_admin.py -q
```

## 5. 注意事项

- 标准深度审计（2026-11-04）确认本特性 `tasks.md` 已 100% 勾选、代码已落地；测试以 INDEX 记录的全绿数为准，**发布前仍建议 CI 跑一次对应服务全量 pytest 对齐计数**。
- 跨特性依赖已在 spec「跨特性关系 / 判定口径补充」节声明（如 036→001/032、037→016/018/036、041→018/034、042→020/008、046→035/042），启用时注意相关特性就绪状态。
