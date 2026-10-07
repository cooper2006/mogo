# Standard 深度全量 QA 审计报告（第三轮 · R3）

**审计时间**：2026-10-06 15:00–17:30
**审计基线**：`main` @ `c9e34f6`（R1 + R2 全部修复已合入上一提交链）
**审计范围**：全仓 21 spec / 3 Python 服务 / 2 前端 / CI 门禁 / 治理资产 / 发布就绪度
**审计目标**：在 R1（生产接线）、R2（数据隔离 / 契约一致性 / 门禁有效性）之后，**换第三批维度**找新问题

---

## 一、审计结论

**共 16 项发现：3 项 P0、10 项 P1、3 项 P2。已全部处置。**

核心结论：**R1/R2 的修复本身没有副作用，但"修复动作"（提交 `707c8ea`，`add log_print to 69 silent except blocks`）引入了一批系统性回归**——这是前两轮完全没有审计过的对象：**审计"修复"而不是"特性"**。

R2 报告宣称 `2226 passed / 0 failed`。**该结论不成立**：它依赖临时传入的 `-o asyncio_mode=auto`，而 `pyproject.toml` 与 CI 都未设置该项。**CI 上的真实结果是 43 项失败、退出码 1**——本轮已实证（见 A1）。

| 等级 | 数量 | 状态 |
| --- | --- | --- |
| P0 阻断 | 3 | ✅ 已修复 |
| P1 高 | 10 | ✅ 已修复 |
| P2 中 | 3 | ✅ 已修复 / 确认为误报 |

**新增维度（R3 独有）**：

| 轴 | 回答的问题 | 前两轮 |
| --- | --- | --- |
| **E · 修复动作的破坏性变更** | "修 Bug 的那次改动，自己有没有引入新 Bug？" | 完全未覆盖 |
| **F · 定位符 vs 凭证** | "URI 是地址，还是通行证？" | 未覆盖（R2 只看 SQL/查询过滤） |
| **G · 门禁可复现性** | "本机绿 ≠ CI 绿，差异在哪？" | R2 只验"门禁会不会红"，没验"门禁在 CI 上到底什么颜色" |

---

## 二、逐条勾选清单

### R3-A 修复动作自身的破坏性变更（新维度 · 核心）

审计对象：`707c8ea`（165 文件 / 452 hunk / +3326 −601）。方法：对每个 hunk 做 **AST 级破坏性判定**——不是看"改了没有"，而是看"**删掉的是不是真实语句**"。

- [x] **A1 · P0 · CI 测试门禁必红（发布阻断）** → 已修复
  - **证据 1**：`services/chat-api/pyproject.toml` 的 `[tool.pytest.ini_options]` 只有 `testpaths` 与 `addopts = "-q --timeout=120"`，**无 `asyncio_mode`**；`.github/workflows/quality-gate.yml` 亦无 `PYTEST_ADDOPTS` 或 `-o asyncio_mode`
  - **证据 2（对抗复现）**：把 `asyncio_mode` 还原为默认 `strict` 后跑全量 —— **exit=1，43 项失败**；而当前 `auto` 配置下 —— **2229 passed / 0 failed / exit=0**
  - **根因**：测试大量使用裸 `async def`（无 `@pytest.mark.asyncio`），pytest-asyncio ≥ 0.23 在 strict 模式下拒绝执行
  - **修复**：`pyproject.toml` 写入 `asyncio_mode = "auto"`，并把 `pytest-asyncio`、`pytest-timeout` 显式声明进 `[tool.poetry.group.dev.dependencies]`（此前是"本机能跑"的隐式依赖）
  - **意义**：这是**唯一一个"代码全对但一定发不出去"**的缺陷——R1/R2 两轮都宣称全绿，但绿是本机手动加 flag 换来的

