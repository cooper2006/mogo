# MOGO SDD 全量 QA 审计报告（standard 深度）· 2026-11-11

- **审计对象**：`specs/` 下全部 **54 个特性**（001–053 + 055；054 资源中心由其它会话在途、磁盘未落地），核验宣称「全流程已就绪，可进入 PR 评审与版本发布——库能力、生产接线与治理资产齐备」
- **审计深度**：`standard`（对齐 QualityForge / 11-04 / 11-06 / 11-09 口径：需求门禁 → 设计 → 实现任务 → 代码 → 测试 → 生产接线 → 文档一致性 → 保留项）
- **审计日期**：2026-11-11
- **权威环境**：**kiri**（`docker context show = kiri`）。生产栈已由 11-09 的 compose dev 切换为 **k3s**：10 个 Pod Running，8 个业务镜像全部 `ghcr.io/mogoai/<svc>:83bd0973`，数据后端为 **ServeBay Mongo**（`host.docker.internal:27017`，库 `mogo_dev`，已归一为「只认 32-hex」终态）。所有服务级验证在 kiri 容器 / k3s Pod / 容器网络内完成；宿主 Python 仅用于静态扫描与静态工具（用项目 venv）。
- **本轮换维**：11-09 验的是「版本发布就绪 + 治理资产有效性」，覆盖 001–049。**本轮换到最没被验过的三块**：① 新增 5 个特性（050/051/052/053/055）的 SDD 五件套、代码落点与跨特性副作用；② ID 归一阶段 2 落地后、k3s 生产栈下的运行态一致性与数据终态；③ 治理守卫在新生产栈下是否仍为真守卫。
- **逐条勾说明**：每项带 `[ ]`，reviewer 可逐项勾选。状态用词：`通过` / `保留` / `缺口` / `已修复` / `未修`。**未验证的项一律留空并写明原因，不假通过。**
- **配套报告**：`docs/regression-arm-kiri-2026-11-11.md`（kiri 三轮回归 R1/R2/R3 逐项明细）

---

## 0. 一句话结论

- [x] **文档层 / 代码层 / 测试层 / 生产接线层：发布就绪**。kiri 三轮回归中 R2/R3 全绿且**测试计数零偏差**：A6 三服务每轮 **5088 passed / 8 skipped / 0 failed**，A4 **339 passed / 9 skipped**，A1–A5、A7 除两个预期 SKIP（`drift` / `verify` rc=2）外全部 rc=0。唯一非测试计数差异是生产库文档数每轮 +14~16（A5 HTTP 冒烟落库副作用，已按 §4.3 逐集合归因，**非回归漂移**）。
- [x] 本轮共发现 **11 项问题**，**已修复 9 项**（含 1 项 P1 数据隔离缺陷、1 项 P1 守卫假通过、4 项 P2 文档/契约/测试一致性、3 项 P3 口径与遗留），**如实登记未修 2 项**（均 P3、需补依赖/按规约不动历史存档）。
- [x] **发布收口已完成**：本轮修复提交 `e883aab5` 并推送 `mogo/main`，随后重建 7 个业务镜像（tag `e883aab5`）、导入 k3s containerd、部署 8 个业务 Deployment，运行态镜像 tag **8/8 = HEAD**，`tag_mismatch=0`；并补跑 A1/A2/A4/A6 全绿、与 R3 计数零偏差。详见 §12。

---

## 1. 审计口径与基线

### 1.1 D1–D8 维度（每条可勾）

- [x] **D1 需求质量门禁** — 54 特性 `checklists/requirements.md` 存在性与勾选状态全量重扫
- [x] **D2 设计完备性** — 54 特性 `plan.md` 存在且非空
- [x] **D3 实现任务落地** — 54 特性 `tasks.md` 勾选率全量重扫（不沿用 11-06/11-09 旧数字）
- [x] **D4 代码落地与防回归** — 新增 5 特性代码落点抽样 + 050–053 跨特性副作用（租户清除清单）+ 11-09 修复防回归
- [x] **D5 测试全绿** — kiri 三轮全量 pytest（三服务、真实隔离库）+ A4/A5 回归集
- [x] **D6 生产接线** — k3s 运行态与 HEAD、网关契约、安全基线、漂移/产物守卫有效性
- [x] **D7 文档一致性与版本口径** — 7 处版本来源 + MCP + OpenAPI 快照 + README 中英 / INDEX / PPT / CHANGELOG / 32-hex 契约口径
- [x] **D8 已知保留项与发布阻塞** — 诚实登记环境类、维护窗口、人工凭据类与未修项

### 1.2 总览基线（本轮脚本实测，非引用）

| 指标 | 本轮实测 | 与 11-09 对比 |
|---|---|---|
| 特性总数 | **54**（001–053 + 055；缺 054） | 11-09 为 49，INDEX 写 53 → **口径陈旧** |
| 五件套 spec / plan / tasks / 门禁 / quickstart | **54 / 54 / 54 / 54 / 49** → 修后 **54/54** | 新增 5 特性缺 quickstart（已补） |
| `tasks.md` 勾选（全量 `- [x]` / `- [ ]` 行） | **1681 / 1696 = 99.12%** | 11-09 为 1549/1563（49 特性） |
| 100% 勾选特性 | **50** | 11-09 为 46 |
| 部分勾选特性 | **4**：017 41/46、024 112/119、049 23/25、051 29/30（共余 15 项） | 11-09 为 3 个 / 14 项 |
| 门禁清单严格口径 | **49 份 100%** + 003–006 四份 0 勾 + 017 四态表无 checkbox | 11-09 为 44 份（49 特性口径） |
| 版本来源（7 处 + MCP + 3 份 OpenAPI `info.version`） | **全部 0.2.7**，`v0.2.7` → `4cfca2af` | 一致 |
| k3s 运行镜像 vs HEAD | **8/8 全部 `83bd0973` = HEAD，tag_mismatch=0** | 11-09 的 N-1（8 处漂移）**已消除** |
| A6 全量 pytest（kiri 容器，R2/R3） | admin **1638 passed/1 skipped** + chat **3378 passed/1 skipped** + doc **72 passed/6 skipped** = **5088 / 8 / 0** | 11-09 为 4828（双服务） |
| A4 `deploy/tests` | **339 passed / 9 skipped** | 11-09 为 333/15（6 个 skip 是当时镜像漂移连带，已消除） |
| A2 `./mogo baseline` | **63 pass / 0 fail** | 一致 |
| A7 32-hex 终态 | `verify PASS`：`objectid_ids=0 / hex24_ids=0 / residual_hex24_values=0 / event_docs=0` | 本轮新增维度 |

