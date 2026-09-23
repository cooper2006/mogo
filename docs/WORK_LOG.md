# Work Log

## 2026-07-08 跨特性双向声明轮：清空 15 份 checklist 全部剩余未勾项

- 目标：消解 001/002/007–019 共 15 份 checklist 的剩余未勾项（跨特性两两关系 + 特性自身缺口），让 spec 契约无冲突、进入 implement 就绪。
- **A 类：跨特性双向声明**（在各 spec 新增"跨特性关系（被依赖方视角）"节，两边同声明）：
  - 001 补：↔006 权限码预设组、↔009 钩子扩展点+审计落点、↔012/013/018 受管入口、↔019 层概念、↔014/015 权限码 resource 扩展
  - 002 补：↔009 会话事件载体、↔011 经验源、↔013 IM 会话承载、↔017 记忆沉淀、↔005 会话 vs 知识边界
  - 004 补：↔011 草稿上游、↔016 市场强化基础、↔018 资产引用；005 补：↔014 业务实体项、↔015 图谱融合、↔017 存储/检索
  - 006 补：↔017 记忆提升权、↔019 厚度配置权；007 补：↔010 重试分层、↔001 配额维度、↔008 韧性字段
  - 009 补：↔001 扩展点/审计、↔002 载体、↔010 节点触发、↔019 非红线可跳+fail_closed 保留
  - 011 补：↔016 共用标记位、↔004 草稿、↔010 纯调度；012 补：↔018 a2a_exposed、↔001 受管入口；014 补：↔015 指针引用、↔005 检索、↔001 权限码
- **B 类：特性自身缺口回填 FR**：001 补 25 格 AUTONOMY_MATRIX 完整取值表；007 补降级原因枚举/重试响应取消/failover 计量归属（FR-11~13）；009 补五事件可携带数据/钩子延迟预算（FR-12~13）；010 补跨层并发预算（FR-12）；008 澄清"新标签页=新端点"契约边界。
- **结果**：15 份 checklist **全部 100% 勾选达标**（001 18/18、002 16/16、007–019 各满额）；各 checklist"评审结论"节更新为"全部达标"；003–006 既有回溯未动。
- 更新 `specs/INDEX.md`：checklist 统计行 + "五（补2）"表头与共性结论更新为"已全部消解"。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。改 `specs/**/spec.md`（跨特性关系 + FR 回填）+ `checklists/requirements.md`（勾选+结论）+ `INDEX.md`，未改 services/apps 源码。

## 2026-07-08 回填 + 评审勾选 P2 特性 012–019 的 checklist（agent 代审，19/19 全覆盖）

- 对 P2 八个特性走与 P0/P1 相同流程：逐条判定 checklist，回填 clarify 已定值 + 可消解边界进 FR 正文，再勾真正达标项：
  - **012 a2a-agent-gateway**（13/15）：AgentCard 字段+skills[]、JSON-RPC 方法名、agent 路由、客户端超时/failover、Dify 优先、刷新触发、同租户边界、双向审计、错误码映射、幂等、鉴权枚举、外部注册。
  - **013 multi-im-entry**（13/15）：映射粒度 1:1、长响应分段、能力=Web 全量、租户级开关、首期飞书、纯文本+基础卡片、会话映射、@bot 主体、撤回不回改、离线降级、凭据注入、1会话1IM。
  - **014 business-semantic-index**（12/15）：4 类实体+schema、定时拉取、联查键、来源三级、首期 CRM、PII 走 001、数据源不可用、全量首刷、对齐失败、副本延迟。
  - **015 knowledge-graph-layer**（12/15）：实体/关系类型、跳语义+3 跳、三类约束、查询入口、迁移阈值、断裂判定、合并策略、防环、低置信门槛、矛盾不阻断、融合裁决。
  - **016 skill-market-hardening**（13/15）：异常口径、打分权重、租户灰度、降权行为、20% 回滚、0.4/7天、数据源、最小样本、稳定版本、恢复路径、多版本归集（CHK006 矛盾上轮已修）。
  - **017 three-scope-memory**（12/15）：Workspace 粒度、默认策略、授权角色、衰减口径、三级可见性、001 治理点、离职处置、超限拒绝、多范围各存、检索过滤（CHK002 矛盾上轮已修）。
  - **018 capability-asset-registration**（12/15）：契约四段、扫描目标、3 态、owner 粒度、自动/人工分工、多对多 skill_refs、下线审批、旧版可查、去重键、视图下钻、owner 转移、a2a_exposed。
  - **019 harness-elastic-config**（13/15）：厚/薄层集合、三维 profile、审计粒度+超时、默认厚、优先级、可省/不可省、最小审计四元组、工具调用级生效、配置权、过渡挂载、中途切换。