- [x] **A2 · P1 · 8 处 try 体真实语句被删（控制流破坏）** → 已修复
  - 机械 sweep 在插入 `except ...: log_print(...)` 时，把 try 体内**最后一条真实语句**当成了要替换的 `except` 体一并删除
  - 逐处清单：

    | 文件 | 被删的语句 | 后果 |
    | --- | --- | --- |
    | `api/endpoints/models.py` `stream_model_test` | `yield _sse({"type":"error",...})` | SSE 错误帧不再下发 |
    | `api/endpoints/models.py` `model_test` | `return {"code":0,...,"healthy",...}` | 成功路径返回 `None` |
    | `api/endpoints/models.py` `image_model_test` | `except ModelConfigError` 子句位置 | 异常被 `except Exception` 抢先吞掉 |
    | `browser/engine/effect_verification/discovery.py` | `return EffectContract(**data, source="model")` | 3 项测试 `'NoneType' has no attribute 'is_commit'` |
    | `browser/engine/workflow_cache/recorded_target_identity.py` | `parser.close()` | 文件句柄泄漏 |
    | `content/publish_assembly/assembler.py` | `return False, f"llm_visual_slot_rejected:..."` | 拒绝原因丢失，返回 `None` |
    | `services/rag_service/remote_knowledge_rag_service.py` | `raw = resp.json()` | 后续引用未绑定 |
    | `services/skill_sharing/legacy_migration.py` | `package = validate_skill_package(archive)` | 校验被跳过（**安全相关**） |

- [x] **A3 · P1 · 23 处 except 回退值被删** → 已修复
  - sweep 把 `except Exception:` → `except Exception as exc: log_print(...)` 时，**把原 handler 的 `return X` 兜底一并删除**，异常路径直接穿透
  - 分三类，全部用脚本实证（修复前 `[FAIL]`，修复后 `[OK]`）：

    **A3-1 · UnboundLocalError（16 处）** —— try 体绑定的名字在 except 后仍被读取

    | 文件 · 函数 | 名字 | 原回退 |
    | --- | --- | --- |
    | `utils/ssrf_guard.py` `is_safe_url` | `parsed` | `return False` ⚠️ **安全函数** |
    | `tools/infographic.py` `is_valid_remote_image_url` | `parsed` | `return False` |
    | `services/image_generation.py` `_is_valid_remote_image_url` | `parsed` | `return False` |
    | `browser/engine/auth_state.py` `site_scope` | `host` | `return ""` |
    | `evidence/foundation/user_payload.py` `_json_text` | `parsed` | `return ""` |
    | `evidence/foundation/user_payload.py` `_empty_kb_result` | `parsed` | `return False` |
    | `evidence/foundation/writer_packet/common.py` `decode_mapping` | `parsed` | `return {}` |
    | `evidence/foundation/kb_qa_projection.py` `decode_tool_payload` | `parsed` | `return {}` |
    | `llm/resilience/providers.py` `load_resilience_config` | `document` | `return {}` |
    | `llm/decision_turn/contracts.py` `normalize_decision_commentary` | `commentary` | `return None` |
    | `infrastructure/execution_events/operation.py` `normalize_model_operation` | `operation` | `return None` |
    | `knowledge_graph/rag_candidates.py` `kg_rag_candidates` | `store` | `return []` |
    | `services/skill_assets/composite_task.py` `_extract_frontmatter` | `data` | `return {}` |
    | `services/business_semantic_index.py` `semantic_search` | `result` | `return []` |
    | `browser/engine/workflow_cache/learning_trace.py` `_stable_action_args` | — | `return {}` |
    | `browser/pending_intervention.py` `pending_browser_result` | `record` | `return None` |

    **A3-2 · 契约破坏（6 处）** —— 函数注解 `-> X`（X 非 None），异常时却隐式返回 `None`

    | 文件 · 函数 | 注解 | 原回退 |
    | --- | --- | --- |
    | `browser/engine/pages/wechat_draft_list_page.py` `find_draft` | `-> bool` | `return False` |
    | `services/org_skill_adapter.py` `_safe_int` | `-> int` | `return 0` |
    | `services/skills.py` `_coerce_int` | `-> int` | `return 0` |
    | `services/presentation/image_native/deck_brief_planner.py` `theme_reference_markdown` | `-> str` | `return ""` |
    | `utils/storage_utils.py` `download_text` | `-> str` | `return ""` |
    | `governance/action_receipt_store.py` `_load_many` | `-> List[...]` | `return []` |

    **A3-3 · 行为回归（1 处）** —— `browser/ws_endpoint.py` `ping_loop` 的 `except: return` 被删，`while True` 循环失去早退，socket 断开后仍每 20s 打点+记日志，直到 `finally` 取消

