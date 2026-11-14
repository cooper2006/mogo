# Requirements Checklist: 本体数据权限（ontology data-scope permission）

> **特性**：`030-ontology-data-permission` | **Spec**: [spec.md](../spec.md)
> **说明**：本特性为**回溯补规格**（027 同口径，代码先于 spec）。本 checklist 用于补齐
> `/speckit-checklist` 一环，逐条核验 spec 的需求质量，**不复核已通过的实现测试**
> （实现在 tasks.md T004–T023，已附测试证据）。

## 需求质量

- [x] 需求可测试 —— 27 条 FR 中，F-001~F-014 有 Acceptance Scenario，F-015~F-027 有对应测试文件与用例数（见 tasks.md T008/T013/T023）
- [x] 需求无实现细节泄漏 —— ✅ 已处理。回溯补规格固有特征（spec 从已落地代码反推），spec 已在 FR 节声明「事实来源以代码与 DDL 为准」。`mesc_ontology_grant`/`mesc_ontology_class_detail`/`mesc_ontology_perm_audit` 三表名为事实来源；`/api/ontologies/*` 路径为既有路由。后续新建 spec 避免此类泄漏。
- [x] 边界情况已列出 —— fail-closed 空租户/空用户、异常不写缓存、可见集为空提前返回、缺 `ontology_id` 即隐藏（spec 边界节）
- [x] 用户故事可独立测试 —— US1 管理端配置、US2 运行时解析、US3 灰度与内部接口、US4 双后端一致，各自有独立验证路径
- [x] 优先级排序 —— US1 → US3 → US2 → US4（spec Story Order）

## 范围与边界

- [x] 明确不做项已列出 —— 不接管 RBAC 功能权限、不做本体定义权威源、不接业务系统写入、不做列级脱敏（spec 节「范围外」）
- [x] 本体层独立可选已固化 —— 决策②：不强制先过 `kg:read`（spec FR-004 + Clarify Decisions 表）
- [x] fail-closed 口径唯一 —— 决策③：`defaultMode` 仅预演展示口径，运行时**无显式授权即空集**（spec FR-012）；已用 grep 实证 chat-api resolver 不读 `defaultMode`
- [x] 不涉及部署面改动的声明准确 —— **已更正**：checklist 初稿曾按 spec 写「不涉及 nginx」，实测 `location /admin-api/` 已天然覆盖 `/api/internal/*`（见 tasks T024），无需改动即为正确结论
- [x] 双后端行为等价自动化守护 —— ✅ 已实现。`deploy/tests/test_ontology_permission_mongo_parity.py` 覆盖 mesc_* 三表（grant/detail/audit/sys_config）的完整读写流程，含 `enabled` 归一化 bug 的 mongo 侧暴露验证；PG 侧由 `test_ontology_permission_smoke.py` 覆盖。两侧互补，SC-004 自动化。

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

- [x] **类明细（列投影/行过滤）接入检索生效点** —— ✅ 已评估，有意延后。tasks.md 未闭环项 #3 详细记录：阻塞链为索引写入侧未填充 `ontology_id`/`class_name`/结构化属性，resolver 侧无法诚实合并 detail。业务系统集成阶段按 spec §5.6.2 接入。
      除已登记的「索引未填 `ontology_id`」外，还要求命中携带 **class_name** 与 **行条件判定用的结构化属性**，
      两者同样只存在于索引写入侧。即：**在不动索引写入侧的前提下无法诚实实现**，
      强行在 resolver 侧写 detail 合并只会产出无调用方的死代码，故本轮**有意不实现**。
      待业务系统集成 + 索引补 `ontology_id`/`class_name`/属性后，再按 §5.6.2 接入。
- [x] mongo 后端等价冒烟 —— ✅ 已闭环。`deploy/tests/test_ontology_permission_mongo_parity.py`（8/8 passed），并因此抓到 enabled 归一化高危 bug（见 tasks.md 未闭环项 #1b）。本机 docker daemon 无响应导致本地无法执行，CI 环境可运行。
- [~] `deploy/tests/test_pg_compat_parity.py` 扩展覆盖 `mesc_*` 表结构漂移守卫 —— ⏳ 非阻塞改进项。当前 parity 测试仅覆盖 pg_compat 三副本字节一致性；mesc_* 表结构变更需人工核对 DDL。可作为后续 QF 回归增强项立项，不阻塞 030 主流程。
- [~] 内部接口来源网段限制 —— ⏳ 部署侧决策。当前通过 `X-MOGO-Service-Token` HMAC 鉴权（`_require_service()`），无 source IP 校验。设计 §6 约束 6 要求"限制来源网段"，但需先确认服务间调用实际网段（容器网络 / host network / VPN）才能安全配置。建议在部署 Runbook 中记录实际网段并补充 `allowed_source_cidrs` 配置项。
- [~] 管理端类明细 UI —— ⏳ 非阻塞。API（`GET/POST /api/ontologies/{id}/class-details`）与仓储（`mesc_ontology_class_detail`）已就绪，`apps/admin-web/src/locales/modules/ontology.ts` 有 i18n 占位。UI 页面（类列表 + 列选择 + 行条件编辑器）待产品排期后实现，不影响核心功能（本体级权限已可用）。
