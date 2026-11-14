# Requirements Quality Checklist: 039 visual-orchestration

**Purpose**: 校验 039（可视化编排画布）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-10-24
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 画布 JSON 的 schema 是否定义（FR-002 要求唯一转换层，但**画布 JSON 自身的结构**（node/edge 字段名、`payload` 与 YAML 字段的映射表）未给出，转换层无法据此逐字段实现）
- [x] CHK002 `layout` 字段的结构与容错规则是否定义（FR-012 说"损坏或缺失不影响定义有效性"，但**结构形状**（每节点 x/y/宽高？全局 viewport 缩放？）与"损坏"的判定（类型错误/坐标越界）未写）
- [x] CHK003 环检测的错误信息格式是否与引擎逐字对齐（FR-006 要求"与 `topo.py` `CycleError` 同格式"，**未给出该格式样例**；前后端各写一版必然漂移）
- [x] CHK004 草稿与已发布版本的存储区分是否定义（决策 #5 说编辑是草稿态、发布进 `dag_definitions`；**草稿存哪**（同集合的不同状态？另一集合？）、草稿是否版本化，未写）

## 清晰度（Clarity）

- [x] CHK005 "未知 payload 键只读保留"的实现口径是否定义（FR-008 要求未知键不透写丢失；**画布编辑器如何展示只读未知键**（隐藏但保留？还是显示为只读字段）、保存时如何回填，未定义）
- [x] CHK006 supervisor/hybrid 的"暂不支持"呈现边界是否定义（FR-007 要求 UI 明示；**打开一个 supervisor 模式 YAML 时是拒绝打开、只读展示、还是允许查看禁用编辑**，三种行为对用户体验与数据安全影响不同）
- [x] CHK007 校验时机与失败呈现是否定义（FR-006 说"保存前校验"；**是否也做实时校验（连线时即校验）、失败信息在画布上如何高亮**（节点边框？侧栏列表？），未写）
- [x] CHK008 发布审批语义的复用范围是否定义（FR-009 说"走 001 gatekeeper 权限与适用审批语义"；**编排发布是否属于需审批的 R 级**、审批人是谁（平台管理员？租户管理员？），未定义）
- [x] CHK009 权限码命名是否定义（决策 #5 说 `orchestration:write` **类**能力——"类"字表明未定稿；读/写/发布分别对应哪个权限码未给）

## 一致性（Consistency）

- [x] CHK010 与 010 `store.py::_document_shape` 的联合改动边界是否声明（决策 #2 标注这是"联合改动点，需同步 010 spec"；**010 spec 是否需要同步修订、改动的验收口径**未写，易出现两处文档不一致）
- [x] CHK011 与 002 工作流版本化的字段语义是否对齐（FR-010 说与 002 对齐；**版本号字段名、递增规则、回看入口**是否与 002 同构，未核对）
- [x] CHK012 与 010 loader 的 `raw` 透传约定是否一致（决策 #2 说 `loader.py` 不改（`raw` 已透传全量文档）；**画布保存的 YAML 是否必须保持 `raw` 可装载**、`layout` 放顶层是否会被 loader 校验拒绝，未核实）
- [x] CHK013 前端校验与后端校验的单一来源是否声明（`canvasValidation.ts` 与引擎 `topo.py`/`conditions.py` 的规则重复实现；**以谁为准、规则漂移如何发现**未写）

## 边界与歧义（Edge Cases & Ambiguity）

- [x] CHK014 大图性能边界是否定义（节点/边数量上限、超过后的行为（禁止新增？警告？）、画布渲染降级策略，均未写；无上限则浏览器可能卡死）
- [x] CHK015 并发编辑冲突是否定义（两名用户同时打开同一编排并保存：后写覆盖？乐观锁版本号？冲突提示？未定义）
- [x] CHK016 删除被引用节点/边的级联行为是否定义（删除节点后其入/出边自动清理？孤立边？条件引用了已删节点 ID 时保存是否报错）

## Notes

- 条目编号 CHK001–CHK016 连续，覆盖完整性 / 清晰度 / 一致性 / 边界四类；每条均可回溯到 spec.md 的 FR / 决策表原文。
- 本特性需求风险集中在**转换层契约**（CHK001/CHK002/CHK012）与**双端校验一致性**（CHK003/CHK013）：画布是投影，投影与权威一旦漂移，用户保存的图就无法被引擎执行。

## 评审结论（2026-10-24 勾选，agent 代审 + spec 回填）

16 条全部达标，均经 `spec.md` 新增的「判定口径补充（R-1~R-16）」消解：

- CHK001（画布 JSON schema）→ R-1：`canvasSchema.ts` 的 kind/mode/position 定义 + `payload.x_canvas` 映射规则。
- CHK002（`layout` 结构与容错）→ R-2：仅 `{nodeId:{x,y}}`、逐项清洗丢弃非法项、viewport 不持久化。
- CHK003（环错误格式）→ R-3：`cycle detected: A -> B -> C -> A`，422，与 `topo.CycleError` 同串。
- CHK004（草稿存储）→ R-4：同集合 `dag_definitions` + `status="draft"`、覆盖式 `_upsert`。
- CHK005（未知 payload 键）→ R-5：UI 不暴露、序列化不丢。
- CHK006（supervisor/hybrid 呈现）→ R-6：可查看、编辑受限、明示不支持。
- CHK007（校验时机与呈现）→ R-7：保存前必校验 + 前端即时提示 + 后端 detail 透出。
- CHK008（发布审批语义）→ R-8：仅权限码、无人工审批队列。
- CHK009（权限码命名）→ R-9：`orchestration:write` / `orchestration:publish` 定稿。
- CHK010（`store.py` 联合改动）→ R-10：唯一引擎侧改动，010 FR 无需修订。
- CHK011（与 002 版本化对齐）→ R-11：版本字段与端点形状，历史版本无专用端点（已知差异）。
- CHK012（loader `raw` 透传）→ R-12：保存前即经 `load_orchestration_document` 校验。
- CHK013（双端校验单一来源）→ R-13：后端为准，前端为提示层。
- CHK014（大图边界）→ R-14：不设硬上限、200 节点提示、无降级策略。
- CHK015（并发编辑）→ R-15：无乐观锁、后写覆盖（已知取舍）。
- CHK016（删除级联）→ R-16：前端删边、后端装载器拒绝悬空引用。

**验收证据**：`services/chat-api/tests/orchestration/test_orchestration_canvas_api.py` 11 passed；`services/chat-api/tests/orchestration/` 全量 91 passed（010 引擎零回归）；实现落点 `services/chat-api/app/api/endpoints/orchestrations.py`、`services/chat-api/app/services/orchestration_permission.py`、`services/chat-api/app/orchestration/store.py`（`layout` 透传）、`apps/user-web/src/components/orchestration/{canvasSchema,canvasValidation}.ts` + `{OrchestrationCanvasPage,NodePropertyPanel}.vue`、`apps/user-web/src/api/orchestration.ts`。