- **19 份 checklist 现已全部 agent 代审并勾选**，P0/P1/P2 质量层完全一致。剩余未勾项**高度集中于跨特性双向声明**（012↔001/018、013↔001/002、014↔005/015/001、015↔005/014/001、016↔004/011、017↔005/002/006、018↔004/012/001、019↔001/009），需相关 spec 互相确认。
- 更新 `specs/INDEX.md`：checklist 行改为 19/19 全代审；"五（补2）"表补齐 P2 八行 + 更新共性结论；SDD 路径 P2 行标注已评审勾选。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。改 `specs/**/spec.md`（FR 回填）+ `checklists/requirements.md`（勾选+评审结论）+ `INDEX.md`，未改 services/apps 源码。

## 2026-07-08 回填 + 评审勾选 P1 特性 002/009/010/011 的 checklist（agent 代审）

- 对 P1 四个特性走与 P0 相同流程：先逐条判定 checklist，把"clarify 已定未回填 FR"+"可消解边界缺口"回填进 spec，再勾真正达标项：
  - **002 session-versioning**（12/16）：回填触发条件 / resume seq 续编 / share 权限转移+失效空态 / co-presence 冲突乐观锁 / 秘密判定 熵≥3.5+前缀 / 独立 `session_snapshots`+附件引用 / 审计字段 / 解引用定义 / 离线贡献保留。余 4 项跨特性（002↔001/009/011/005）。
  - **009 hooks-interception**（11/16）：回填三规则语义 / 作用域叠加合并 / fail_closed 不可配+observe 例外 / 首期仅 PreToolUse / 超时 5s / 解析失败三类 / deny 返回 403 区分 / 生效时机 / 求值顺序。余 5 项（五事件数据、跨特性 001/002/019、延迟预算）。
  - **010 dag-orchestration**（13/16）：回填节点数据传递 / 并发度 4+排队 / 跳过追溯 / 阻塞下游闭包+blocked 态 / JSON 条件对象 / 版本字段 / 环路径格式 / 双轨迁移 / 语法错误 fail_closed / 节点原子语义 / supervisor 失败传播。余 3 项跨特性（007/009/002）+ 跨层并发预算。
  - **011 dream-cycle**（12/16）：回填片段字段 / Jaccard+编辑距离 / 测试定义 / 采纳率口径 / friction 默认捕获 / MR 目标 004 草稿目录 / 草稿vsMR 边界 / 淘汰恢复 / 草稿堆积上限 / 同片段去重 / 淘汰生效范围 / 生成侧质量门槛。余 4 项跨特性（004/002/016/010）。
- 累计 P0+P1 七份 checklist 已 agent 代审：001 15/18、007 10/15、008 13/15、002 12/16、009 11/16、010 13/16、011 12/16。**剩余未勾项高度集中于跨特性双向声明**，需相关 spec 互相确认。
- 更新 `specs/INDEX.md`：checklist 行标注 P0/P1 已评审勾选；新增"五（补2）P0/P1 评审 + FR 回填记录"表。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。改 `specs/**/spec.md`（FR 回填）+ `checklists/requirements.md`（勾选+评审结论）+ `INDEX.md`，未改 services/apps 源码。

## 2026-07-08 审阅并勾选 P0 特性 001/007/008 的 checklist（agent 代审）

- 按 `/speckit-checklist` 语义逐条判定 001/007/008 的 18+15+15 项需求质量，**只勾真正达标的，未达标如实保留 `[ ]`**（不滥勾）：
  - **001**：勾 4/18（CHK003 PII 5 类、CHK008 脱敏仅存指纹、CHK011 编号已订正、CHK015 并发竞态属实现细节）；14 项未勾 = 真实缺口（含 clarify 已定但 FR 正文未回填的 CHK009/010 + 未定义的级联/时区/矩阵表/预设组/超时动作 + 跨特性 006/019 对齐）
  - **007**：勾 3/15（CHK005 单供应商 no-op 可验证、CHK010 凭据口径、CHK015 抖动属实现细节）；12 项未勾 = 真实缺口（主/备判定、降级维度、成本单价表、clarify 已定退避/仅文本未回填 FR、跨特性 008 字段对齐）
  - **008**：勾 1/15（CHK013 N=4 上轮已补）；14 项未勾 = 真实缺口（去重键/时区/容差/异常枚举、clarify 已定人工介入率/P50P95/top-N 未回填 FR、跨特性 007/006 对齐）
- 诚实结论：**P0 三份 checklist 均未 100% 达标**，暴露出大量"spec 还没写到可 implement"的需求缺口，主要集中在 ①clarify 已定但 FR 正文未回填（高频）②跨特性字段/角色口径未双向对齐 ③矩阵取值表/级联/时区等边界未定义。
- 勾选态即 `/speckit-implement` 的拦截门禁；未勾项须先回填 spec 才能放行。各 checklist 已加"评审结论"节登记达标/缺口明细。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。仅改 `checklists/requirements.md`，未改 spec/services/apps 源码。

## 2026-07-08 生成 P0 缺口特性 001/007/008 的 tasks.md（为 implement 铺路）

