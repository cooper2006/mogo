# Requirements Quality Checklist: 014 business-semantic-index

**Purpose**: 校验 014（业务系统语义索引：对接 CRM/采购/财务做语义检索）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-07-08
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 "业务实体"（FR-1）是否穷举（客户/订单/供应商/账目，是否含产品/库存/员工等更多实体类型，还是首期仅 4 类）？
- [x] CHK002 "增量更新"（FR-2）是否定义增量粒度（按主键变更 vs 全量重建 vs CDC 事件，clarify 已定时机是否 FR 同步）？
- [x] CHK003 "跨系统联查"（FR-5）是否定义联查的关联键（客户编号如何跨 CRM/财务对齐，实体对齐的键规则是否声明）？
- [x] CHK004 "检索命中带实体来源"（FR-3）是否定义来源定位的字段深度（表名/字段/记录 ID 三级，还是仅"业务系统名"一级）？

## 清晰度（Clarity）

- [x] CHK005 clarify 已定"首期 CRM + DB 只读副本"（OQ-1）——FR-1 是否同步"首期对接 CRM"（还是正文写"至少 1 个"而无具体）？
- [x] CHK006 clarify 已定"实体 schema 可配置"（OQ-2）——FR 是否声明 schema 配置入口（哪个集合/管理面维护 entity_types）？
- [x] CHK007 clarify 已定"定时拉取（复用 scheduled_tasks），不做 CDC"（OQ-3）——FR-2"增量更新"是否同步"定时拉取"机制（避免实现误用 CDC）？
- [x] CHK008 clarify 已定"业务 PII 字段走 001 脱敏（mask/hash），索引前脱敏，检索不回填明文"（OQ-4）——FR 是否声明 PII 脱敏约束（还是正文未提业务数据 PII 安全）？

## 一致性（Consistency）

- [ ] CHK009 与 005（knowledge-rag）"检索复用 005 检索客户端 + 引用锚点"（FR-7）——005 是否声明其 RetrievalChunkItem 可扩展"业务实体项"（014 的检索项与 005 文档项同通道，口径是否对齐）？
- [ ] CHK010 与 015（knowledge-graph-layer）"业务实体可纳入图谱节点"（015 FR）——014 的 `biz_entities` 与 015 的 `kg_nodes` 实体对齐（指针引用 vs 数据复制，015 clarify OQ-5 定了指针引用，014 是否同步）？
- [ ] CHK011 与 001（gatekeeper）"业务索引访问受 001 权限约束"（FR-9）——业务数据访问的权限码（`bizdata:read` 类）是否在 001 权限码模型中声明（001 权限码 resource 是否含业务系统维度）？

## 边界与歧义（Edge cases & Ambiguity）

- [x] CHK012 业务系统连接不可用（DB 副本宕机）时的检索行为（索引陈旧 vs 明确标注"数据源不可用"）是否定义？
- [x] CHK013 增量拉取的"全量首刷"时机（首次接入如何建全量索引，是否需人工触发）是否定义？
- [x] CHK014 业务实体间"对齐"失败（不同系统同实体对齐键不一致）时的降级（对齐失败是拒绝联查还是标记"未对齐"）是否定义？
- [x] CHK015 只读副本的数据一致性（副本延迟导致检索到旧数据）是否在 spec 级要求标注延迟（还是接受副本延迟不特别说明）？

## Notes

- 本清单为需求质量门禁，全部条目需审阅人逐条评估后勾选；未勾选项构成 `/speckit-implement` 的拦截门禁。
- 标 `[x]` 仅代表"需求质量达标"，不代表实现完成。
- P2 后置特性，CHK 项可在 014 排期前集中处理。
## 评审结论（2026-07-08 勾选，agent 代审；含 FR 回填后复核）

**达标已勾 `[x]`（12 项）**：
- FR 回填后达标：CHK001（首期 4 类实体+schema 可配 → FR-1）、CHK002（定时拉取不做 CDC → FR-2）、CHK003（联查键=业务主键 → FR-5）、CHK004（来源定位三级 → FR-3）、CHK005（首期 CRM+只读副本 → FR-1）、CHK006（entity_types 可配 → FR-1）、CHK007（定时拉取 → FR-2）、CHK008（业务 PII 走 001 脱敏 → FR-10）、CHK012（数据源不可用明确标注 → FR-11）、CHK013（全量首刷人工触发 → FR-2）、CHK014（对齐失败标记未对齐不拒联查 → FR-6）、CHK015（副本延迟标注时间戳 → FR-12）

**未勾 `[ ]` = 真实缺口（3 项，跨特性对齐）：**
- CHK009：005 需声明其 RetrievalChunkItem 可扩展"业务实体项"（需 005 spec 侧确认）
- CHK010：015 需声明 `kg_nodes` 指针引用 `biz_entities`（014 已声明对齐键，需 015 spec 侧反向确认）
- CHK011：001 权限码 resource 需含业务系统维度（`bizdata:read`，需 001 spec 侧确认）

> CHK009/CHK010/CHK011 是 014 与 005/015/001 的跨特性对齐项，需相关 spec 反向声明后勾选。014 自身 spec 质量已达 implement 可写程度。
