# MOGO SDD 全量 QA 审计报告（standard 深度）· 2026-11-09

- **审计对象**：`specs/` 下 001–049 共 **49 个特性**（SDD 驱动），核验宣称「全流程已就绪，可进入 PR 评审与版本发布——库能力、生产接线与治理资产齐备」
- **审计深度**：`standard`（对齐 QualityForge / 2026-11-06 报告口径：需求门禁 → 设计 → 实现任务 → 代码 → 测试 → 生产接线 → 文档一致性 → 保留项）
- **审计日期**：2026-11-09
- **权威环境**：**kiri**（`docker context show = kiri`，Kiri 0.1.18，`linux/arm64` dev profile，mongo 后端，11 个业务容器 healthy）。所有服务级验证均在 kiri 容器 / 容器网络内完成；宿主 Python 只用于静态扫描与静态工具。
- **本轮换维**：上轮（11-06）验的是「文档 + 代码 + 测试 + 生产接线四层」；**本轮换到「版本发布就绪 + 治理资产有效性」**——即宣称里最没被验过的那半句：发布口径是否自洽、守卫脚本是否真的能跑、quickstart 的命令是否真的可执行、发布资产（PPT / README / CHANGELOG）数字是否真实、上轮修复是否防回归、运行态与 HEAD 是否一致。
- **逐条勾说明**：每项均带 `[ ]` 勾选框，reviewer 可逐项勾选。状态用词：`通过` / `保留` / `缺口` / `已修复` / `未修`。**未验证的项一律留空并写明原因，不假通过。**
- **配套报告**：`docs/regression-arm-kiri-2026-11-09.md`（kiri 三轮回归 R1/R2/R3 逐项明细）

---

## 0. 一句话结论

- [x] **文档层 / 代码层 / 测试层 / 生产接线层：发布就绪**（kiri 三轮全量 pytest 每轮 4828 passed / 2 skipped / 0 failed，三轮计数完全一致）。
- [ ] **运行态与源码 HEAD 尚不一致**：`./mogo drift` FAIL 8 处、`./mogo verify` FAIL 8 处（运行镜像 `8ae25759` vs HEAD `fd02f69e`）。这是**本轮唯一的一级发布阻断项**，消除它需要重建 7 个业务镜像（耗时且改动 kiri 生产栈），未擅自执行，待用户决定。
- [x] 本轮共发现 **13 项**问题，**已修复 7 项**（含 1 项代码级守卫缺陷、1 项上轮遗留 D-3），**如实登记未修 6 项**。

---

## 1. 审计口径与基线

### 1.1 D1–D8 维度（每条可勾）

- [x] **D1 需求质量门禁** — 49 特性 `checklists/requirements.md` 存在性与勾选状态全量重扫
- [x] **D2 设计完备性** — 49 特性 `plan.md` 存在且非空
- [x] **D3 实现任务落地** — 49 特性 `tasks.md` 勾选率全量重扫（不沿用 11-06 旧数字）
- [x] **D4 代码落地与防回归** — 发布关键特性落点抽样 + 11-06 F-1/F-2/F-8 与 11-08 D-7/D-8 修复是否仍有效
- [x] **D5 测试全绿** — kiri 容器内三轮全量 pytest（真实 MongoDB 隔离库）+ A4/A5 回归集
- [x] **D6 生产接线** — compose / 安全基线 / 网关契约 / 漂移与产物校验
- [x] **D7 文档一致性与版本口径** — 7 处版本来源 + MCP + OpenAPI 快照 + README 中英 / INDEX / PPT / CHANGELOG
- [x] **D8 已知保留项与发布阻塞** — 诚实登记环境类、维护窗口、人工凭据类与未修项

### 1.2 总览基线（本轮脚本实测，非引用）