### 1.3 方法学声明（诚实边界）

- [x] 原 QualityForge 964 项逐条判定文本未入库、工具不可用，本轮按文档化 `standard` 方法论对仓库内**可核验证据重新执行**，不逐字复刻。
- [x] `standard` 深度**不要求 54 特性逐文件行级穿透**；D4 采用「声明 + 抽样 + 防回归 + 全树扫描守卫」。
- [x] **以 kiri 为准**：A6 在 kiri docker daemon 的 `83bd0973` 生产镜像内跑，源码经 `-v /Users/cooper/mogo:/Users/cooper/mogo` 同路径挂载（覆盖工作区最新改动）；A1/A5 直接打 k3s Pod / 网关；A2/A3/A4 用宿主 venv + `docker context = kiri`（静态仓库守卫与契约工具，不依赖容器内 python 包）。
- [x] **三层口径分开记账（审计执行时点）**：① 审计执行时的已提交 HEAD `83bd0973`；② k3s 运行镜像 `83bd0973`（= 当时 HEAD，但不含本轮 QA 修复）；③ pytest 收集的是**工作区源码**（含本轮修复）。三者差异在 §5.4 / §11 单列，不混为一谈。**审计收尾后的状态变化**：修复单独提交使 HEAD 前进到 `e883aab5`，当时 k3s 镜像仍是 `83bd0973`，故 `A1_k3s` 的「8/8 tag = HEAD」为审计时点结论；短暂的 tag 不等号属「修复未部署」，不是 N-1 那类镜像漂移。**2026-11-11 11:23–11:32 部署收口后已恢复一致**：k3s 8 个业务镜像 tag 全为 `e883aab5` = HEAD，`tag_mismatch=0`（见 §12）。
- [x] 测试写入**隔离库** `mogo_regtest_20261111`（三轮复用同一库，验证自清理与幂等）；A5 HTTP 冒烟走运行中的 k3s admin-api，**连的是生产库 `mogo_dev`**：自建业务数据用完即删，但按审计合规保留的审计 / 会话 / 配置变更记录不删，故每轮生产库文档数 +14~16。三轮后业务集合仍 155 个、无结构污染、`verify` 三轮 PASS（见 §4.3 与 `docs/regression-arm-kiri-2026-11-11.md` §6）。

---

## 2. D1–D3 逐特性状态表（54 行，全量重扫）

> 列：五件套 `OK` = 存在且非空；勾选 = 已勾/总数。数据源 `/tmp/qa-d1d3-20261111.log`。

| ID | 特性 | spec | plan | tasks | quickstart | 门禁 | tasks勾选 | 门禁勾选 | 状态 |
|---|---|---|---|---|---|---|---|---|---|
| 001 | gatekeeper-governance | OK | OK | OK | OK | OK | 32/32 | 18/18 | 通过 |
| 002 | session-versioning | OK | OK | OK | OK | OK | 22/22 | 16/16 | 通过 |
| 003 | document-ingestion-delivery | OK | OK | OK | OK | OK | 35/35 | 0/20 | 保留（门禁未审） |
| 004 | skillhub-lifecycle | OK | OK | OK | OK | OK | 41/41 | 0/18 | 保留（门禁未审） |
| 005 | knowledge-rag-research | OK | OK | OK | OK | OK | 32/32 | 0/17 | 保留（门禁未审） |
| 006 | position-rbac-admin | OK | OK | OK | OK | OK | 33/33 | 0/17 | 保留（门禁未审） |
| 007 | llm-gateway-resilience | OK | OK | OK | OK | OK | 25/25 | 15/15 | 通过 |
| 008 | ops-dashboard | OK | OK | OK | OK | OK | 27/27 | 15/15 | 通过 |
| 009 | hooks-interception | OK | OK | OK | OK | OK | 19/19 | 16/16 | 通过 |
| 010 | dag-orchestration-engine | OK | OK | OK | OK | OK | 22/22 | 16/16 | 通过 |
| 011 | dream-cycle-self-evolution | OK | OK | OK | OK | OK | 19/19 | 16/16 | 通过 |
| 012 | a2a-agent-gateway | OK | OK | OK | OK | OK | 12/12 | 15/15 | 通过 |
| 013 | multi-im-entry | OK | OK | OK | OK | OK | 12/12 | 15/15 | 通过 |
| 014 | business-semantic-index | OK | OK | OK | OK | OK | 13/13 | 15/15 | 通过 |
| 015 | knowledge-graph-layer | OK | OK | OK | OK | OK | 12/12 | 15/15 | 通过 |
| 016 | skill-market-hardening | OK | OK | OK | OK | OK | 18/18 | 15/15 | 通过 |
| 017 | three-scope-memory | OK | OK | OK | OK | OK | 41/46 | 四态表无 checkbox | 保留 |
| 018 | capability-asset-registration | OK | OK | OK | OK | OK | 14/14 | 15/15 | 通过 |
| 019 | harness-elastic-config | OK | OK | OK | OK | OK | 15/15 | 15/15 | 通过 |
| 020 | platform-multi-tenancy | OK | OK | OK | OK | OK | 62/62 | 28/28 | 通过 |
| 021 | unified-context-address | OK | OK | OK | OK | OK | 10/10 | 15/15 | 通过 |
| 022 | security-hardening | OK | OK | OK | OK | OK | 58/58 | 18/18 | 通过 |
| 023 | observability-resilience | OK | OK | OK | OK | OK | 126/126 | 18/18 | 通过 |
| 024 | deployment-hardening | OK | OK | OK | OK | OK | 112/119 | 17/17 | 保留（7 环境项） |
| 025 | api-contract-hardening | OK | OK | OK | OK | OK | 52/52 | 25/25 | 通过 |
| 026 | performance-scalability | OK | OK | OK | OK | OK | 57/57 | 18/18 | 通过 |
| 027 | mongo-to-panweidb-migration | OK | OK | OK | OK | OK | 75/75 | 35/35 | 通过 |
| 028 | user-web-trajectory-tab | OK | OK | OK | OK | OK | 10/10 | 18/18 | 通过 |
| 029 | user-web-sso-receiver | OK | OK | OK | OK | OK | 20/20 | 18/18 | 通过 |
| 030 | ontology-data-permission | OK | OK | OK | OK | OK | 29/29 | 21/21 | 通过 |
| 031 | model-provider-discover | OK | OK | OK | OK | OK | 20/20 | 17/17 | 通过 |
| 032 | eval-gate | OK | OK | OK | OK | OK | 22/22 | 15/15 | 通过 |
| 033 | canary-rollout | OK | OK | OK | OK | OK | 22/22 | 15/15 | 通过 |
| 034 | credential-encryption | OK | OK | OK | OK | OK | 37/37 | 15/15 | 通过 |
| 035 | cost-attribution | OK | OK | OK | OK | OK | 35/35 | 15/15 | 通过 |
| 036 | trust-rating | OK | OK | OK | OK | OK | 29/29 | 16/16 | 通过 |
| 037 | unified-portal | OK | OK | OK | OK | OK | 31/31 | 15/15 | 通过 |
| 038 | egress-sandbox | OK | OK | OK | OK | OK | 34/34 | 15/15 | 通过 |
| 039 | visual-orchestration | OK | OK | OK | OK | OK | 33/33 | 16/16 | 通过 |
| 040 | model-tier-routing | OK | OK | OK | OK | OK | 20/20 | 16/16 | 通过 |
| 041 | connector-market | OK | OK | OK | OK | OK | 24/24 | 16/16 | 通过 |
| 042 | three-level-quota | OK | OK | OK | OK | OK | 25/25 | 16/16 | 通过 |
| 043 | session-replay | OK | OK | OK | OK | OK | 21/21 | 16/16 | 通过 |
| 044 | multi-agent-modes | OK | OK | OK | OK | OK | 26/26 | 16/16 | 通过 |
| 045 | asset-center | OK | OK | OK | OK | OK | 15/15 | 19/19 | 通过 |
| 046 | project-dimension | OK | OK | OK | OK | OK | 34/34 | 23/23 | 通过 |
| 047 | quota-discoverability | OK | OK | OK | OK | OK | 30/30 | 19/19 | 通过 |
| 048 | business-line-removal | OK | OK | OK | OK | OK | 13/13 | 16/16 | 通过 |
| 049 | project-members | OK | OK | OK | OK | OK | 23/25 | 19/19 | 保留 |
| 050 | sop-human-handoff | OK | OK | OK | **补齐** | OK | 27/27 | 16/16 | 通过 |
| 051 | digital-employee-profile | OK | OK | OK | **补齐** | OK | 29/30 | 17/17 | 保留（T028 人工） |
| 052 | team-collaboration-mode | OK | OK | OK | **补齐** | OK | 22/22 | 17/17 | 通过 |
| 053 | plaza-template-distribution | OK | OK | OK | **补齐** | OK | 29/29 | 17/17 | 通过 |
| 055 | menu-management | OK | OK | OK | **补齐** | OK | 25/25 | 20/20 | 通过 |