- [x] **A4 · P1 · 6 处重复 `except` 子句（死兜底）** → 已修复
  - sweep 追加了新 handler 却未删旧的，形成同类型重复子句；**后者在 Python 中不可达**（`except A` 之后再来 `except A`），新加的 `log_print` 永远不执行
  - 涉及 `models.py`（2）、`discovery.py`、`recorded_target_identity.py`、`assembler.py`、`remote_knowledge_rag_service.py`、`legacy_migration.py`、`content/evaluation/streaming.py`
  - 其中 `content/evaluation/streaming.py` 后果最重：原重复使 `await queue.put(EvaluationStreamItem("error", exc))` 不可达，**SSE 流在异常时永久挂起**
  - **复检**：AST 扫描全 `app/` 重复 `except` 子句 = **0**

- [x] **A5 · P1 · 18 个文件调用未导入的 `log_print`** → 已修复
  - sweep 批量插入了 `log_print(...)` 调用，但**没有为这些文件补 import**
  - **后果**：异常分支自身抛 `NameError`——比原来的静默 `pass` 更糟（静默至少不崩）
  - **实证**：`orchestration/store.py` 的注册失败路径实测抛 `NameError`
  - **修复**：18 个文件补 `from app.infrastructure.observability.config import log_print`
  - **复检**：pyflakes 全服务未定义名扫描 = **0**（仅剩 2 处字符串前向引用误报，见下）

- [x] **A6 · P2 · import 被插进模块 docstring / 重复 import** → 已修复
  - `services/business_semantic_index.py`：`from ... import log_print` 被插进模块 docstring 正文（第 5 行），docstring 内容被污染
  - `business_index/entities.py` 同类问题
  - `api/endpoints/models.py`：同一 import 连续重复 3 行
  - **复检**：模块级重复 import = **0**；docstring 内 import = 0（剩余 3 处为 `skills_specs/` 第三方脚本的 `Usage:` 文档示例，非代码）

- [x] **A7 · 检测器自身的对抗验证** → 通过
  - 写了 AST 检测器（`S1` 落空 except 读 try 绑定名 / `S2` 非 None 注解函数落到末尾）
  - **在缺陷提交 `707c8ea` 上跑：命中全部 24 处真缺陷**
  - **在当前工作区跑：仅剩 4 处，逐一核实为非缺陷**（Protocol 存根 `session_tiers`、已前置初始化的 `resp`、两处 `Optional[...]` 落空返回 `None` 与原逻辑等价）
  - 检测器自身也修过两轮误报（`falls_through` 未递归进 `Try`、推导式变量被误判为作用域内绑定、兄弟 `try` 交叉污染）

### R3-B 越权与访问控制：定位符 vs 凭证（新维度）

- [x] **B1 · P0 · `check_memory_visibility` 采信 URI 自身携带的身份** → 已修复
  - **证据**：原实现从 `addr` 上的 `scope` / `owner_id` 段**构造**一个 `Memory` 对象再判定可见性
  - **影响**：URI 是**定位符**却被当成**凭证**。`u2` 构造 `mogo://memory/org/u1/m-1/L2` 即可读到 `u1` 的私密内容
  - **实证**：复现脚本输出 `[LEAK] u1 PRIVATE SALARY 99999`；修复后 `[DENIED]`
  - **修复**：`check_memory_visibility` 改为接收**真实存储记录**（`memory: Optional[Any]`），缺失即 **fail closed**；`check_visibility` 转发；`adapters/memory.py` 传入已加载的记录
  - **验证**：新增 5 项越权回归测试（伪造 owner / 伪造 org scope / 正常读自己 / session 同理）

- [x] **B2 · P0 · session 适配器只按 `_id` + tenant 查询** → 已修复
  - **证据**：`adapters/session.py` 的 `_load` 查询条件为 `{"_id": oid}` + `add_main_scope(...)`，**无 `user_id`**
  - **影响**：同一租户内任一成员可读他人会话（含 L2 逐字稿）
  - **修复**：查询加入 `"user_id": str(viewer_id)`；`_load` 增加 `viewer_id` 形参
  - **验证**：新增 `test_resolve_session_other_user_is_denied` / `test_resolve_session_owner_still_reads_own`