| 指标 | 本轮实测 | 与 11-06 对比 |
|---|---|---|
| 特性总数 | **49**（001–049） | 一致 |
| spec / plan / tasks / quickstart / 门禁 五件套 | **49 / 49 / 49 / 49 / 49**（存在且非空） | 一致（11-06 只列了四件套 + 门禁文件） |
| `tasks.md` 勾选（`^- \[[ x]\] ` 全量行） | **1549 / 1563 = 99.10%** | 一致 |
| 100% 勾选特性 | **46** | 一致 |
| 部分勾选特性 | **3**：017 41/46、024 112/119、049 23/25 | 一致 |
| 门禁清单严格口径 | **44 份 100% 勾选** + 003–006 四份 0 勾 + 017 一份四态表无 checkbox | 口径差异，见下方说明 |
| 版本来源（7 处 + `MCP_CLIENT_VERSION` + 3 份 OpenAPI `info.version`） | **全部 0.2.7，一致** | 新增核验维度 |
| 全量 pytest（kiri 容器，R1/R2/R3） | 每轮 **admin 1568 passed / 1 skipped；chat 3260 passed / 1 skipped** | 与 11-08 权威基线一致 |
| 三轮累计 | **14484 passed / 6 skipped / 0 failed** | 新增（本轮多轮） |
| `./mogo baseline` | 修前 **0 pass / 1 fail（rc=1）**；修后 **63 pass / 0 fail（rc=0）** | 新增（本轮发现并修复） |
| `deploy/tests` | **333 passed / 15 skipped**（三轮一致） | 与 11-08 的 339/9 差 6 项，归因见 §5.3 |
| 相对链接扫描 | 386 条，命中 15；活动文档真实断链 **1**（已修）→ **0** | 新增维度 |

> **门禁口径差异说明（非缺陷）**：11-06 报告写「45 份 100% 勾选」，本轮按「文件含 checkbox 且无未勾项」的严格口径为 **44**；017 的 v3 Gate 是四态表、无 checkbox，本轮单列。003–006 四份为既有回溯未审（0 勾，20/18/17/17 未勾），与 11-06 一致。差异仅来自 017 是否计入，不影响发布结论。

### 1.3 方法学声明（诚实边界）

- [x] 原 QualityForge 964 项逐条判定文本未入库、工具不可用，本轮按文档化 `standard` 方法论对仓库内**可核验证据重新执行**，不逐字复刻。
- [x] `standard` 深度**不要求 49 特性逐文件行级穿透**；D4 采用「声明 + 抽样 + 防回归」。
- [x] **以 kiri 为准**：宿主 Python 缺 `yaml` / `openapi_spec_validator` / `pytest`，直接在宿主跑契约工具会失败；本轮 A3/A5/A6 全部在 kiri 容器或容器网络内执行，宿主仅用于静态扫描与静态工具（用项目 venv）。
- [x] 源码级结论覆盖 **HEAD `fd02f69e`**（容器同路径挂载 workspace）；镜像级结论对应 **运行镜像 `8ae25759` / `60e8e90d`**，两者差异在 §5.4 单列，不混为一谈。

---

## 2. D1–D3 逐特性状态表（49 行，全量重扫）

> 列：五件套 = spec / plan / tasks / quickstart / 门禁（`OK` = 存在且非空）；tasks 勾选 = 已勾/总数；门禁 = 已勾/含 checkbox 总数；状态 = `通过` / `保留`。

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

### 2.2 结论（逐条勾）

- [x] **D1** 49/49 门禁文件存在；44 份严格口径全勾 + 003–006 四份既有回溯未审 + 017 v3 Gate 四态表（无 checkbox）。
- [x] **D2** 49/49 `plan.md` 存在且非空。
- [x] **D3** 46/49 `tasks.md` 100% 勾选；017 / 024 / 049 余 **14 项**（5 + 7 + 2）均为环境类 / 维护窗口 / 人工凭据类保留，已逐项核实，非懒勾。
- [ ] 003–006 门禁清单仍为 0 勾（既有回溯，2026-10-03 落地审计判定 `partial`；非本轮引入，发布说明须标注）。

---

## 3. D4 代码落地、防回归与版本口径

### 3.1 上轮修复防回归（逐条勾）