### 2.2 结论（逐条勾）

- [x] **D1** 54/54 门禁文件存在；49 份严格口径全勾 + 003–006 四份既有回溯未审 + 017 v3 Gate 四态表（无 checkbox）。新增 050/051/052/053/055 五份门禁全部 100% 勾选。
- [x] **D2** 54/54 `plan.md` 存在且非空。
- [x] **D3** 50/54 `tasks.md` 100% 勾选；017/024/049/051 余 **15 项**均为环境类 / 维护窗口 / 人工凭据类保留，已逐项核实，非懒勾。
- [x] **五件套缺口已闭合**：修前 `quickstart.md` 49/54，本轮补齐 5 份后 **54/54**（与 README「每个特性含完整规格链路」宣称一致）。
- [ ] 003–006 门禁清单仍为 0 勾（既有回溯，2026-10-03 判定 `partial`；非本轮引入，发布说明须标注）。
- [ ] 054 资源中心由其它会话在途，磁盘无目录；待落地后须按发布流程再重扫 specs 计数与 tasks 勾选数。

---

## 3. D4 代码落地、跨特性副作用与版本口径

### 3.1 新增 5 特性的代码落点抽样（逐条勾）

- [x] **050** `app/orchestration/human_approval.py`、`run_store.py`（`orchestration_runs`）、user-web `ApproverPicker.vue` / `NodePropertyPanel.vue`；`tests/orchestration/test_human_approval.py`。
- [x] **051** admin-api `app/employees/` + `app/api/routes/employees.py`、chat-api `app/api/endpoints/employees.py` 与 `app/im_gateway/routing.py`；`tests/test_employees.py` / `test_employee_credentials.py` / `test_employee_tenant_identity.py`。
- [x] **052** chat-api `app/orchestration/team.py`（第七模式 `team`、黑板、验收循环）；`tests/orchestration/test_team.py`。
- [x] **053** admin-api `app/services/templates/` + `app/api/routes/templates.py`、chat-api `app/api/endpoints/plaza_templates.py`、user-web `src/plaza/PlazaPage.vue`；`tests/test_plaza_templates.py` / `test_plaza_clone_consumer.py`。
- [x] **055** admin-api `app/menu_settings/` + `GET|PUT|DELETE /api/v1/settings/menus`、admin-web `MenuManagePage.vue` / `menuConfig.ts`；`tests/test_menu_settings.py`。

### 3.2 跨特性副作用（本轮 P1 发现，逐条勾）

- [ ] **修前**：050–053 新增 7 个带标量 `tenant_id` 的集合未纳入 `tenant_purge.TENANT_SCOPED_COLLECTIONS`，租户删除后会残留并被同 ID 重建的租户读到 → 见 F-1。
- [x] **修后**：7 个集合全部纳入；`test_tenant_purge.py::test_every_tenant_id_keyed_collection_in_the_tree_is_covered` 全树扫描守卫由 **1 failed → passed**，单文件 30 passed。
- [x] `setup_cleanup.SETUP_SCOPED_COLLECTIONS` 经核实是「setup 管道实际写入集合」的刻意子集，不需要同步；同时更正 `tenant_purge.py` 注释里把它误标为 `services/chat-api/app/**` 的陈旧引用。
- [x] 11-09 的 7 项修复防回归：`tenant_purge` 的 `projects` / `memory_policies`、`test_session_end_lifecycle` 测试隔离、`path_naming`、compose `celery@$(hostname)`、Dockerfile `chmod -R a+rX` 均仍有效（由 A6/A4 全量覆盖）。

### 3.3 版本发布口径（逐条勾）