- 按 `/speckit-tasks` 语义把 spec 用户故事 + plan 模块结构 + 已消解 OQ + checklist 门禁拆成可执行任务，P0 先走：
  - **001 gatekeeper**（32 任务）：Phase1 骨架/配置/协议/编排 → Phase2 基础表/审计/权限码模型 → US1 六层链 → US2 25 格矩阵 → US3 PII 脱敏 → US4 权限码管理 → US5 配额 → Polish。含 clarify 决策（审批复用 approval_runtime 不建表、MongoDB 配额、PII 全局默认+租户覆盖）+ checklist 门禁说明。
  - **007 llm-gateway-resilience**（25 任务）：Phase1 resilience 子模块骨架 → Phase2 provider 抽象/退避原语 → US1 failover → US2 降级链 → US3 退避 → US4 计量 → Polish。含 clarify 决策（tenacity 复用、1.5s/30s/±10%/3 次、仅文本模型、事件落 token_usage_logs）。
  - **008 ops-dashboard**（27 任务）：Phase1 数据源对齐 → Phase2 质量/趋势聚合补齐 → US1 总览 → US2 成本 → US3 使用 → US4 质量 → US5 趋势 → Polish。含 clarify 决策（人工介入率口径、P50/P95 数据源、瓶颈 top-N、N=4、DashboardPage 标签页）。
- 每份含：故事分阶段 + 依赖图 + 并行点 + MVP 范围 + 实现策略 + checklist 门禁提示；故事间按 P1→P2→P3 排序，MVP 取最核心故事。
- 更新 `specs/INDEX.md`：完成度统计新增 tasks 行（P0 三份完成），SDD 路径细化 P0/P1/P2 各自 tasks 状态。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。纯 spec 规划文件，未改 services/apps 源码。

## 2026-07-08 修正 checklist 暴露的 5 处 spec 缺陷（规约自洽化）

- 按"先修缺陷再进 tasks"，逐个研读对应 spec 段落并修正：
  - **001 编号订正**：Non-Goals 4 条特性引用订正（LLM 韧性 002→007、DAG 003→010、自进化 004→011、会话版本化 005→002）。确认 003/005 的交叉引用编号本就正确，错配仅在 001 自身。
  - **016 FR-4 对齐 clarify**：FR-4 + US3 由"按比例/用户"改为"首期按租户，按比例/用户为后续扩展"，消除与 clarify OQ-2 的矛盾。
  - **017 FR-3/FR-5 默认策略统一**：按 clarify OQ-1"单/多人会话"改写 FR-3（单人默认 personal、多人默认 workspace）与 FR-5（沉淀随会话类型），消除两条默认冲突。
  - **008 补 N 值**：US2 成本预测"N = 4 期（可配置 forecast_periods）"，新增 clarify OQ-5。
  - **010 补语法错误策略**：US3 + FR-4 定为"默认 fail_closed（跳过 + 审计），可配置报错中断"，新增 clarify OQ-5，与 009 钩子 fail_closed 底线一致。
- 更新 `specs/INDEX.md`"五（补）"节：缺陷表由"待修正"改为"✅ 已修"修正记录。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。纯 spec 文本订正，未改 services/apps 源码。

## 2026-07-08 为 001–019 补齐需求质量门禁 checklist（19/19 规约质量层一致）

- 按 `/speckit-checklist` 语义（"需求的单元测试"，校验 spec 质量而非实现）为尚无 checklist 的 15 个特性生成 `checklists/requirements.md`（001/002/007/008/009/010/011 + P2 012–019），每份含完整性/清晰度/一致性/边界与歧义四类条目（CHKxxx 编号，全未勾选，reviewer-owned）。与既有 003/004/005/006 保持同口径，**19/19 规约质量层一致**。
- 门禁作用：`/speckit-implement` 读勾选态作为拦截门禁；未勾选项须先消解。
- checklist 逐份研读 spec+plan+clarify 记录后生成，暴露 5 个需在 reviewer 审阅前修正的缺陷（登记进 INDEX "五（补）"节）：
  - **001 CHK011 一致性缺陷**：spec Non-Goals 特性编号引用错配（写"LLM 韧性属 002/DAG 属 003"，实际 007/010），连带 012/013/014 的"001 是否含本特性"需按正确编号核实
  - **016 CHK006 矛盾**：FR-4"灰度按比例/用户" vs clarify"首期按租户"，需按 clarify 修正 FR-4
  - **017 CHK002 矛盾**：FR-3"默认个人级" vs FR-5"会话沉淀默认 Workspace"，需按 clarify OQ-1 统一
  - 008 CHK013 / 010 CHK013：成本预测 N 值、表达式语法错误策略 两处完整性缺口
- 更新 `specs/INDEX.md`：完成度统计 checklist 改为 19/19；新增"五（补）缺陷登记表"；SDD 路径三行同步。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。未改 services/apps 源码。

## 2026-07-08 按 P0→P1→P2 顺序完成 001–019 全部 clarify（OQ 消解）