- [x] **11-06 F-2** `tenant_purge.py` 的 `TENANT_SCOPED_COLLECTIONS` 仍含 `projects`（L95）与 `memory_policies`（L122），租户清除不残留。
- [x] **11-06 F-8** `test_session_end_lifecycle.py` 仍含 `monkeypatch.setattr(store_mod, "get_db", lambda: db)`（L125）与 `_FakeCollection.replace_one`（L58），真库隔离未被覆盖。
- [x] **11-06 F-1** `path_naming.py --root .` → `path-naming OK — no verb segments found`，025 路径整改未回退。
- [x] **11-08 D-7** `docker-compose.yml:1128` 仍为 `celery@$$(hostname)`，document-worker healthy。
- [x] **11-08 D-8** `services/document-parser/Dockerfile:275` 仍有 `chmod -R a+rX`，document-api `/api/ready` 200、setup status 六项全 ok。
- [x] **11-08 D-1/D-2/D-4/D-6** 三服务 `/ready` 隐含在 setup status 六项 ok 内；`./mogo baseline` 免手工 `MOGO_VERSION` 后 63/0；`./mogo check` 非外部库无检查项（正常）。

> 排查提示：首次用 BSD `grep 'a\|b'` 查这些符号会全部落空（BRE 不支持 `\|`），本轮已改用 ripgrep 复核，**不是修复丢失**。

### 3.2 版本发布口径（逐条勾）

- [x] 7 处版本来源：`chat-api/pyproject.toml`、`admin-api/pyproject.toml`、`admin-web/package.json`、`user-web/package.json`、三服务 `app/main.py` 的 `version=` —— **全部 0.2.7**。
- [x] `services/chat-api/app/services/mcp_streamable_http.py` 的 `MCP_CLIENT_VERSION` = **0.2.7**。
- [x] `specs/025-api-contract-hardening/openapi/*.json` 三份 `info.version` = **0.2.7**。
- [x] `git tag v0.2.7` 指向 `4cfca2af`（2026-11-08 19:30），与 CHANGELOG `## v0.2.7 - 2026-11-08` 一致。
- [x] README 中英特性数均为 **49**（001–049）。
- [ ] **CHANGELOG 收归未完成**：`Unreleased` 节仍堆放 2026-11-04 的 QA 条目，v0.2.7 节内 0 处 QA 条目 → 见 N-8（本轮未修）。
- [ ] **PPT 统计本轮修前有误**：首页写 `2026-11-06 · v0.2.7`、第 7 页写 `1567 项（已勾 1549 · 余 18）` → 见 N-7（已修）。

### 3.3 治理资产有效性（本轮新增维度）

- [x] `deploy/cli/baseline-check.sh` 修前在宿主 Python 下**根本没跑起来**（PyYAML 缺失 → 0 pass / 1 fail，rc=1）→ 已修，见 N-2。
- [x] `025/quickstart.md` 修前 §1 / §2.1 / §4.1–4.3 / §6 / §8 使用了工具**不存在的参数**（`--services` / `--side` / `--contract` / `--provider-url` / `--base` / `--head` / `--fail-on-breaking` / `--all` on validate），且把 npm 包 `spectral-cli` 与不存在的 pip 包 `redis-py` 写进 `pip install` → 已修并逐条实跑，见 N-6。
- [x] 修复后 quickstart 命令**全部实跑通过**：`path_naming --root .`、`error_codes_uniqueness`、`error_code_mapping`、`validate.py`（三份契约）、`consumer_refs --all`、`deprecation_check --all`、`diff.py --old/--new` 自比对、`openapi/validate.py --all`、`openapi/probe.py --all` 均 rc=0。
- [ ] `tools/openapi/probe.py --all` 在宿主 venv 下 chat-api 探测 0 端点（venv 缺 `tenacity`，日志有 `ModuleNotFoundError`），属环境性，工具仍报 `probe: OK`；**未纳入发布阻断**。

---

## 4. D5 测试全绿（kiri 三轮实测，非声明）

### 4.1 A6 双服务全量 pytest（三轮逐轮）