- [x] 7 处版本来源（2 份 `pyproject.toml`、2 份 `package.json`、3 份 `app/main.py` 的 `version=`）+ `MCP_CLIENT_VERSION` + 3 份 OpenAPI `info.version` = **全部 0.2.7**，与 `git tag v0.2.7`（→ `4cfca2af`）一致。
- [x] 运行态：`HEAD 83bd0973`，k3s 8 个业务镜像 tag **全部 = HEAD**（`tag_mismatch=0`）；11-09 的 N-1 镜像漂移已消除。
- [x] 32-hex 终态契约：040 `spec.md` / `checklists/requirements.md` 的 `admin_model_instances._id` 由 24-hex 改为 32-hex（见 F-6）；`model_router._MODEL_CONFIG_ID_RE` 与 `model_routing.yaml` 注释已是 32-hex。

---

## 4. D5 测试全绿（kiri 三轮实测，非声明）

### 4.1 A6 三服务全量 pytest（三轮逐轮）

| 轮次 | admin-api | chat-api | document-parser | 合计 |
|---|---|---|---|---|
| **R1（载体校准 / 缺陷发现）** | 1637 passed / 1 skipped / **1 failed** | 3369 passed / 1 skipped / **9 failed** | 72 passed / 6 skipped | 见 §4.4 归因 |
| **R2（修复后复验）** | 1638 passed / 1 skipped | 3378 passed / 1 skipped | 72 passed / 6 skipped | **5088 / 8 / 0** |
| **R3（稳定性 / 幂等复跑）** | 1638 passed / 1 skipped | 3378 passed / 1 skipped | 72 passed / 6 skipped | **5088 / 8 / 0** |

- [x] R2/R3 **测试计数完全一致**（逐服务 `1638 / 3378 / 72`），三轮复用同一隔离库 `mogo_regtest_20261111`，验证测试自清理与幂等、无状态泄漏；唯一差异见 §4.3 的生产库文档数增长，属设计内落库副作用。
- [x] chat-api 完整口径覆盖 Node 门控 e2e：从 `dsh-runtime-host:83bd0973` 导出 linux `node_modules`（613MB）+ node v24.22.2 二进制只读挂载，**未走 marker 过滤降级**。
- [x] 剩余 skip 均为环境性：admin-api `test_drill_credential_scripts.py` 硬编码 `127.0.0.1:27017`；chat-api `test_dsh_candidate_evaluation.py` 需容器内 git；document-parser 6 项依赖 celery/docling 运行时。

### 4.2 其他回归集（R2/R3 一致）

- [x] **A4** `deploy/tests`：**339 passed / 9 skipped**（与 11-08 权威基线一致；11-09 多出的 6 个 skip 由镜像漂移连带，本轮已消除）。
- [x] **A5** 030 本体权限：k3s Pod 内 smoke **12 passed / 0 failed**；mongo parity **8 passed / 0 failed**（`cleanup left=0`）。
- [x] **A3** 契约工具 10 项全绿：`path_naming` OK、`error_codes_uniqueness` 0 专属/15 通用、`error_code_mapping` 无 drift、`validate.py` 46/63/10 interactions、`consumer_refs --all`、`deprecation_check --all`、`diff.py` 自比对 0 breaking、`openapi/validate.py --all`（openapi-spec-validator + 内置 lint）、`openapi/probe.py --all` → `probe: OK`。
- [x] **A2** `./mogo baseline` **63 pass / 0 fail**（R1/R2/R3 三轮一致）。
- [x] **A7** 32-hex `verify` 三轮 PASS：`objectid_ids=0 / hex24_ids=0 / residual_hex24_values=0 / event_docs=0`；`natural_key_ids` 恒定 314，新增文档全部为新生成的 32-hex 主键。

### 4.3 生产库副作用核验（R3 实测校正）

- [x] 测试写隔离库；`mogo_dev` 业务集合恒为 **155 个**（另有 155 个 `__hex32_bak_*` 备份集合，来自 11-11 停机窗口），集合结构零变化。
- [x] A5 HTTP 冒烟走运行中的 k3s admin-api，会写审计事件（grant/save/delete/enforce_toggle）并 `PUT 复原 enforce=false`、自建 grant/detail 数据用完即删；但**按审计合规保留的写入不删**，故 `verify` 的生产库文档数三轮为 **3931 → 3947 → 3961**（R1→R2 +16、R2→R3 +14）。
- [x] **逐集合实测归因**（按 R2/R3 时间窗统计）：每轮约 `mesc_ontology_perm_audit` +7、`admin_sessions` +1、`sys_config` +1，其余落在无时间戳字段的工具 / 网关审计集合；增量全部是 32-hex 主键，`natural_key_ids` 恒定 314，`objectid_ids` / `hex24_ids` / `event_docs` 恒为 0。**属预期写入，非测试数据残留，不破坏 ID 归一终态。**
- [x] 交叉排除：`A5_parity` 写隔离库 `mogo_regtest_20261111`（该库三轮后 `mesc_ontology_perm_audit` 3 条，对应 `audit n=1/2/3`），未污染生产库；生产库中 `tenant_id=parity-030` 的 23 条记录 `ts` 均为 2026-11-05，属历史遗留。
- [x] 原 `test_ontology_permission_smoke.py` docstring 声称「用完即删」与实际不符，已修为如实说明保留项与线性增长（见 F-12 / §6）；**「R2/R3 零偏差」仅对测试计数成立**，须与生产库副作用分开记账。

### 4.4 R1 失败归因（不掩盖、不误判为产品回归）

- [x] **真实缺陷 2 项**：admin `test_tenant_purge` 全树扫描 1 failed（F-1）；chat `test_im_audit_events` 1 failed（F-2）。
- [x] **载体/环境 65 项**：A4 58 failed（容器内无 `docker` CLI，`docker compose config` 无法执行）；A3 `openapi/validate` 1 rc（镜像缺 `openapi_spec_validator`）、`probe` 1 rc（容器内 chat-api 依赖不全致 9 条路由误判 404，宿主 venv 同命令 = OK）；chat 8 个 DSH Host e2e（workspace 的 node_modules 非 linux 生产版本，启动退出码 1）。
- [x] 载体修正后全部消失，且**未修改任何产品代码来「适配」测试**：A4 改宿主 venv + `--basetemp`，A3 改带依赖的解释器，chat 改挂生产镜像的 linux node_modules。R2/R3 证明产品代码本身通过。
- [x] 因此 R1 定位为「载体校准 + 缺陷发现轮」，R2 为有效修后基线，R3 为稳定性轮；**R1 与 R2 的计数差不作产品回归解读**。