- 按 `/speckit-clarify` 语义（消解 spec 歧义 + 把答案编码回 spec/plan）逐个消解 19 个特性的 OQ，每个 spec 新增 "Clarify 记录" 节，对应 plan "Open Questions" 改为 "Open Questions（已 clarify 消解）"。OQ 答案基于代码事实，未臆造：
  - **P0（001/007/008）**：001 审批复用 `approval_runtime`（poll + 5min 超时）、配额用 MongoDB（不引入 Redis）、PII 全局默认 + 租户可覆盖；007 用既有 `tenacity`（requirements 已含，azure_gpt_image 已用）、退避 1.5s/30s/±10%/3 次、事件落 `token_usage_logs`；008 人工介入率=审批挂起数、P50/P95 取 `duration_ms`、瓶颈 top-N、DashboardPage 加标签页。
  - **P1（002/009/010/011）**：002 独立 `session_snapshots`、熵 ≥3.5 + 前缀双判定、不引入 Redis、share 联动 006；009 超时 5s、fail_closed 不可放行、首期仅 PreToolUse；010 JSON 条件对象（禁代码 AST）、并行度 4、节点/模型重试分层、双轨迁移；011 Jaccard ≥0.7 + 样本 ≥5 建 MR、14 天低采纳淘汰、与 016 共用标记位。
  - **P2（012–019）**：各自口径/阈值/依赖顺序已定（019 薄模式保留身份/RBAC/脱敏/审计/红线，可省审批/配额）。
- 关键依据（grep 核实）：`approval_events.py::EnterpriseApproval`（审批状态机 + risk_level）、`azure_gpt_image.py` 的 tenacity 退避参数、`requirements.txt::tenacity>=8.3.0`、`dashboard.py::_duration_ms`、`scheduled_tasks/schedule.py` 的 once/daily/weekly 调度。
- 更新 `specs/INDEX.md`：完成度统计加入 clarify 19/19 + 关键消解摘要，去掉旧"待 clarify OQ"行。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。未改 services/apps 源码。

## 2026-07-08 补 012–019 的 plan.md（完成全部 19 份技术契约）

- 为 8 个 P2 后置缺口特性补 plan.md（基于已研读代码事实的挂载点设计，均标注 P2 后置 + 各自 OQ）：
  - 012 a2a-agent-gateway：新增 `a2a/`（AgentCard + JSON-RPC + 客户端），复用 `enterprise_capabilities/tools` 执行后端 + `governance` 鉴权审计
  - 013 multi-im-entry：新增 `im_gateway/`（渠道 adapter + 会话映射 + 路由），首期 1 渠道，复用 Workspace/Sandbox/001 治理
  - 014 business-semantic-index：新增 `business_index/`（连接器 + 实体抽取 + 增量 + 对齐），复用 005 `knowledge/retrieval` 检索与引用锚点
  - 015 knowledge-graph-layer：新增 `knowledge_graph/`（抽取 + 存储 + 多跳 + 一致性），首期 MongoDB 邻接模拟图，与 005 RAG 并行融合
  - 016 skill-market-hardening：新增 `admin-api/services/skill_market/`（监控 + 打分 + 灰度 + 标记），在 004 `skill_lifecycle` 之上叠加，复用审计 + token_usage + scheduled_tasks
  - 017 three-scope-memory：新增 `memory/`（三级范围 + 可见性 + 升级授权 + 沉淀），复用 005 个人知识 + 002 会话 + governance 授权
  - 018 capability-asset-registration：新增 `capability_assets/`（发现 + 注册 + 版本 + 治理视图），复用 `enterprise_capabilities/tools` 契约 + 审计 + position_roles
  - 019 harness-elastic-config：新增 `harness_config/`（厚度 schema + 层开关 + 底线守护），是 001 六层门禁的"启用哪几层"开关层，红线 + 审计不可降档
- 每个 P2 plan 均登记 4–5 个 OQ（阈值/口径/依赖顺序），供后续 clarify 消解。
- 更新 `specs/INDEX.md`：012–019 plan 列由 ⏳ 改 ✅，完成度统计改为 spec 19/19 + plan 19/19（全部技术契约齐全），SDD 路径同步。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。未改 services/apps 源码。

## 2026-07-08 为既有回溯特性 003/004/005/006 生成需求质量门禁 checklist

- 按 `/speckit-checklist` 语义（"需求的单元测试"，校验 spec 质量而非实现）为 003/004/005/006 各生成 `checklists/requirements.md`（4 份），每份含完整性/清晰度/一致性/边界与歧义四类条目（CHKxxx 编号，全未勾选）。
- 门禁作用：`/speckit-implement` 读取勾选态作为拦截门禁；未勾选项须先消解（多为跨特性口径对齐 + 各 plan 的 OQ）才能放行。
- 条目聚焦暴露 spec 的质量缺口，关键跨特性对齐项已标注：
  - 003↔001（审计联动依赖）、003↔005（候选片段来源）
  - 004↔006（"角色授权"口径）、004↔001（权限码过渡）、004↔016（市场强化边界）、CHK002 签名是否真实存在（须 clarify 定论）
  - 005↔002（知识分享 vs 会话交接）、005↔003（候选片段来源）、005↔001（检索授权）
  - 006↔001（岗位角色→权限码预设组）、006↔004（角色概念一致）、006↔019（厚度叠加）