| 轮次 | admin-api | chat-api | 合计 |
|---|---|---|---|
| R1（修前基线） | 1568 passed / 1 skipped（64.72s） | 3260 passed / 1 skipped（131.39s） | **4828 passed / 2 skipped / 0 failed** |
| R2（修复后复验） | 1568 passed / 1 skipped（65.12s） | 3260 passed / 1 skipped（133.77s） | **4828 passed / 2 skipped / 0 failed** |
| R3（稳定性 / 幂等复跑） | 1568 passed / 1 skipped（63.43s） | 3260 passed / 1 skipped（127.88s） | **4828 passed / 2 skipped / 0 failed** |

- [x] 三轮计数**完全一致**，且复用同一隔离库 `mogo_regtest_20261109`（验证测试自清理与幂等，无状态泄漏）。
- [x] 与 11-08 权威基线（4828 passed / 2 skipped / 0 failed）**零偏差**。
- [x] chat-api 完整口径已覆盖 Node 门控 e2e：`dsh-runtime-host:8ae25759` 的 linux `node_modules`（613MB）+ node v24.21.0 二进制挂载进容器，未走 marker 过滤降级。
- [x] 剩余 2 skip 均为环境性：admin-api `test_drill_credential_scripts.py` 硬编码 `127.0.0.1:27017`；chat-api `test_dsh_candidate_evaluation.py` 需容器内 git。

### 4.2 其他回归集（三轮一致）

- [x] A4 `deploy/tests`：**333 passed / 15 skipped**（20.10s / 20.04s / 19.33s）。
- [x] A5 030 本体权限容器内端到端：smoke **12 passed / 0 failed**；mongo parity **8 passed / 0 failed**（cleanup left=0）。
- [x] A3 admin-api 契约结构：46 / 63 / 10 interactions 全合规；`tests/api` 语义域未退化（由 A6 全量覆盖）。
- [x] 修后 A4 复跑仍 333/15，证明 `baseline-check.sh` 改动未破坏仓库守卫用例。

---

## 5. D6 生产接线

### 5.1 编排与安全基线（逐条勾）

- [x] `docker-compose.yml`（含 build / external / pool / prod-external-panweidb）与 `deploy/docker-compose.prod.yml` 存在。
- [x] `./mogo baseline` 修后 **63 pass / 0 fail**（R2/R3 各一次），非 root / read_only / cap_drop ALL / no-new-privileges / user=10001 全通过。
- [x] 11 个 `mogo-*` 业务容器 healthy（含 document-worker、dsh-runtime-host）。
- [x] 网关入口 `/`、`/admin/`、`/admin/setup` = 200/200/200；`/api/v1/auth/me` = 401；`/admin-api/api/ontologies`（跟随 301）= 401。
- [x] `/admin-api/api/setup/status`（跟随 301）= 200，`ready:true`，六项服务全 `ok:true`。
- [x] `./mogo check`：dev profile 非外部库，无检查项（正常返回）。

> **HTTP 口径坑（本轮校正）**：`/admin-api/api/setup/status` 不带尾斜杠会 301 到 `/api/v1/...`，须 `curl -L`；**带尾斜杠**会 301 到带斜杠的 v1 路径并得到 **404**。`/admin-api/api/ontologies` 同理。11-08 报告只写了「不带尾斜杠会 301」，本轮补齐后半句。

### 5.2 契约与 API 工具（kiri 容器内 / venv，逐条勾）

- [x] `path_naming.py --root .` → OK（无动词段）
- [x] `error_codes_uniqueness.py` → 0 服务专属码 / 15 通用码
- [x] `error_code_mapping.py` → 无 status-semantics drift
- [x] `contract/validate.py --service` 逐服务 → 46 / 63 / 10 interactions OK（参数非 append，必须逐服务调用）
- [x] `contract/consumer_refs.py --all` → 三服务 OK
- [x] `contract/deprecation_check.py --all` → 三服务 OK
- [x] `openapi/validate.py --all` → 三服务结构级（openapi-spec-validator）+ 内置 lint 阻断项通过；chat-api 168 条提示项不阻断；spectral CLI 未装走内置 lint
- [x] `contract/diff.py` 自比对 → 0 change / 0 breaking
- [x] `openapi/probe.py --all` → `probe: OK`（chat-api 探测 0 端点属宿主 venv 环境性）