---

## 5. D6 生产接线

### 5.1 k3s 运行态与网关（逐条勾）

- [x] 10 个 Pod Running（8 业务 + redis + weaviate），内部 mongo 保持 0 副本；`docker context = kiri`。
- [x] 8 个业务 Deployment 镜像 tag 全部 `83bd0973` = HEAD，`tag_mismatch=0`（本轮新增 A1_k3s 实测项）。
- [x] 网关 `/` 200、`/admin/setup` 200、`/admin-api/health` 200、`/admin-api/api/setup/status`（`-L`）200、`/api/v1/auth/me` 401。
- [x] `./mogo baseline` 63/0：非 root / read_only / cap_drop ALL / no-new-privileges / user=10001 全通过。
- [x] `./mogo check`：dev profile 非外部库，无检查项（正常返回）。

### 5.2 治理守卫在新生产栈下的有效性（本轮二级发现）

- [ ] **修前**：compose dev 栈已整体停机、生产由 k3s 承载，`./mogo drift` 与 `./mogo verify` 却输出「比对 **0** 项 → **OK** — 与声明一致」。这是**误导性绿灯**：11-09 曾把 `drift FAIL` 当发布阻断，现在守卫什么都没验却报通过。
- [x] **修后**：两者在 `checked == 0` 时输出明确 `SKIP — 未发现任何运行中的 compose 服务，本次未执行比对` + 提示改用 kubectl 核对，并返回 **rc=2**；JSON 模式增加 `"status": "skipped"`。R2/R3 三轮一致（A1_drift / A1_verify 均为预期 rc=2）。
- [x] k3s 侧一致性改由 A1_k3s 实测覆盖（8/8 tag = HEAD），不依赖 compose 守卫。

### 5.3 契约工具与 025 quickstart 防回归

- [x] 11-09 修复的 `025/quickstart.md` 命令口径未回退；本轮 10 条契约命令全部实跑 rc=0。
- [x] `tools/contract/validate.py --service` 参数非 append，本轮逐服务调用（46/63/10 均 OK）。

---

## 6. D7 文档一致性（逐条勾）

- [x] **特性数口径全面陈旧 → 已修**：README.md 4 处、README.zh-CN.md 4 处、`specs/INDEX.md` 4 处、`docs/intro-v4.pptx` slide7/12/13 共 8 处文本，全部由 49（或 53）对齐到磁盘实测 **54 / 1696 项（已勾 1681 · 余 15）**；PPT `testzip()` 通过、改前备份 `/tmp/intro-v4.pptx.bak-20261111`。
- [x] **英文 README L106 漏改 → 已修**：原写 `Six of them (001, 007, 008, 009, 020)`（数字与列表不符，且实际 8 个），改为 `Eight of them (001, 007, 008, 009, 010, 020, 025, 026)`，与中文 README 的 8 个一致。
- [x] `specs/INDEX.md` 追加「2026-11-11 复核增补」节，记录 54 特性口径、五件套、勾选率、版本、k3s、32-hex 与修复清单。
- [x] `CHANGELOG.md` 在 `Unreleased` 追加 11-11 审计与 ID 归一阶段 2 条目（**未收归 v0.2.7**，因尚未发版；不改动已发布节）。
- [x] 补 5 份 `quickstart.md`，五件套 54/54 齐备。
- [x] **F-12 冒烟脚本 docstring 口径 → 已修**：`deploy/tests/test_ontology_permission_smoke.py` 原称「对自建的冒烟数据用完即删」，但实测每轮在生产库保留 7 条本体权限审计 + 1 条会话 + 1 条 `sys_config` 变更等，令 `mogo_dev` 文档数线性增长（3931→3947→3961）。现如实写明保留项、多轮回归影响与「隔离库执行 / 按时间窗评估清理」建议；并补 k3s `kubectl exec deployment/admin-api` 实际用法（原仅 compose 的 `mogo-admin-api-1`）。`py_compile OK`，宿主按设计 `1 skipped`，未引入收集错误。
- [x] 11-09 遗留 **N-12** 已处置：INDEX L261「029 未建」加复核注记（029 checklist 已建且 18/18），不动历史快照正文。
- [x] 11-09 遗留 **N-11** 已修：`./mogo baseline --json` stdout 为纯 JSON（`json.loads` 成功），普通模式仍显示人读诊断行。
- [ ] **N-8 CHANGELOG 收归**仍未执行：`Unreleased` 保留 11-04 QA 历史条目 + 本轮新增条目；按发布流程应在下次发版时收归入新版本节。
- [ ] **N-10** OTel instrumentation 依赖仍未声明（三服务 `requirements.in/txt` 无匹配）；本轮 k3s Pod 近 30 分钟日志 `Instrumentor init failed` 计数 0，tracing 降级**未复现**，但仍属未闭合项。
- [ ] **N-14** 历史存档文档 13 处根相对链接：按 AGENTS.md「WORK_LOG 停更、仅作历史存档」规约不动。

---

## 7. D8 已知保留项与发布阻塞（诚实登记，不假通过）

### 7.1 环境类 / 维护窗口 / 人工凭据类（15 项，逐条勾）

- [ ] **017**（5 项）：T031 双端真实浏览器 E2E、T042 切换演练 + `--reverse` 对账、T043 049 手工全链路、T045 M4 对账清理、T046 B/C 组
- [ ] **049**（2 项）：T022 全链路手工验证（需 admin 会话 + A/B/C 三账号）、T025 成员变更审计回归确认
- [ ] **024**（7 项）：T081 / T085 / T086 DR 演练、T106 压测容量、T107 扩容实测、B004 `mogo up` 全链路、B005 备份恢复真实模式
- [ ] **051**（1 项，新增）：T028「真实登录态 + 下拉选中具体员工发起会话」——自动化 SFC 10/10、双端 `vue-tsc` 0 错误、端点鉴权 401 均已证实，但该交互从未验证，且历史 200 依赖自签合成登录态（会话已删、不可复现），按 reviewer 意见保持 `[ ]`
- [ ] **026** T041 水平扩展压测、**023** RTO/RPO 真实实测值、**003–006** 既有回溯需求清单未审 —— 发布说明须标注
- [x] **027** 默认数据后端为 MongoDB；本轮生产实际接 ServeBay Mongo（k3s Secret 指向 `host.docker.internal:27017`），PanWeiDB 为可选开关，口径已在 CHANGELOG 明确

