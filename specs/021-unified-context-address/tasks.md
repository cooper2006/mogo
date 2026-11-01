# Tasks: Unified Context Address Space

**Prerequisites**: plan.md (required), spec.md (required)

**Organization**: 落点 = `chat-api/app/context_space/`

---

## Phase 1: 基础设施（路由器 + 适配器框架 + 轨迹）

- [x] T001 实现 URI 路由器（mogo:// 解析 + 未知根报错 + 路由到适配器）—— `router.py` 已实现并通过 `test_context_space.py`。
- [x] T002 定义 TierAdapter 接口（base.py: `ResolvedTier` + `resolve`）—— 已实现。
- [x] T003 实现统一检索轨迹（trace.py：schema + 绑定 session/turn）—— 已实现，并接入 `adapters.knowledge_search` 真实 RAG 路径（`memory_retrieval_trace`）。
- [x] T004 实现委托式可见性解析（visibility.py：调各后端检查，静默裁剪）—— 已实现 `check_visibility` 委托 017 `visible_to`。

## Phase 2: 首期 tenant（memory，接 017）

- [x] T005 实现 memory 适配器（adapters/memory.py，消费 017 FR-17/FR-18）—— 已实现。
- [x] T006 端到端：记忆经 mogo://memory/... 寻址 + 渐进加载 + 轨迹回看—— 已实现并通过测试（可见/不可见/未找到/未知根）。
- [x] T007 接 009 SessionEnd → 触发 017 分层沉淀（FR-20）—— **已重构（2026-10-06）**。原实现只在 `delete_session` 里直接调 `sediment_session_end`，语义上是"删除时才沉淀"，009→017 闭环并未真正闭合。现改为：① 新增 `app/dsh_runtime/hooks/dispatcher.py` 提供真实的事件订阅/派发（`subscribe`/`dispatch`/`dispatch_session_end`），`lifecycle.emit_*` 产出的 payload 不再无人消费；② `app/memory/sediment.py` 注册为 `SessionEnd` 订阅者（`register_sedimentation_subscriber`），并用 `_SEDIMENTED` 账本保证幂等；③ 002 新增显式结束语义 `SessionPersistenceService.end_session` + `POST /sessions/{id}/end`，会话结束时派发 `SessionEnd` 触发沉淀；④ `delete_session` 降级为兜底（仅对未结束过的会话沉淀，经账本去重）。测试：`tests/hooks/test_dispatcher.py`、`tests/services/test_session_end_lifecycle.py`。

## Phase 3: 扩展 tenant（按节奏，依赖各 spec 就绪）

- [x] T008 resource 适配器：005 doc / 014 biz / 015 kg —— `adapters/resource.py` 已实现 `ResourceTierAdapter`，覆盖 doc/biz/kg 三子根。**2026-10-06 优化**：kg 子根原调用 `TenantKgStore._ensure_loaded()`（一次拉取租户最多 2000 节点 + 5000 边）仅为读取单节点，且调用了私有方法破坏封装；现新增公开接口 `TenantKgStore.get_node_direct(node_id)`（直查单节点 + 限量邻居，已加载时回退内存路径），适配器改用该接口。
- [x] T009 skill 适配器：004 skill / 018 asset —— `adapters/skill.py` 已实现 `SkillTierAdapter`，覆盖 skill/asset 两子根。
- [x] T010 session 适配器：002 归档根 mogo://session/... —— `adapters/session.py` 已实现 `SessionTierAdapter`，L0/L1/L2 逐层委托 002 后端。

---

## Notes

- 021 依赖 017 优化先落地（见 017 Phase 5：T012~T018）。
- 不新增存储，复用各后端库。
- 跨特性关系已在 spec 双向声明（017/002/009/005/014/015/004/018）。
- 首期只做 memory tenant，验证"目录树可浏览 + 检索轨迹"范式后再扩。
