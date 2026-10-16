# Requirements Checklist: 本体数据权限（ontology data-scope permission）

> **特性**：`030-ontology-data-permission` | **Spec**: [spec.md](../spec.md)
> **说明**：本特性为**回溯补规格**（027 同口径，代码先于 spec）。本 checklist 用于补齐
> `/speckit-checklist` 一环，逐条核验 spec 的需求质量，**不复核已通过的实现测试**
> （实现在 tasks.md T004–T023，已附测试证据）。

## 需求质量

- [x] 需求可测试 —— 27 条 FR 中，F-001~F-014 有 Acceptance Scenario，F-015~F-027 有对应测试文件与用例数（见 tasks.md T008/T013/T023）
- [ ] 需求无实现细节泄漏 —— **未达标**：spec 的 FR/契约节直接引用了 `mesc_ontology_grant` 列名、`/api/ontologies/*` 路径与 `business_entity_index` 表名。回溯补规格的固有问题（spec 从已落地代码反推），已在该节声明「事实来源以代码与 DDL 为准」
- [x] 边界情况已列出 —— fail-closed 空租户/空用户、异常不写缓存、可见集为空提前返回、缺 `ontology_id` 即隐藏（spec 边界节）
- [x] 用户故事可独立测试 —— US1 管理端配置、US2 运行时解析、US3 灰度与内部接口、US4 双后端一致，各自有独立验证路径
- [x] 优先级排序 —— US1 → US3 → US2 → US4（spec Story Order）

## 范围与边界

- [x] 明确不做项已列出 —— 不接管 RBAC 功能权限、不做本体定义权威源、不接业务系统写入、不做列级脱敏（spec 节「范围外」）
- [x] 本体层独立可选已固化 —— 决策②：不强制先过 `kg:read`（spec FR-004 + Clarify Decisions 表）
- [x] fail-closed 口径唯一 —— 决策③：`defaultMode` 仅预演展示口径，运行时**无显式授权即空集**（spec FR-012）；已用 grep 实证 chat-api resolver 不读 `defaultMode`
- [x] 不涉及部署面改动的声明准确 —— **已更正**：checklist 初稿曾按 spec 写「不涉及 nginx」，实测 `location /admin-api/` 已天然覆盖 `/api/internal/*`（见 tasks T024），无需改动即为正确结论
- [ ] 双后端行为等价**未被自动化守护** —— PG 与 mongo 两侧字段对应关系靠人工对齐（`deploy/pg/ontology_permission.sql` ↔ `deploy/mongo/ontology_permission.js`），无 parity 测试。已有 `deploy/tests/test_pg_compat_parity.py` 但只覆盖 `pg_compat` 三副本，**不覆盖 mesc_***

## 可测性

- [x] SC-001（授权后立即可见）可验证 —— 冒烟 T023 已覆盖授予→回读→撤销
- [x] SC-002（未授权本体不可见）可验证 —— `test_semantic_search_ontology_filter.py` 缺键即隐藏
- [x] SC-003（异常时 fail-closed）可验证 —— resolver 异常→空集且不写缓存（T005）
- [x] SC-004（双后端同形）**仅人工验证** —— 本轮实测 PG 侧全流程；mongo 侧只建了集合与索引，未跑通 repository 读写（mongo 后端下 `MOGO_DATA_BACKEND=mongo` 未做等价冒烟）
- [x] SC-005（审计留痕）可验证 —— 配置变更落 `mesc_ontology_perm_audit`，运行时判定落 `gate_events`（不双写）

## 一致性

- [x] 与 `docs/ontology-permission-merge-plan.md` 决策①②③一致
- [x] 与 Constitution 原则 I（Specification-First）—— **已违背并如实标注**：本特性代码先于 spec，spec 的 Constitution Check 已标 ⚠️
- [x] 与 AGENTS.md 改动纪律一致 —— 未删除既有文件，改动集中在新增模块 + 必要生效点
- [x] 与用户明确暂缓项一致 —— 索引写入方不填 `ontology_id`（spec/tasks 均记录，未擅自接入）

## 待办（含本轮新增识别的阻塞链）

- [ ] **类明细（列投影/行过滤）接入检索生效点** —— 阻塞链已查清，**不是「后续改造」一句话能概括**：
      除已登记的「索引未填 `ontology_id`」外，还要求命中携带 **class_name** 与 **行条件判定用的结构化属性**，
      两者同样只存在于索引写入侧。即：**在不动索引写入侧的前提下无法诚实实现**，
      强行在 resolver 侧写 detail 合并只会产出无调用方的死代码，故本轮**有意不实现**。
      待业务系统集成 + 索引补 `ontology_id`/`class_name`/属性后，再按 §5.6.2 接入。
- [ ] mongo 后端等价冒烟 —— 在 `MOGO_DATA_BACKEND=mongo` 下跑通 repository 读写（SC-004 自动化）
- [ ] `deploy/tests/test_pg_compat_parity.py` 扩展覆盖 `mesc_*` 表结构漂移守卫
- [ ] 内部接口来源网段限制（部署侧，需先确认服务间调用实际网段）
- [ ] 管理端类明细 UI（当前 API/仓储已就绪，无界面入口）