### 7.2 本轮新增保留 / 阻断（逐条勾）

- [x] **P1 发布前动作已完成**：本轮 9 项修复提交 `e883aab5`，7 个业务镜像重建为 `e883aab5` 并部署到 k3s，8/8 tag = HEAD；生产 Pod 内 `tenant_purge.TENANT_SCOPED_COLLECTIONS` 实测 95 项、050–053 的 7 个新集合全部在场，修复已真正进入运行态。详见 §12。
- [ ] **054 在途**：资源中心目录未落地，待其完成后按发布流程重扫 specs 计数与 tasks 勾选数。
- [ ] **N-8 / N-10 / N-14** 三项 P3 未修，须在发布说明标注。
- [ ] **F-12 残留（P3）**：`A5_smoke` 仍指向生产库 `mogo_dev`，多轮回归会让审计 / 会话 / 配置变更记录线性增长（实测 +14~16/轮）。文档口径已修，但「切隔离库」需改 k3s Pod 的 DB 配置（会动生产栈），超出本轮最小改动边界；已累积的审计日志按合规不直接删除，需人工评估。**不阻断发布**。
- [x] 11-09 的 **N-1（镜像漂移）已消除**：k3s tag 与 HEAD 零偏差；N-2 / N-6 / N-3~5 / N-7 / N-9 修复防回归有效。

---

## 8. 发现的问题清单（逐条可勾，含严重度）

| 编号 | 严重度 | 问题 | 位置 | 状态 |
|---|---|---|---|---|
| **F-1** | **P1** | 050–053 引入的 7 个租户集合（`asset_templates` / `template_clones` / `template_upgrades` / `employees` / `employee_api_keys` / `channel_employee_bindings` / `orchestration_runs`）未纳入租户清除清单，删除租户后跨服务数据残留（与 11-06 F-2 同类） | `services/admin-api/app/services/tenant_purge.py` | **已修复 + 全树扫描守卫复验** |
| **F-2** | **P1** | `./mogo drift` / `verify` 在 compose 栈停机（生产为 k3s）时「比对 0 项 → OK」，守卫假通过、误导发布门禁 | `deploy/cli/drift-check.sh`、`deploy/cli/verify-artifact.sh` | **已修复 + 三轮复验** |
| F-3 | P2 | 051 新增审计事件 `im.employee.route` 未同步测试白名单，chat-api 全量 1 failed | `services/chat-api/tests/services/test_t999_audit_t998_docs.py` | **已修复**（8 passed） |
| F-4 | P2 | 特性数口径全面陈旧：磁盘 54，README 中英 / INDEX / PPT / CHANGELOG 仍写 49 或 53；英文 README L106「Six of them」数字与列表均错 | `README.md`、`README.zh-CN.md`、`specs/INDEX.md`、`docs/intro-v4.pptx`、`CHANGELOG.md` | **已修复 + 逐处复核** |
| F-5 | P2 | 050/051/052/053/055 缺 `quickstart.md`，五件套仅 49/54，与「每个特性含完整规格链路」宣称矛盾 | 5 个 spec 目录 | **已修复**（补 5 份，复扫 54/54） |
| F-6 | P2 | 040 spec / checklist 仍写 `admin_model_instances._id` 为 24-hex，与 11-11「只认 32-hex」终态及代码冲突 | `specs/040-model-tier-routing/spec.md`、`checklists/requirements.md` | **已修复** |
| F-7 | P3 | 11-09 遗留 N-11：`./mogo baseline --json` stdout 混入 `Environment profile: ...`，`json.loads` 失败 | `mogo`、`deploy/cli/env-profiles.sh` | **已修复**（纯 JSON，普通模式不变） |
| F-8 | P3 | 11-09 遗留 N-12：INDEX L261「029 未建」与磁盘（029 已建且 18/18）矛盾 | `specs/INDEX.md` | **已修复**（加复核注记） |
| F-9 | P3 | 11-09 遗留 N-10：OTel instrumentation 依赖仍未声明（本轮日志未复现降级） | 三服务 `requirements.in/txt` | **未修**（需补 wheel + 重建镜像） |
| F-10 | P3 | 11-09 遗留 N-14：历史存档 13 处根相对链接 | `docs/WORK_LOG.md`、2026-10-01 回归报告 | **未修**（按规约不动历史存档） |
| F-11 | 载体 | R1 的 65 项失败属回归载体缺陷（容器无 docker CLI / 缺 validator / node_modules 非 linux 版），非产品代码 | 回归脚本与环境 | **已修载体**，见 §4.4 |
| F-12 | P3 | `test_ontology_permission_smoke.py` docstring 称「用完即删」，实际每轮在生产库保留 7 条本体权限审计 + 1 条会话 + 1 条 `sys_config` 变更等，令 `mogo_dev` 文档数 3931→3947→3961 线性增长；「R2/R3 零偏差」措辞失真 | `deploy/tests/test_ontology_permission_smoke.py`、本报告 §4.3 | **已修文档口径**（如实登记 + k3s 用法）；切隔离库列为 P3 保留，见 §7.2 |

---

## 9. 修复记录与复验证据

| 修复 | 文件 | 复验证据 |
|---|---|---|
| F-1 补 7 个租户集合 + 更正 setup_cleanup 跨服务引用 | `tenant_purge.py` | 定向 `test_tenant_purge.py` **30 passed**；R2/R3 admin 全量 **1638 passed / 1 skipped / 0 failed** |
| F-2 `checked==0` → 显式 SKIP + rc=2，JSON 加 `status` | `drift-check.sh`、`verify-artifact.sh` | `./mogo drift` / `verify` 均 rc=2 且输出 SKIP 提示；R2/R3 三轮一致 |
| F-3 审计枚举断言加 `im.employee.route` | `test_t999_audit_t998_docs.py` | 单文件 **8 passed**；R2/R3 chat 全量 **3378 passed / 1 skipped / 0 failed** |
| F-4 计数 49/53 → 54/1696，英文 contracts 6→8 | README×2 / INDEX / PPT / CHANGELOG | `grep` 残留 49 计数 **0**；PPT `testzip()=None`，slide7/12/13 文本逐条复核；CHANGELOG 新增条目 |
| F-5 补 5 份 quickstart | 050/051/052/053/055 | D1–D3 全量重扫 `f_qs: OK=54/54` |
| F-6 040 契约 24-hex → 32-hex | 040 `spec.md`、`checklists/requirements.md` | 与 `model_router._MODEL_CONFIG_ID_RE`、`model_routing.yaml` 注释一致 |
| F-7 `--json` 抑制 profile 诊断行 | `mogo`、`env-profiles.sh` | `./mogo baseline --json` → `json.loads` 成功（keys: items/pass/fail）；普通模式仍显示诊断行 |
| F-8 INDEX L261 复核注记 | `specs/INDEX.md` | 历史正文保留，新增「029 已建且 18/18」说明 |
| F-12 冒烟 docstring 如实登记生产库保留写入 + 补 k3s 用法 | `deploy/tests/test_ontology_permission_smoke.py` | `py_compile OK`；宿主单文件 `1 skipped`（按设计需 Pod 内 secret）；§4.3 逐集合实测归因 3931→3947→3961 |