- 更新 `specs/INDEX.md`：完成度统计加入 checklist（4 份），SDD 路径既有回溯链改为 spec→plan→checklist→tasks→analyze，并登记跨特性口径对齐待消解项。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。未改 services/apps 源码。

## 2026-07-08 补 007–011 的 plan.md + P2 后置清单建 spec（012–019）

- 补 5 份缺口特性 plan.md（基于已研读代码事实）：
  - 007 llm-gateway-resilience：`llm/resilience/` 子模块（failover/降级链/退避），计量复用既有 token_usage 管线
  - 008 ops-dashboard：在既有 dashboard.py/analytics.py 上补"质量/趋势"两维度，前端扩四维看板
  - 009 hooks-interception：`dsh_runtime/hooks/` 五事件注册 + fail_closed，挂载复用 turn_admission/gateway/approval_runtime
  - 010 dag-orchestration-engine：新增 `orchestration/` 通用引擎，content/planning 作为迁移参照
  - 011 dream-cycle-self-evolution：新增 `self_evolution/`，复用 scheduled_tasks/skills_specs/004 skill_lifecycle
- 新建 8 份 P2 后置清单 spec（规划文档 §清单 8–15，对应 12 的沉淀闭环已并入 011）：
  - 012 a2a-agent-gateway / 013 multi-im-entry / 014 business-semantic-index / 015 knowledge-graph-layer / 016 skill-market-hardening / 017 three-scope-memory / 018 capability-asset-registration / 019 harness-elastic-config
- 更新 `specs/INDEX.md`：新增"P2 后置清单"分组（012–019），修正完成度统计（spec 001–019 全 19 份；plan 001–011 共 11 份，012–019 待补）与 OQ 汇总
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。未改 services/apps 源码。

## 2026-07-08 补全全部特性规约（spec 007–011 + plan 002/005/006 + INDEX）

- 新建 5 份缺口特性 spec（规划文档 §2/§3 补强清单）：
  - 007 llm-gateway-resilience（清单 2，P0）：failover/降级链/指数退避/计量
  - 008 ops-dashboard（清单 3，P0）：成本/使用/质量/趋势四维驾驶舱
  - 009 hooks-interception（清单 4，P1）：五事件 Hooks + fail_closed + 声明式规则
  - 010 dag-orchestration-engine（清单 5，P1）：四模式/拓扑/环检测/条件跳过/节点重试
  - 011 dream-cycle-self-evolution（清单 7，P2）：friction 沉淀/模式扫描/草稿建 MR/低采纳淘汰
- 补 plan.md 至已有 spec：002 session-versioning、005 knowledge-rag-research、006 position-rbac-admin（均基于既有代码事实：sessions.py versions/seq、knowledge/ citation 复合键、position_roles 集合）
- 新建 `specs/INDEX.md` 总览：既有回溯（003/004/005/006）与缺口新特性（001/002/007–011）分组，标注 spec/plan 完成度、对应规划条目、代码位置、待 clarify 的 OQ 汇总
- 规约完成度：spec.md 001–011 全完成（11 份）；plan.md 001/002/003/004/005/006 完成（6 份），007–011 待补
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。未改 services/apps 源码。

## 2026-07-08 创建待确认清单目录 docs/pending-review/

- 按 AGENTS.md 代理操作规约中"无法判断的文件放入待确认清单"的约定，创建 `docs/pending-review/README.md`：定义收录规则（用途不明/疑似临时/与任务冲突/疑似废弃）、条目登记格式（路径/日期/发现者/疑点/建议/状态）、处置流程（用户拍板→代理执行→改 resolved）。
- 当前无待确认条目，台账为空。未改动 services/apps 源码。

## 2026-07-08 引入 Spec Kit SDD 规约 + 合并代理操作规约

- 初始化 specify-cli 1.0.8（claude skills 集成），生成 `.specify/`（模板/脚本/workflow）与 `.claude/skills/`（10 个 /speckit-* 技能；`.claude/` 按 .gitignore 不入库）。
- 写入项目 constitution `.specify/memory/constitution.md` v1.0.0（5 条核心原则 + 技术约束 + 工作流 + 治理）。
- 本次在 Development Workflow 后新增 **Agent Operating Rules（代理操作规约）** 一节，合并用户提供的 13 条代理行为约定（中文回复/思考、仅操作工作区、禁删文件、需确认先问、待确认清单、改后更新 WORK_LOG、只读最新 AGENTS.md/WORK_LOG.md、最小改动、不顺手重构、必要范围测试、出错先定位、远端写入边界只推 cooper2006/mogong）。constitution 版本升至 v1.1.0。
- 改动文件：`.specify/memory/constitution.md`（新增 Agent Operating Rules 节 + 版本号 1.0.0→1.1.0）。未改 services/apps 源码。
- 验证：constitution 为规约文档，无运行代码；`git diff` 仅该文件变更。