### 5.3 A4 与 11-08 的 6 项差异归因（非代码回归）

- [x] 本轮 333 passed / 15 skipped，11-08 为 339 passed / 9 skipped，**总用例数同为 348**。
- [x] 多出的 6 个 skip 全部来自 `test_container_hardening.py:497`：`镜像 ghcr.io/mogoai/<svc>:fd02f69e 未在本机构建`——正是 §5.4 镜像漂移的连带结果（kiri 上只有 `8ae25759`）。
- [x] 其余 9 skip 与 11-08 同口径：alertmanager e2e ×6（需 `AM_E2E=1`）、ontology smoke ×1 + mongo parity ×2（已在 A5 容器内实跑覆盖）。

### 5.4 运行态漂移（本轮一级发现）

- [ ] `./mogo drift` → **FAIL — 8 处漂移**：admin-api / admin-web / chat-api / document-api / document-worker / gateway / user-web 运行 `8ae25759`，dsh-runtime-host 运行 `60e8e90d`，声明均为 `fd02f69e`。
- [ ] `./mogo verify` → **FAIL — 8 处不一致**（R1/R2/R3 三轮一致）。
- [x] 漂移系 2026-11-08 修复提交后 HEAD 前移、未重建镜像所致（11-08 报告已预判），**不是新引入的代码缺陷**。
- [x] 本轮源码级回归通过「容器同路径挂载 workspace」覆盖 HEAD，故测试结论对 `fd02f69e` 有效；**镜像级**一致性仍未满足。
- [ ] **消除漂移需重建 7 个业务镜像并 `./mogo up`**，耗时长且改动 kiri 生产栈，属影响面大的操作，本轮未擅自执行（见 §11）。

---

## 6. D7 文档一致性（逐条勾）

- [x] 49 特性五件套 100% 齐备，`tasks.md` 1549/1563 与 INDEX / CHANGELOG 声明一致。
- [x] 7 处版本来源 + MCP + 3 OpenAPI 快照 = 0.2.7 一致。
- [x] README 中英 49 特性口径一致；**已修** 017 旧范围口径、046–048 旧计数、`contracts/` 目录计数（5 → 8）。
- [x] PPT **已修** 首页日期与第 7 页 tasks 统计，与磁盘实测对齐。
- [x] 相对链接扫描 386 条：历史存档（WORK_LOG 9 / regression-report 4）为根相对路径口径、非活动资产；`credential-key-rotation-drill.md` 1 处真实断链**已修**；`QA-AUDIT-STANDARD-2026-11-04.md` 1 处为正文引用的示例链接，**扫描器误报非缺陷**。修复后活动文档真实断链 **0**。
- [ ] INDEX L236 仍写「029 未建」，而磁盘 `specs/029-user-web-sso-receiver/checklists/requirements.md` 存在且 18/18（本轮脚本记为 18/18）→ 见 N-12（历史快照段，本轮未修）。
- [ ] CHANGELOG `Unreleased` 未收归 v0.2.7 → 见 N-8（本轮未修，因该文件有其他会话在途改动）。

---

## 7. D8 已知保留项与发布阻塞（诚实登记，不假通过）

### 7.1 上轮 14 项环境类保留（本轮状态不变，逐条勾）

- [ ] **017**（5 项）：T031 双端真实浏览器 E2E、T042 切换演练 + `--reverse` 对账、T043 049 手工全链路、T045 M4 对账清理、T046 B/C 组（A 组本地已绿）
- [ ] **049**（2 项）：T022 全链路手工验证（需 admin 会话 + A/B/C 三账号）、T025 成员变更审计回归确认
- [ ] **024**（7 项）：T081 / T085 / T086 DR 演练、T106 压测容量、T107 扩容实测、B004 `mogo up` 全链路、B005 备份恢复真实模式
- [x] 明细与执行顺序见 `deliverables/QA-AUDIT-STANDARD-2026-11-06-remaining-items.md`（14 项，0/14 完成，T046-A 部分已勾）。
- [ ] **026** T041 水平扩展压测、**023** RTO/RPO 真实实测值、**003–006** 既有回溯需求清单未审 —— 发布说明须标注。
- [x] **027** 默认数据后端仍为 MongoDB（`MOGO_DATA_BACKEND` 未设置），PanWeiDB 为可选开关，口径已在 CHANGELOG 明确。

