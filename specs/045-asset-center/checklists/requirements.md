# Requirements Quality Checklist: 045 asset-center

> 质量门禁（/speckit-checklist）。勾选为已核验。

## 完整性（Completeness）

- [x] spec 含 User Scenarios / Requirements / Success Criteria / Assumptions 四大必选章节。
- [x] 每个 User Story 有 AC（AC1–AC5）。
- [x] FR 编号连续（FR-1 ~ FR-15），覆盖方案 §3 FR-1 ~ FR-13 并扩展。
- [x] Key Entities 列出五域数据模型与字段。
- [x] Edge Cases 覆盖：capability_asset 无评级 / 未上架 / 0 申领 / 未发布技能 / 非 active 能力。
- [ ] tasks.md 覆盖全部 FR（实施时逐项勾）。
- [ ] 后端接口有单测覆盖（实施时勾）。

## 清晰度（Clarity）

- [x] FR 每条单一职责，可测试。
- [x] 统一坐标 `(asset_type, asset_key)` 定义明确：技能=skills._id；能力=capability_assets.asset_id。
- [x] 类型下拉 4 项与 capability_asset kind 映射关系明确。
- [x] 缺失评级容忍口径明确（capability_asset 不在 036 ASSET_TYPES）。
- [x] 空状态与错误状态区分明确。

## 一致性（Consistency）

- [x] 与 018（capability_assets 集合 / registry）命名一致。
- [x] 与 036（trust_ratings / ASSET_TYPES）口径一致，不越界改评级模型。
- [x] 与 037（portal_listings / portal_requests / 状态机）口径一致，不改状态机。
- [x] 与 001（permission_grants / grantCount 同源）口径一致。
- [x] 路由路径与 admin-api `/api/v1` 前缀一致。
- [x] 前端 API 层与既有 `apiClient` 约定一致。

## Notes

- 本特性跨 018/036/037/001 四特性，仅加枢纽 + 互链 + 一个只读接口，不改任一被依赖方的核心逻辑。
- capability_asset 评级缺失是 036 既有约束（`ASSET_TYPES` 不含 `capability_asset`），方案 §10.2 已定为容忍，本 checklist 不要求扩展 036。

## 评审结论

- [x] agent 自审通过（2026-10-29）：spec / plan / tasks 三件齐全，口径与四特性一致，无遗漏必选章节。