- [x] **B3 · P1 · `context_space` 检索轨迹无租户隔离** → 已修复
  - `_TRACE_RING` 以单键存储，跨租户可读他人检索轨迹（暴露"谁在查什么"）
  - **修复**：`_TRACE_RING: dict[str, tuple[str, dict]]` 存 `(tenant_id, trace)`；`get_context_trace` 校验 `entry[0] != tenant_id` → 404
  - **验证**：新增 `test_trace_readback_is_tenant_scoped`

- [x] **B4 · P1 · `POST /memory` 允许任意角色写 org 作用域（违反 017 FR-4）** → 已修复
  - **修复**：`scope == org` 且角色不在 `ORG_PROMOTION_ROLES` → 403
  - **验证**：新增 2 项测试（普通角色拒绝 / 管理员放行）

### R3-C 契约、配置与数据正确性

- [x] **C1 · P1 · 记忆 `HARD_MAX` 按字符而非字节计量（违反 017 FR-16）** → 已修复
  - `len(content)` 计的是**字符数**，中文内容实际占用 3 倍字节，上限被穿透
  - **修复**：`len(content.encode("utf-8", errors="replace"))`

- [x] **C2 · P1 · 摘要刷新周期硬编码 30 天（死配置）** → 已修复
  - `MEMORY_SUMMARY_REFRESH_DAYS` 存在但从不被读取；`_row_to_memory` 硬编码 `30`
  - **修复**：新增 `_configured_refresh_days()`；`save(summary_refresh_days=0)` 语义明确为"用配置值"；删除 `sediment.py` 中重复的 `SUMMARY_REFRESH_DAYS_DEFAULT`

- [x] **C3 · P1 · `orchestration/store.py` 双重缺陷** → 已修复
  - `_document_shape` 读 `loaded.definition.id`（真实字段是 `orchestration_id`）→ 落库主键为空
  - 修好注册路径后暴露第二处：`load_orchestration_document` **未导入** → `NameError`
  - **验证**：新增 `test_document_shape_uses_orchestration_id`

- [x] **C4 · P1 · `revoke_share` 引用未定义变量** → 已修复
  - `main_id, _ = await _authorize(...)` 丢弃了 `user_id`，函数体后续却引用 `user_id` → 端点必 500
  - **修复**：`main_id, user_id = await _authorize(...)`

- [x] **C5 · P2 · `memory/address.py` 未拒绝超长 URI** → 已修复
  - `> 4` 段未校验，畸形 URI 可绕过作用域解析
  - **修复**：`if len(parts) > 4: raise ValueError(...)`

- [x] **C6 · P2 · 未定义名扫描的两处残留** → 确认为误报
  - `llm/resilience/providers.py:117` `ResilientLLMClient`、`context_space/adapters/base.py:46` `ViewerContext`
  - 二者均为**字符串前向引用注解**，且在 `from __future__ import annotations` 下永不求值；前者函数体内已 lazy import，后者为 `@abstractmethod` 签名
  - **不修改**（改反而是噪音）

### R3-D 测试与发布就绪（复验）

- [x] **D1 · chat-api 全量** → **2229 passed / 0 failed / 0 error / 0 skipped**，exit=0（JUnit XML 权威计数）
- [x] **D2 · chat-api 覆盖率门禁** → **57.16% ≥ 55%**，exit=0
- [x] **D3 · 模块覆盖率门禁** → **8/8 通过**（context_space 92.6% / memory 86.3% / hooks 91.2% / router 100% / trace 100% / address 92.3% / tiering 97.4% / dispatcher 84.3%）
- [x] **D4 · admin-api** → **433 passed / 0 failed**
- [x] **D5 · document-parser** → **22 passed / 0 failed**
- [x] **D6 · 生产接线门禁** → **5/5**（context_space.router / dispatcher / sediment / tiering / address）
- [x] **D7 · 版本一致性** → CHANGELOG / user-web / admin-web 统一 **0.2.0**
- [x] **D8 · 全服务语法与未定义名** → AST 解析全通过；pyflakes 未定义名仅 2 处字符串前向引用误报
- [x] **D9 · flaky 测试** → `test_durable_writer_flush_deadline_is_measured_from_first_event` 改为区间断言 + 总量断言，消除对墙钟批次大小的依赖