### 7.2 本轮新增保留 / 阻断（逐条勾）

- [ ] **N-1（P1 发布阻断）** 运行镜像 8 处漂移，`./mogo verify` FAIL —— 待用户决定是否重建。
- [ ] **N-8（P2）** CHANGELOG `Unreleased` 未收归 v0.2.7 节。
- [ ] **N-10（P3）** OTel 插桩依赖缺失，三服务各 8 条 `Instrumentor init failed` 日志，tracing 降级。
- [ ] **N-11（P3）** `./mogo baseline --json` stdout 混入诊断行，非纯 JSON。
- [ ] **N-12（P3）** INDEX L236「029 未建」陈旧声明。
- [ ] **N-14（P3）** 历史存档文档 13 处根相对链接（WORK_LOG / 2026-10-01 回归报告）。

---

## 8. 发现的问题清单（逐条可勾，含严重度）

| 编号 | 严重度 | 问题 | 位置 | 状态 |
|---|---|---|---|---|
| N-1 | **P1** | kiri 运行镜像 8 处漂移，`drift` / `verify` 均 FAIL；连带 A4 6 项 container-hardening 用例 skip | kiri 运行态 / `docker-compose.yml` 声明 | **未修**（影响面大，待决定） |
| N-2 | **P2** | `./mogo baseline` 宿主 Python 无 PyYAML → `0 pass / 1 fail` rc=1，安全基线守卫未真正执行 | `deploy/cli/baseline-check.sh` | **已修复 + 复验** |
| N-3 | P2 | README 中英仍写 017 范围 `personal / workspace / org`，与 v0.2.7 D4 已落地的 `personal/project/department`（无兼容层）冲突 | `README.md:160`、`README.zh-CN.md:143` | **已修复** |
| N-4 | P2 | README 英文 046–048 计数写 `34/35 · 30/31`、`all four`（实为 3 个特性且均 100%） | `README.md:117` | **已修复** |
| N-5 | P2 | README 中英称「5 个特性另附 `contracts/`」，磁盘实测 **8 个**（001/007/008/009/010/020/025/026） | `README.md:119`、`README.zh-CN.md:89` | **已修复** |
| N-6 | P2 | **上轮遗留 D-3 扩大**：025 quickstart 的 §1 / §2.1 / §4.1–4.3 / §6 #13–16、#19 / §8 使用工具不存在的 CLI 参数，依赖安装行含 npm 包与不存在的 `redis-py`；只有 §9 CI 片段正确 | `specs/025-api-contract-hardening/quickstart.md` | **已修复 + 全命令实跑** |
| N-7 | P2 | 发布资产 PPT 首页日期 `2026-11-06`（实为 11-08）、第 7 页 `1567 项 / 余 18`（实测 `1563 / 余 14`） | `docs/intro-v4.pptx` slide1 / slide7 | **已修复 + zip 完整性校验** |
| N-8 | P2 | `Unreleased` 节仍堆 2026-11-04 QA 条目，v0.2.7 节 0 处 QA 条目，发布收归流程未执行 | `CHANGELOG.md` | **未修**（其他会话在途改动） |
| N-9 | P3 | 凭证轮换演练文档的脚本链接断链（脚本实际在 `scripts/`） | `docs/credential-key-rotation-drill.md:12` | **已修复** |
| N-10 | P3 | OTel `FastAPIInstrumentor` / `HTTPXInstrumentor` 依赖未声明，三服务各 8 条 init failed 日志；离线 bundle 无对应 wheel | `services/*/requirements.in`、`services/common/observability_base.py` | **未修**（需补 wheel + 重建镜像） |
| N-11 | P3 | `./mogo baseline --json` stdout 首行混入 `Environment profile: ...`，`json.loads` 失败；直接调 `deploy/cli/baseline-check.sh --json` 才是纯 JSON | `mogo` CLI 包装 / `deploy/cli/env-profiles.sh` | **未修**（需改 i18n/profile 初始化，跨文件） |
| N-12 | P3 | INDEX L236「029 未建」与磁盘矛盾（029 checklist 存在且全勾） | `specs/INDEX.md:236` | **未修**（历史快照段） |
| N-13 | P3 | 11-06 报告门禁「45 份 100% 勾选」与严格口径 44 份差异（017 四态表是否计入） | `deliverables/QA-AUDIT-STANDARD-2026-11-06.md` | **已确认口径差异，非缺陷，本轮更正说明** |
| N-14 | P3 | 历史存档文档 13 处根相对链接被断链扫描命中 | `docs/WORK_LOG.md`、`docs/regression-report-2026-10-01.md` | **未修**（历史存档，按规约不动） |
| N-15 | P3 | `QA-AUDIT-STANDARD-2026-11-04.md` 1 处「断链」为正文引用的示例链接 | 同文件 L184 | **已确认扫描器误报，非缺陷** |