## 2026-07-08 回溯 SDD 规约：spec/plan 001–006

- 按 existing-projects 回溯方法为既有能力域补齐 SDD 规约，均提交并推送 cooper2006/mogong（origin/himovo push 已锁 no-push，未触碰）：
  - 001 gatekeeper-governance（缺口新特性）：spec.md + plan.md（含 3 个 OQ 待 clarify）。
  - 002 session-versioning（缺口新特性）：spec.md。
  - 003 document-ingestion-delivery（既有能力回溯）：spec.md + plan.md。
  - 004 skillhub-lifecycle（既有能力回溯）：spec.md + plan.md。
  - 005 knowledge-rag-research（既有能力回溯）：spec.md。
  - 006 position-rbac-admin（既有能力回溯）：spec.md。
- 远端：`git remote set-url --push origin no-push`，锁定不向 himovo 写入；推送走 mogong remote。

## 2026-09-22 将 movo-intro-v2 配色切为「极简单色」（黑白灰 + 单一电光青）

- 用户对「科技深空」仍不满意，指定方向「极简单色监听」：白底黑字 + 纯黑深底（封面/结束/挂载条/P2 band），**唯一电光青 `#12C2B0`** 作一律强调（标题竖条 / 证据 / ✓ / P0 / 最高优先级），其余全部灰阶。
- 优先级用「青实底 / 中灰 / 纯黑」分层：P0=电光青实底、P1=中灰 `#7B8491`、P2=纯黑；删去除青以外的所有彩色。
- 改动集中在 `/tmp/movo-ppt-build/gen-deck.mjs`：T tokens 收敛为黑/灰阶+单青（teal/amber/blue 同指电光青）；P4 GAP 与 P9 路线图 P1 由 teal→gray；P7 三卡顶条改「首卡青、余灰」；P8 Dream 步骤序号首步青、余灰。
- 结构校验仍通过（10 页、404 形状 0 越界、无畸形占位符）；LibreOffice→PDF→PyMuPDF 全页重渲染 + 蒙太奇总览确认整体协调。

## 2026-09-22 调整 movo-intro-v2 配色为「科技深空」+ 切微软雅黑字体

- 按用户指定方向「科技深空」重配色：深靛蓝 `#141B38`（封面/结束/挂载条）→ 品牌蓝 `#3D7BFF`（标题竖条）→ 电光青 `#11A8CC`（证据/强调/filled）→ 品红紫 `#A93DDF`（P0/最高优先级），内容页白底、浅蓝灰卡 `#F0F4FC`；头部 label/文本微调为深靛蓝系。
- 字体已由上版切为微软雅黑（`FONT_CN = "Microsoft YaHei"`），跨 Windows/WPS 通用。
- 仅改 `/tmp/movo-ppt-build/gen-deck.mjs` 的 design tokens（T 对象）+ header tick 锚点色，其余布局未动；重生成后结构校验通过（10 页、404 形状 0 越界、无畸形占位符），LibreOffice→PDF→PyMuPDF 全页重渲染 + 蒙太奇总览确认协调。
- 产物原位更新：`outputs/movo-intro-v2/movo-intro-v2.pptx`（含 PDF 预览与各页 PNG）；未改动源码与旧版产物。

## 2026-09-22 重做 MOVO 介绍 + 补强规划整合版 PPT（movo-intro-v2）

- 用户对 `outputs/movo-intro/movo-intro.pptx`（15 页）不满意（视觉不够高级 / 结构混乱 / 信息过载 / 篇幅长），要求**整合「社区版介绍 + 功能补强规划」两块、精简到 8–10 页重做**。
- 采用 jingmei-ppt 视觉总监流程 + **咨询研报配方**（analytical / compressed / calm）：白底 + 藏青墨色 + 细灰线 + 结论先行 + 单页单一 claim；深藏青封面/结束遥呼，P0 用克制的琥珀（占位 ≤6%）。
- 产出 10 页决策稿 `outputs/movo-intro-v2/movo-intro-v2.pptx`：01 封面 → 02 定位与核心判断 → 03 差异化底座 → 04 六大缺口（P0/P1/P2）→ 05 P0·治理风控层 → 06 P0·网关韧性+驾驶舱 → 07 P1·Hooks/DAG/双版本化 → 08 P2·自进化与生态 → 09 三阶段路线图 → 10 结束页。
- 技术路线：PptxGenJS（`/tmp/movo-ppt-build`，全局无 perl-library 依赖），结构化为 design tokens + 组件（header/token 单行保护/panel/pill）+ 每页组合；短 token 走 `token()` 单行保护（wrap:false + fit:shrink）。
- 结构校验：10/10 页、404 个形状 0 越界、无畸形占位符；LibreOffice headless 转 PDF + PyMuPDF 渲染 10 页 PNG，蒙太奇总览 + 封面/最密页（P0 治理、P0 生产）全尺寸检查通过。
- 审查副产品（仅供查看，未引用）：`movo-intro-v2.pdf`、`montage.png`、`preview/sNN.png`。
- 未改动源码、services、apps 目录；`assets/`/`slides/` 等旧产物保留未动。