- [x] 全部修复均为**本地最小改动**；审计执行时未提交，收尾后已随本次 QA 提交入库并推送 `mogo/main`；**未发版、未重建镜像**。
- [x] 未触碰其它会话在途的 6 个已修改文件（`authExpiry.ts`、`loader.py`、`test_human_approval.py`、051 `tasks.md`、053 `spec.md`、`06-deployments.yaml`）与 4 个未跟踪项（含真实密钥的 `03-secrets.yaml`、`docs/pending-review/`、两份 ServeBay 脚本）。
- [x] `docs/id-unification-hex32-runbook.md` 的改动属**同日阶段 2 停机窗口执行记录**（本次会话早前阶段产物），非本轮 QA 修复，但随本次提交一并入库；本报告引用其「只认 32-hex」终态与回滚口径，本轮 QA 未修改它。
- [x] 修复未引入回归：R2/R3 与 R1 的真实缺陷计数（2 项）一一对应闭合，其余**测试步骤**计数零偏差；生产库文档数增长已单列归因（§4.3），不作回归解读。

---

## 10. 发布就绪结论（逐条勾）

- [x] 54 特性 spec / plan / tasks / quickstart / 门禁五件套 **54/54** 齐备
- [x] 50/54 `tasks.md` 100% 勾选；15 项未勾均为环境 / 窗口 / 凭据类，诚实留空
- [x] 门禁清单 49 份全勾；003–006 既有回溯未审 + 017 四态表，口径已说明
- [x] 新增 5 特性代码落点抽样通过；跨特性租户清除缺陷已修并复验
- [x] 版本口径 7 处 + MCP + 3 份 OpenAPI + tag = 0.2.7 一致；32-hex 终态契约已同步
- [x] **kiri 三轮回归：R2/R3 每轮 A6 5088 passed / 8 skipped / 0 failed，测试计数零偏差**（26 步 rc 三轮一致，含 2 个预期 SKIP）
- [x] A1–A5、A7 除 `drift` / `verify` 两个预期 rc=2 SKIP 外全部 rc=0；契约工具 10 项、安全基线 63/0、网关 200/200/200/200/401
- [x] 本轮 **9 项**已修复问题均附复验证据，且未引入回归
- [x] 生产库副作用已逐集合归因：155 live + 155 backup 集合不变，`verify` 三轮 PASS，增量全为 32-hex 主键（§4.3）
- [x] 文档一致性错误（README 中英 / INDEX / PPT / CHANGELOG / 040 契约）已修
- [x] 11-09 的 N-1 镜像漂移已消除（k3s tag = HEAD），N-11 / N-12 遗留已闭合
- [x] **发布前动作已完成**：重建 7 个业务镜像 → 导入 k3s containerd → 部署 8 个 Deployment → 补跑 A1/A2/A4/A6 全绿（§12）
- [ ] **N-8 CHANGELOG 收归**、**N-10 OTel**、**N-14 历史断链** 三项 P3、**F-12 A5_smoke 仍写生产库** 一项 P3，与 15 项环境类保留，须在发布说明如实标注
- [ ] 054 落地后须重扫 specs 计数与 tasks 勾选数

**结论**：在 `standard` 深度下，**代码冻结与 PR 评审可进入，版本发布的技术收口已完成**——文档层、代码层、测试层（kiri 审计三轮 + 部署后完整复跑）、生产接线层（k3s 镜像 tag = HEAD、治理守卫有效性、网关 200/200/200/200/401）均达标，本轮修复已进入运行态且无回归。仅剩两类非阻塞事项：① 仓库 `deploy/k8s/generated/06-deployments.yaml`（其它会话在途）仍写 `83bd0973` 且 `mongo.replicas=1`，须由其所属会话同步；② N-8 / N-10 / N-14 / F-12 与 15 项环境类保留项，须在发布说明标注。

---

## 11. 本轮未修 / 需用户决定

| 项 | 为什么没修 | 建议动作 |
|---|---|---|
| **运行态与清单一致性（部署收口后）** | 已重建镜像并部署、运行态 8/8 tag = `e883aab5`；但仓库 `deploy/k8s/generated/06-deployments.yaml` 属其它会话在途改动，仍是 `83bd0973` + `mongo.replicas=1` | **待该会话同步**：把 tag 改为 `e883aab5`、`mongo.replicas` 改回 `0`；在此之前勿直接 apply 仓库清单，否则会回退 tag 并误启内部 Mongo。部署实际用的是临时清单 `/tmp/06-deployments.e883aab5.yaml`，回滚清单 `/tmp/06-deployments.rollback-83bd0973.yaml` |
| **N-10 OTel 插桩** | 离线 bundle 无 instrumentation wheel，补依赖需下载 + 改 requirements + 重建镜像，超出最小改动边界；本轮日志未复现降级 | 单独排期，当前不阻断 |
| **N-14 历史存档断链** | `docs/WORK_LOG.md` 自 2026-10-17 停更、仅作历史存档，按 AGENTS.md 规约不动 | 保持原样，报告已登记 |
| **N-8 CHANGELOG 收归** | v0.2.7 已发布，本轮未发版；把未发布内容写进已发布节不合口径 | 下次发版时按发布流程收归入新 `## vX.Y.Z` 节 |
| **F-12 A5_smoke 仍写生产库** | 文档口径已修；切隔离库要给 k3s Pod 换 DB 配置（会动生产栈），已累积审计日志按合规不直接删，超出最小改动边界 | 维护窗口把冒烟切隔离库，或人工评估后按时间窗清理；文档已如实登记，不阻断发布 |
| **15 项环境类保留 / 054 在途** | 需维护窗口、远端集群、真实浏览器、A·B·C 账号凭据；054 属其它会话 | 见 §7.1；054 落地后重扫计数 |