---

## 9. 修复记录与复验证据

| 修复 | 文件 | 复验证据 |
|---|---|---|
| N-2 守卫自动选择带 PyYAML 的解释器（`MOGO_PYTHON_BIN` > `python3` > 三服务 venv），3 处 `python3 -` 改为 `"${PYTHON_BIN}" -` | `deploy/cli/baseline-check.sh` | 修前 `0 pass / 1 fail` rc=1 → 修后 `63 pass / 0 fail` rc=0；R2/R3 各一次；A4 复跑 333/15 无退化 |
| N-3 017 范围口径改为 `personal/project/department` 并注明 D4 无兼容层 | `README.md`、`README.zh-CN.md` | 与 `CHANGELOG.md:52`、`specs/INDEX.md:9`、017 design v3 一致 |
| N-4 046–048 计数与「three」 | `README.md` | 与磁盘 34/34、30/30、13/13 一致 |
| N-5 `contracts/` 目录 5 → 8 并补 010/025/026 链接 | `README.md`、`README.zh-CN.md` | 磁盘 `ls -d specs/*/contracts/` = 8 |
| N-6 quickstart 全量命令口径 | `specs/025-api-contract-hardening/quickstart.md` | 10 条命令逐条实跑 rc=0（见 §3.3）；与 §9 CI 片段一致 |
| N-7 PPT 首页日期 + 第 7 页统计 | `docs/intro-v4.pptx` | zip 读到内存 → 临时文件 → `os.replace`；`testzip()` 通过；改前备份 `/tmp/intro-v4.pptx.bak-20261109`；文件大小不变 |
| N-9 演练脚本链接 | `docs/credential-key-rotation-drill.md` | 活动文档真实断链 1 → 0 |

- [x] 全部修复均为**本地最小改动**，未提交、未推送、未发布、未重建镜像。
- [x] 未触碰其他会话的 3 个在途改动：`CHANGELOG.md`（v0.2.7 日期修正）、`docs/2026-11-01-full-qa-audit-r13.md`（已删）、`docs/kiri-dev-build-guide.md`（已删）。
- [x] 曾尝试修 N-11（在 `mogo` 的 `command_baseline` 里重定向诊断输出），实测**未生效**（前缀来自更早的 profile 初始化），**已完整回退**，`mogo` 文件保持 clean，不留无效代码。

---

## 10. 发布就绪结论（逐条勾）