## 2026-09-22 补充「功能补强规划」4 页到介绍 PPT（完成）

- 依据 `docs/MOVO企业级智能体功能补强规划.md` 扩展 PPT：11 页 → 15 页，新增第 4 章节「04 · 功能补强」。
- 新增 4 页（本地 `slides/` 源文件已完成并通过 slidep lint）：
  - P11 现状与六大缺口（横向条列，P0 琥珀 / P1 主蓝 / P2 青三色标注）
  - P12 P0 三大最高优先级（深色 hero，左大卡"治理与风控层"跨行 + 右上"LLM 网关韧性" + 右下"数据驾驶舱"）
  - P13 三阶段实施路线图（三列阶段卡 + 贯穿原则横条）
  - P14 P1 能力深读 + P2 生态清单（上三卡 Hooks/DAG/双版本化，下深色横条列 P2 十项）
- 已同步更新：`slides/02.slide` 目录页新增第 4 章、全部 15 页页码统一为 `NN / 15`、`slides/15.slide` 结束页副标增加呼应语。
- 中途阻塞：写入前 7 页成功、随后 08-15 全部 `HttpTransportError: openFile network error`；约 3.5 小时后重试，等 30 秒后 `slidep upsert-dsl movo-intro-v1.pptx --page-index 10` 首次成功（返回 `presentation is not open` 后自动恢复），说明云端 openFile 服务瞬时故障已解除。
- 最终产物：`outputs/movo-intro/movo-intro.pptx` 15 页完整版本，逐页 lint 全部通过（15/15 `"ok":true`）；未修改的 15 份 `.slide` 源文件保留在 `slides/`；空的中间产物 `movo-intro-empty-backup.pptx`（13 KB）作为归档保留。


## 2026-09-22 同步主文档 §2.1/§2.5 grep 措辞至规划1 修正版

- 对 `docs/MOVO企业级智能体功能补强规划.md`（主文档，含 AgentGit 会话级维度）的 §2.1 与 §2.5 两处 grep 措辞，同步为 `docs/MOVO企业级智能体功能补强规划 (1).md` 上一轮已修正的版本：
  - §2.1 R0–R4 矩阵行：「grep 无 `risk_level`/`rbac`/`autonomy` 命中」→「无分级矩阵（grep 无 `risk_level` 矩阵 / `risk_level × autonomy` 联合命中；`risk_level` 仅散落于 `enterprise_capabilities/tools`、`events/tool_presentation` 等业务模块）」。
  - §2.5 Dream Cycle 行：「grep 无 `learnings`/`dream`/`jaccard` 命中」→「无通用记忆自进化（grep 无 `learnings`/`dream`/`jaccard` 命中；`learning` 命中集中在 `browser/engine/workflow_cache`，属浏览器工作流缓存，非框架层）」。
- 复核主文档内其它 grep 表述（`circuit_break`/`degradation_chain`、`dag`/`topological`/`cyclic`、`hooks`）与 `services/` 验证结果一致，无需再改。
- 两份文档 grep 措辞现已完全一致；实质差异仅为主文档多含 AgentGit 会话级维度（§2.6、P1 第 6 项、P2 第 12 项、路线图、落地建议）。
- 未改动源码、services、apps 目录。



- 对 `docs/MOVO企业级智能体功能补强规划 (1).md` 的 §2.1 与 §2.5 两处表格描述做了最小修正，其余正文/结构未动：
  - §2.1 R0–R4 矩阵行：「grep 无 `risk_level`/`rbac`/`autonomy` 命中」→「无分级矩阵（grep 无 `risk_level` 矩阵 / `risk_level × autonomy` 联合命中；`risk_level` 仅散落于 `enterprise_capabilities/tools`、`events/tool_presentation` 等业务模块）」——避免与上一轮 grep 验证事实冲突。
  - §2.5 Dream Cycle 行：「无记忆自进化/经验沉淀（grep 无 `learnings`/`dream`/`jaccard` 命中）」→「无通用记忆自进化（grep 无 `learnings`/`dream`/`jaccard` 命中；`learning` 命中集中在 `browser/engine/workflow_cache`，属浏览器工作流缓存，非框架层）」——补上 `learning` 命中的实际位置。
- 复核规划1全文其它 grep 相关表述（`failover`/`circuit_break`/`degradation_chain`/`dag`/`topological`/`cyclic`/`hooks`），与 `services/` grep 结果一致，无需再改。
- 未改动源码、services、apps 目录。