---

## 三、修复清单

| 编号 | 等级 | 问题 | 修复 | 验证 |
| --- | --- | --- | --- | --- |
| A1 | **P0** | CI 测试门禁必红（`asyncio_mode` 缺失） | 写入 `pyproject.toml` + 显式声明 dev 依赖 | strict 复现 43 failed → auto 2229 passed |
| B1 | **P0** | 021 地址层记忆越权（URI 当凭证） | 改为接收真实记录，缺失 fail closed | 复现 `[LEAK]` → `[DENIED]` + 5 项回归测试 |
| B2 | **P0** | 021 地址层 session 越权（无 `user_id`） | 查询加 `user_id` 条件 | 2 项回归测试 |
| A2 | P1 | 8 处 try 体真实语句被删 | 逐处恢复 | 3 项 effect_discovery 测试转绿 |
| A3 | P1 | 23 处 except 回退值被删 | 逐处恢复 | 23 项复现脚本全 `[OK]`（缺陷树全 `[FAIL]`） |
| A4 | P1 | 6 处重复 `except`（死兜底） | 合并 | AST 复检 = 0 |
| A5 | P1 | 18 文件 `log_print` 未导入 | 补 import | pyflakes = 0 |
| B3 | P1 | 检索轨迹无租户隔离 | ring 存 `(tenant_id, trace)` | 1 项回归测试 |
| B4 | P1 | org 作用域无角色校验 | 非管理员 403 | 2 项回归测试 |
| C1 | P1 | HARD_MAX 按字符计量 | 改按 UTF-8 字节 | 上限测试 |
| C2 | P1 | 摘要刷新周期死配置 | 读环境变量 | 配置测试 |
| C3 | P1 | `orchestration/store.py` 双重缺陷 | 字段名 + 补 import | 1 项回归测试 |
| C4 | P1 | `revoke_share` 未定义变量 | 接住 `user_id` | — |
| A6 | P2 | docstring 内 import / 重复 import | 归位去重 | AST 复检 = 0 |
| C5 | P2 | 超长 URI 未拒绝 | 段数校验 | 地址测试 |
| A7 | — | 检测器未经验证 | 在缺陷提交上对抗验证 | 24/24 命中 |
| D9 | — | flaky 测试 | 改区间断言 | 两轮全量稳定 |

**测试净增**：chat-api 2226（R2 宣称）→ **2229**（+3，均为越权/隔离回归测试）；另新增 `tests/context_space/`、`tests/hooks/`、`tests/memory/` 等 9 个测试文件/目录（R1/R2 期间沉淀）

---

## 四、可勾选确认

- [x] R3-A 修复动作的破坏性变更 —— 7/7（**P0 门禁必红已修**；8 处控制流破坏、23 处回退丢失、6 处死兜底、18 处未导入、docstring 污染全部归零）
- [x] R3-B 越权与访问控制 —— 4/4（**2 项 P0 越权已修**；轨迹隔离、org 角色校验已修）
- [x] R3-C 契约与配置 —— 6/6（4 项 P1 已修，2 项确认为误报）
- [x] R3-D 测试与发布就绪 —— 9/9（三服务全绿、四门禁全过、版本一致）
- [x] **总体：无 P0 遗留，可进入 PR 评审与版本发布**

---

## 五、遗留建议（不阻断发布）