- [x] 49 特性 spec / plan / tasks / quickstart / 门禁五件套齐备（100%）
- [x] 46/49 特性 `tasks.md` 100% 勾选；14 项未勾均为环境 / 窗口 / 凭据类，诚实留空
- [x] 门禁清单 44 份全勾；003–006 既有回溯未审 + 017 四态表，口径已说明
- [x] 发布关键特性代码落点抽样与 11-06 / 11-08 的 7 项修复防回归全部有效
- [x] 版本口径 7 处 + MCP + 3 份 OpenAPI 快照 = 0.2.7，与 tag / CHANGELOG 一致
- [x] **kiri 三轮全量 pytest 每轮 4828 passed / 2 skipped / 0 failed，三轮零偏差**
- [x] A1–A5（网关契约 / 安全基线 / API 契约 / 仓库守卫 / 本体权限）三轮全绿
- [x] 契约工具 8 项、quickstart 全命令实跑通过；治理资产「可执行」而非仅文案
- [x] 本轮 7 项已修复问题均附复验证据，且未引入回归
- [x] 文档一致性错误（README 中英 / PPT / 断链）已修
- [ ] **N-1 运行镜像漂移未消除**：`./mogo verify` FAIL 8 处，若发布要求「运行态与 HEAD 零漂移」则构成阻断
- [ ] **N-8 CHANGELOG 收归未完成**；**N-10 / N-11 / N-12 / N-14** 四项 P3 未修，须在发布说明标注
- [ ] **14 项环境类保留项**（017 / 024 / 049 等）待维护窗口 / 凭据 / 远端环境执行，未执行前不构成代码冻结阻断

**结论**：在 `standard` 深度下，**代码冻结与 PR 评审可进入**——文档层、代码层、测试层（kiri 三轮真实全量实跑）、生产接线层（含治理资产可执行性）均达标，且本轮修复无回归。**版本发布前**仍需处理 N-1（重建镜像或明确接受漂移口径）、N-8（CHANGELOG 收归），并在发布说明中如实标注 N-10 / N-11 / N-12 / N-14 与 14 项环境类保留项。

---

## 11. 本轮未修 / 需用户决定（单独列出，等下一轮）

| 项 | 为什么没修 | 建议动作 |
|---|---|---|
| **N-1 镜像漂移** | 重建 7 个业务镜像 + `./mogo up` 耗时长、改动 kiri 生产栈，属影响面大 / 不可逆氛围操作，按规约不擅自执行 | **请用户决定**：① 按 `docs/dev-build-guide.md` 重建到 `fd02f69e` 后复跑 `drift/verify/A4`；或 ② 明确接受「运行态 `8ae25759` + 源码级 HEAD 回归」口径并在发布说明标注 |
| **N-8 CHANGELOG 收归** | 该文件已有其他会话在途改动（v0.2.7 日期 11-06 → 11-08），覆盖会污染并行工作 | 待该会话提交后，下轮按发布流程把 `Unreleased` 收归 v0.2.7 / 保留空 `Unreleased` |
| **N-10 OTel 插桩** | `base-images/` 790 个 wheel 中 0 个 instrumentation 包，补依赖需下载 + 更新 `requirements.in/txt` + 离线 bundle + 重建镜像，超出最小改动边界 | 单独排期：补 `opentelemetry-instrumentation-fastapi` / `-httpx` 并重建；当前 tracing 降级不阻断 |
| **N-11 `--json` 纯输出** | 诊断行来自 profile 初始化（早于 `command_baseline`），需改 `i18n.sh` / `env-profiles.sh` 跨文件；本轮尝试的局部修复已回退 | CI 暂用 `deploy/cli/baseline-check.sh --json`（已是纯 JSON）；下轮在 i18n 层把诊断行走 stderr |
| **N-12 INDEX「029 未建」** | 位于 2026-10-24 历史快照长段，改动会牵连整段口径 | 下轮加一行复核注记，不改历史快照正文 |
| **N-14 历史存档断链** | `docs/WORK_LOG.md` 自 2026-10-17 停更、仅作历史存档；按规约不动 | 保持原样，报告已登记 |
| **14 项环境类保留** | 需维护窗口 / 远端集群 / 真实浏览器 / A·B·C 账号凭据 | 见 `QA-AUDIT-STANDARD-2026-11-06-remaining-items.md` 的执行顺序 |

---

*审计数据落点：`/tmp/qa-d1d3-20261109.log`（49 特性重扫）、`/tmp/qa-r1-a1a2-20261109.log`、`/tmp/qa-r1-a6-20261109.log`、`/tmp/qa-r2r3-a6-20261109.log`（三轮 A6）、`docs/regression-arm-kiri-2026-11-09.md`（多轮回归明细）。*