---

## 12. 发布收口记录（2026-11-11 11:14–11:38）

用户要求执行「重建 7 个业务镜像 → 部署 → 补一轮 A1/A2/A4/A6」。全部完成，逐条勾如下。

### 12.1 构建链故障与绕行（如实记录）

- [ ] **原标准入口 `./mogo build` 不可用**：kiri 的 `kiri-bk2`（docker-container driver）依赖 `mogo-local-reg:5000` mirror 解析 `FROM` 的 manifest；该 registry **容器与镜像均已不存在**（kiri 全部 context / `kiri raw images` / k3s containerd / VM 进程均未找到，只剩 `mogo-local-reg:5000/pause:3.10.2` 这个历史推送 tag），公网与国内镜像源均不可达。gateway 探针报 `dial tcp 172.21.0.5:5000: no route to host`；去掉 mirror 后改报 `registry-1.docker.io i/o timeout`。
- [x] **绕行方案**：改用 **daemon 内置 builder**（`DOCKER_BUILDKIT=0 docker --context kiri build`），它直接读 kiri daemon 的本地基础镜像，不解析 registry manifest。构建参数从 `docker compose -f docker-compose.yml -f docker-compose.build.yml config --format json` 解析（context / dockerfile / 全部 build args），逐镜像手工传入，未改任何 Dockerfile 或 compose 文件。
- [x] 构建前把 `kiri-bk2` 的 `/etc/buildkit/buildkitd.toml` 临时改为无 mirror 做验证，**收尾已还原原配置**（备份 `/tmp/buildkitd.toml.bak-20261111`）；`buildx prune -a -f --builder kiri-bk2` 回收 22.71 GiB 缓存，磁盘从 6.7 GiB 回升到 28.7 GiB。
- [ ] **后续建议**：恢复 `mogo-local-reg` 容器后再用标准 `./mogo build`；本绕行路径可复用（脚本 `/tmp/qa_rebuild_20261111.sh`）。

### 12.2 镜像重建与导入（逐条勾）

- [x] 7 个业务镜像全部重建，tag `e883aab5`，耗时 8m29s：`gateway` 8.9MB、`admin-web` 12.8MB、`user-web` 13MB、`admin-api` 101MB、`dsh-runtime-host` 284MB、`chat-api` 1.12GB、`document-parser` 1.66GB。
- [x] `export` / `scp` / `import` 三步 rc 全为 0（`IMAGE_TAG=e883aab5 scripts/k3s-rebuild-deploy.sh {export,scp,import}`）；containerd 中 7 个 `e883aab5` 镜像齐全，旧 `83bd0973` 保留作回滚。

### 12.3 部署与运行态验收（逐条勾）

- [x] **未使用脚本的 `apply` 步骤**（它会 sed 改其它会话在途的 `06-deployments.yaml`，且其 `mongo.replicas=1` 会误启内部 Mongo、还会重复 apply secrets）。改用临时清单 `/tmp/06-deployments.e883aab5.yaml`：8 处 tag → `e883aab5`，`mongo.replicas=0`；`kubectl apply --dry-run=client` 预检通过（8 个业务 Deployment configured、mongo/redis/weaviate unchanged）。
- [x] 8 个 Deployment 全部 `successfully rolled out`；10 个 Pod Running；`HEAD=e883aab5`，8/8 业务镜像 tag = HEAD，`tag_mismatch=0`；`mongo.replicas=0` 保持；relay Up。
- [x] 网关 `200 / 200 / 200 / 200 / 401`（`/`、`/admin/setup`、`/admin-api/health`、`setup/status`、`auth/me`）。
- [x] **修复真正进入运行态**：在运行中的 `admin-api` Pod 内导入 `TENANT_SCOPED_COLLECTIONS`，实测 95 项，050–053 的 7 个新集合 `missing=[]`、`all_present=True`。
- [x] 回滚清单已备：`/tmp/06-deployments.rollback-83bd0973.yaml`（tag 回 `83bd0973`，mongo 保持 0）。

### 12.4 部署后补跑 A1/A2/A4/A6（逐条勾）

- [ ] **首轮 POSTDEPLOY 的载体疏漏（已修正，不掩盖）**：精简回归脚本漏了原脚本的 `-e MOGO_E2E_MONGO_URI`，导致 `test_orchestration_canvas_mongo_e2e.py` 的 3 个用例被 skip，chat 变成 `3375 passed / 4 skipped`。补齐环境变量后**完整重跑 POSTDEPLOY2**，与 R3 计数完全一致。
- [x] **POSTDEPLOY2 最终结果**：A1（pods / images / http / k3s / drift / verify）rc 符合预期（`drift` / `verify` 为预期 rc=2 SKIP），`tag_mismatch=0`；A2 `63 pass / 0 fail`；A4 `339 passed / 9 skipped`；A6 admin `1638 passed / 1 skipped`、chat `3378 passed / 1 skipped`、doc `72 passed / 6 skipped`，合计 **5088 passed / 8 skipped / 0 failed**，与 R2/R3 **逐服务零偏差**。
- [x] 日志：`/tmp/qa-postdeploy-POSTDEPLOY2.log`、`/tmp/qa-POSTDEPLOY2-*.out`；脚本 `/tmp/qa_regress_postdeploy_20261111.sh`。精简回归不含 A5，未再写生产库。

### 12.5 剩余非阻塞事项

- [ ] 仓库 `deploy/k8s/generated/06-deployments.yaml`（其它会话在途）仍是 `83bd0973` + `mongo.replicas=1`，与运行态不一致；须由该会话同步，**在此之前勿直接 apply 仓库清单**（会回退 tag 并误启内部 Mongo）。
- [ ] 本 §12 及 §0/§1.3/§7.2/§10/§11 的口径更新为**工作区未提交改动**，如需入库须另行提交。
- [ ] N-8 / N-10 / N-14 / F-12 与 15 项环境类保留项，发布说明仍需标注。

---

*审计数据落点：`/tmp/qa-d1d3-20261111.log`（54 特性重扫）、`/tmp/qa-regress-20261111-R{1,2,3}.log`（三轮 A1–A7）、`/tmp/qa-R{1,2,3}-*.out`（逐步原始输出）、`docs/regression-arm-kiri-2026-11-11.md`（多轮回归明细）、`/tmp/qa-postdeploy-POSTDEPLOY2.log`（部署后回归）。*