- 在 `docs/MOVO企业级智能体功能补强规划.md` 末尾新增「§六、对标 EntAgent 可补充进 Movo 的功能（按价值排序）」，含 6.1 治理风控层、6.2 LLM 网关韧性、6.3 可扩展 Hooks、6.4 通用 DAG 编排、6.5 Dream 自进化、6.6 反向确认、6.7 落地优先级；原 §一–§五 结构与正文未动。
- grep 核实（`services/` 内）：`failover`/`circuit_break`/`degradation_chain` 0 命中、`topological`/`DAG` 0 命中、`rbac` 字样 0 命中；`risk_level` 仅散落 `enterprise_capabilities/tools`，`autonomy` 无业务命中；`hook` 命中全在业务代码（浏览器 rules、图像生成），非框架层；`learning` 命中集中在 `browser/engine/workflow_cache`，`dream`/`jaccard` 0 命中。文档结论据此表述为「无统一 X，已有 X 作挂载点」。
- 同步更新两处：顶部 `> 依据` 追加 EntAgent 对标来源；§四 实施路线图 P0/P1/P2 行追加 EntAgent 对标章节映射；「附：知识库核心参考来源」追加 EntAgent 安全闭环等参考。
- 未改动源码、services、apps 目录。

## 2026-09-22 制作 MOVO 社区版介绍 PPT

- 基于 `README.md` / `README.zh-CN.md` 内容，用 tencent-pptx 技能产出 11 页去代码化介绍 PPT，面向同行技术人员（企业自用智能体平台使用者）。
- 产出位置：`outputs/movo-intro/`（`movo-intro.pptx`、`STORY.md`、`DESIGN.md`、`slides/*.slide`、`assets/`）。未改动项目源码与 services 目录。
- 设计：科技蓝白配色（主 `#3B82F6` / 辅 `#06B6D4` / 强调 `#F59E0B` / 深底 `#0F172A`），11 页含 3 个 hero 页（封面、能力总览、结束页）。
- 复用项目自带素材：`movo-logo.png`（页脚 L3 角标）、`docs/assets/dsh-movo-responsibilities-zh-cn.png`（第 4 页 DSH/MOVO 分工主视觉）。封面与结束页背景图 ImageGen 两次均带"AI生成"水印，按规则改用 SVG 兜底。
- 全部 11 页 `slidep lint` 通过、已写入 pptx；第 7 页（七大能力）初版 6 卡横排触发 child-containment 溢出，改为 3 列 × 2 行 + 缩短文案后通过。
- 内容边界：保留"社区许可证非 OSI 开源、不可白标/OEM"的准确表述，未夸大开源程度。


## 2026-09-22 切换 OrbStack Docker 环境并启动全部服务

- 停止本地源码开发方式（dev.sh 及 8000/8100/8101/8200/3000/3100 端口服务），切换到 Docker 环境。
- 确认 OrbStack daemon 运行正常，`/usr/local/bin/docker`（OrbStack 注入）与 Compose v5.1.2 可用；DSH 沙箱 PATH 缺 docker，统一在命令中显式 `export PATH=/usr/local/bin:$PATH` 或 `DOCKER_BIN=/usr/local/bin/docker`。
- `~/.orbstack/config/docker.json` 已有国内 registry-mirrors（腾讯云/USTC/dockerproxy/1ms.run），daemon 已生效；拉取期间出现腾讯云源 Bad Gateway 与 short read，重试后 alpine:3.21、mongo:6.0.20、weaviate、ghcr 镜像全部就绪。
- `./movo --lang zh-CN up` 完成：bootstrap/mongo/redis/weaviate/dsh-runtime-host/chat-api/admin-api/document-api/document-worker/admin-web/user-web/gateway 全部 running（多数 healthy），入口 http://localhost:3000 与 /admin/setup 均返回 200。
- 此前本地开发阶段修改保留：三个 services 下的 `.env`（MONGODB_URI 指向本机 27017）、chat-api venv 的 motor 3.7.1/pymongo 4.18.1、admin-api 五处 `db is not None` 真值判断修复、user-web 与 admin-web 的 `pnpm-workspace.yaml` allowBuilds 开启（均为 dev.sh 源码模式需要；不影响 Docker 部署）。
- 下一步：访问 http://localhost:3000/admin/setup 完成首次初始化（企业管理员凭据由 setup 向导创建，无预置账号）。

## 2026-09-22 熟悉文档并尝试启动应用

- 已阅读 `README.md`、`README.zh-CN.md`、`dev.sh`、`dev_dsh.sh`、`CONTRIBUTING.md`、`docker-compose.yml` 与 `docs/docker-deployment.md`，确认官方启动入口为 `./movo up`，本地源码开发入口为 `./dev.sh` 或 `./dev_dsh.sh`。
- 已在本机执行 `./movo --lang zh-CN up`，启动器因“未找到 Docker”失败。
- 检查发现本机缺少 Docker、Docker Desktop、Docker Compose、Redis 与 Homebrew，因此当前环境不满足推荐启动条件；未继续执行 `./dev.sh` 以免缺少依赖后产生不完整启动。
- 下一步：安装并启动 Docker Desktop（或 Docker Engine + Docker Compose v2），确保至少 8 GB 可用内存和 20 GB 可用磁盘，然后执行 `./movo up` 后访问 `http://localhost:3000/admin/setup`；若选择本地源码开发，需要先安装并启动 Redis，再执行 `./dev.sh`。