| # | 建议 | 处置 | 说明 |
| --- | --- | --- | --- |
| 1 | **禁止对 `except` 块做批量机械改写** | **已落地为纪律** | 本轮所有缺陷同源于 `707c8ea` 的机械 sweep。建议：任何跨文件批量改写必须附带 ① AST 破坏性 diff 审查 ② 全量测试 ③ pyflakes 未定义名门禁。已把 3 个检测脚本（AST 落空检测 / 破坏性 hunk 扫描 / 缺陷类复检）沉淀为可复用工具 |
| 2 | **CI 增加静态门禁：`pyflakes` 未定义名 + 重复 `except` 子句** | **建议下一步** | 这两类缺陷本可 100% 被静态检查拦住，且成本极低（pyflakes 全服务 < 2s）。R2 已建立"门禁自身要对抗验证"的做法，本轮建议把门禁从"接线/覆盖率"扩展到"静态正确性" |
| 3 | 全仓宽泛/静默异常捕获分批收敛 | **R4 已收口（2026-10-06）** | Wave 1–4 已完成；Wave 5+（`707c8ea`）做了 69 处但**引入本轮全部 A2–A6 缺陷**。**R4 改用 AST 安全改写器**（只增不删 / 不遮蔽变量 / 保留尾注释 / 排除异常已传播 / 绝不碰 `log_print` 定义模块）处理剩余非静默宽泛 except：**95 文件 · 209 条日志 · 66 个 import · 147 行 except 改写 · 非-except 删除 0**；显式排除 73 处已传播 + 38 处有意 `pass`（含日志基础设施自身）。全量 **2229 / 0 / 0 / 0**，缺陷类基线对比与快照**完全一致（60 = 60）**。详见 `docs/WORK_LOG.md` 同日 R4 节 |
| 4 | `action_receipt_store._load_one/_load_latest` 落空返回 `None` | **确认为等价** | 原逻辑即 `except: return None`，与隐式返回 `None` 语义相同，不修改 |
| 5 | `skills_specs/` 第三方脚本的 `Usage:` docstring 含 import 示例 | **确认为非代码** | 扫描器误报，不修改 |
| 6 | Node Runtime Host 启动失败（`manager.probe()` 挂起） | **延后，需独立排查（继承 R2）** | 属 Node/DSH kernel 集成层，超出 Python 审计范围 |

---

## 六、修改文件清单（本轮 R3）

**P0 / 越权（021 地址层）**

- `services/chat-api/app/context_space/visibility.py` — 改为接收真实记录 + fail closed
- `services/chat-api/app/context_space/adapters/memory.py` — 传入已加载记录
- `services/chat-api/app/context_space/adapters/session.py` — 查询加 `user_id`
- `services/chat-api/app/api/endpoints/context_space.py` — 轨迹 ring 租户隔离
- `services/chat-api/app/api/endpoints/memory.py` — org 作用域角色校验
- `services/chat-api/pyproject.toml` — `asyncio_mode = "auto"` + dev 依赖显式声明

**P1 / 恢复被删语句（A2）**

- `app/api/endpoints/models.py`（3 处控制流 + 重复 import 去重）
- `app/enterprise_capabilities/browser/engine/effect_verification/discovery.py`
- `app/enterprise_capabilities/browser/engine/workflow_cache/recorded_target_identity.py`
- `app/enterprise_capabilities/content/publish_assembly/assembler.py`
- `app/services/rag_service/remote_knowledge_rag_service.py`
- `app/services/skill_sharing/legacy_migration.py`
- `app/enterprise_capabilities/content/evaluation/streaming.py`

**P1 / 恢复 except 回退（A3）**

- `app/utils/ssrf_guard.py`、`app/tools/infographic.py`、`app/services/image_generation.py`
- `app/enterprise_capabilities/browser/engine/auth_state.py`
- `app/enterprise_capabilities/browser/engine/operation_result_projection.py`
- `app/enterprise_capabilities/browser/engine/workflow_cache/learning_trace.py`
- `app/enterprise_capabilities/browser/engine/pages/wechat_draft_list_page.py`
- `app/enterprise_capabilities/browser/pending_intervention.py`
- `app/enterprise_capabilities/evidence/foundation/user_payload.py`（2 处）
- `app/enterprise_capabilities/evidence/foundation/writer_packet/common.py`
- `app/enterprise_capabilities/evidence/foundation/kb_qa_projection.py`
- `app/llm/resilience/providers.py`、`app/llm/decision_turn/contracts.py`
- `app/infrastructure/execution_events/operation.py`
- `app/knowledge_graph/rag_candidates.py`
- `app/services/skill_assets/composite_task.py`
- `app/services/org_skill_adapter.py`、`app/services/skills.py`（2 处）
- `app/services/presentation/image_native/deck_brief_planner.py`
- `app/services/business_semantic_index.py`（回退 + docstring 清理）
- `app/utils/storage_utils.py`、`app/governance/action_receipt_store.py`
- `app/browser/ws_endpoint.py`

**P1 / 契约与配置（C 轴）**

- `app/memory/store.py`（字节计量 + 配置化刷新周期）
- `app/memory/sediment.py`（去重复常量）
- `app/memory/address.py`（段数校验）
- `app/orchestration/store.py`（字段名 + 补 import）
- `app/api/endpoints/dsh_session_versioning.py`（未定义变量）

**P1 / `log_print` 补导入（A5，18 文件）**

- `app/main.py`、`app/knowledge_graph/store.py`、`app/knowledge_graph/consistency.py`、`app/tools/pdf.py`、`app/a2a/client.py`、`app/context_engine/compactor.py`、`app/context_engine/token_budget.py`、`app/business_index/entities.py`、`app/orchestration/store.py`、`app/api/principal.py`、`app/services/business_semantic_index.py`、`app/services/knowledge_preview_stream.py`、`app/services/document_context.py`、`app/services/form_filling/mapper.py`、`app/services/presentation/icon_library.py`、`app/infrastructure/observability/execution_trace.py`、`app/knowledge/citations/citation_resolver.py`、`app/llm/decision_turn/runner.py`

**测试**

- `tests/context_space/test_address_visibility.py` — 替换"只验构造器"的伪测试为 2 项真实判定测试
- `tests/context_space/test_adapters_integration.py` — 5 项越权回归
- `tests/context_space/test_context_endpoints.py` — 轨迹租户隔离
- `tests/memory/test_memory_endpoints.py` — org 角色校验
- `tests/orchestration/test_competitor_deep_dive_audit.py` — `_document_shape` 字段
- `tests/dsh_runtime/test_step4_live_persistence.py` — flaky 修复

**本轮报告**

- `docs/pending-review/2026-10-06-full-qa-audit-r3.md` — 本文件

---

## 七、方法论备注

**1. 本轮真正的价值来自"审计修复动作本身"。**

R1 问"实现了但到得了吗"（生产接线），R2 问"到得了但安全吗、对得上吗"（隔离 / 契约）。这两轮都默认"**修复 = 变好**"。本轮第一次把**提交 `707c8ea` 本身**当作审计对象，结果 3 个 P0 中挖出 1 个、10 个 P1 中挖出 4 个。

一个反直觉的结论：**"把静默异常改成打日志"这个看似零风险的改动，是整条提交链里破坏性最强的一次。** 原因不是意图错，而是**手段是机械的**——用正则/脚本跨 165 个文件做 `except` 块替换，而 `except` 块的边界（哪里是 handler 体、哪里是 try 体最后一句）**正则判不准**。

**2. "本机绿"与"CI 绿"之间的差距必须显式验证。**

R2 报告写"2226 passed / 0 failed"。本轮用 JUnit XML 复现，发现该结论依赖临时 `-o asyncio_mode=auto`。**把配置还原成仓库里真实的样子（strict）后是 43 failed / exit=1。**

教训：**验证"测试全绿"时必须用 CI 的真实调用方式**，不能用"本机顺手加的参数"。这也补上了 R2 的一个缺口——R2 验了"门禁会不会红"，但没验"门禁在 CI 上到底是什么颜色"。

**3. 检测器必须先被对抗验证，否则它只是在生产噪音。**

本轮 AST 检测器迭代了三轮才可信：

| 版本 | 问题 | 后果 |
| --- | --- | --- |
| v1 | `falls_through` 不递归进 `Try` | 修复后的代码仍被报，**误报** |
| v1 | 只检查 handler 内部的读 | **漏报** `_json_text` 这类"读在 try 之后"的真缺陷 |
| v2 | 推导式变量被当成外层作用域绑定 | `compose_skill.py` 3 处**误报** |
| v2 | 兄弟 `try` 之间交叉污染 | `orchestration/store.py` **误报** |
| v3 | 补齐后 | 缺陷树 **24/24 命中**，当前树仅剩 4 处且全部核实为非缺陷 |

**判定标准**：一个检测器只有在"已知有缺陷的版本上全部命中、已知无缺陷的版本上零命中"之后，它的输出才值得写进报告。否则 100% 误报和 100% 漏报一样无用（R2 已记录过同类教训）。
