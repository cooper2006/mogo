# kiri 生产环境多轮回归明细 · 2026-11-11

- **所属审计**：`deliverables/QA-AUDIT-STANDARD-2026-11-11.md`（standard 深度全量 QA 审计）
- **权威环境**：`docker context show = kiri`；生产栈 = **k3s**（10 Pod Running），数据后端 = **ServeBay Mongo**（`host.docker.internal:27017` / `mogo_dev`，已归一「只认 32-hex」）
- **运行镜像 / HEAD（审计时点）**：`83bd0973`（8 个业务 Deployment 全部一致，`tag_mismatch=0`）。审计收尾后 QA 修复单独提交使 HEAD 前进，k3s 镜像仍是 `83bd0973`；该「tag ≠ HEAD」是**修复未部署**的预期状态，不是镜像漂移，发布前重建镜像即恢复一致。
- **轮次设计**：R1 修前基线 / 载体校准 / 缺陷发现 → R2 修复后全量复验 → R3 稳定性 / 幂等复跑
- **隔离测试库**：`mogo_regtest_20261111`（三轮复用同一库，专测自清理与幂等）
- **逐条勾说明**：每项带 `[ ]`，reviewer 可逐项勾选；未验证项一律留空并写明原因。

| 轮次 | 起始 | 结束 | 定位 |
|---|---|---|---|
| R1 | 2026-11-11 09:36:57 | 09:42:09 | 修前基线、载体校准、真实缺陷发现 |
| R2 | 2026-11-11 09:59:08 | 10:06:15 | 修复后有效基线 |
| R3 | 2026-11-11 10:06:21 | 10:13:14 | 稳定性 / 幂等复跑 |

---

## 1. 回归矩阵定义（A1–A7，逐条勾）

- [x] **A1 运行态 / 安全接线**：`A1_pods` 10 Pod、`A1_images` 8 业务镜像、`A1_http` 网关 5 个探测、`A1_k3s` kubectl 实测 tag = HEAD（R2 起新增）、`A1_drift` / `A1_verify` 治理守卫
- [x] **A2 安全基线**：`./mogo baseline`（非 root / read_only / cap_drop ALL / no-new-privileges / user=10001）
- [x] **A3 API 契约工具 10 项**：`path_naming` / `error_codes_uniqueness` / `error_code_mapping` / `validate.py ×3` / `consumer_refs --all` / `deprecation_check --all` / `diff.py` / `openapi/validate.py --all` / `openapi/probe.py --all`
- [x] **A4 仓库守卫**：`deploy/tests` 全量（339 用例）
- [x] **A5 本体权限端到端**：k3s Pod 内 HTTP smoke（12 项）+ mongo 双后端 parity（8 项）
- [x] **A6 三服务全量 pytest**：admin-api / chat-api / document-parser，跑在 kiri 的 `83bd0973` **生产镜像**内，workspace 同路径挂载覆盖工作区修复
- [x] **A7 ID 归一终态**：`migrate_ids_to_hex32.py verify` + 生产库 live / backup 集合与文档计数

> **载体口径**：A1/A5 直接打 k3s Pod 与网关；A6 在 kiri docker daemon 的生产镜像内跑；A2/A3 部分 / A4 用宿主项目 venv（静态守卫与契约工具，不依赖容器内 python 包）；A7 用宿主 python3 直连 ServeBay Mongo。**全部以 kiri 为准**，未使用其它 docker context。

---

## 2. 三轮 RC 汇总（26 步 × 3 轮）

| 步骤 | R1 | R2 | R3 | 说明 |
|---|---|---|---|---|
| A1_pods | 0 | 0 | 0 | 10 Pod Running |
| A1_images | 0 | 0 | 0 | 8 业务镜像 tag `83bd0973` |
| A1_http | 0 | 0 | 0 | 200/200/200/200/401 |
| A1_k3s | — | 0 | 0 | R2 起新增，`tag_mismatch=0` |
| A1_drift | **0（假阳性）** | **2（预期 SKIP）** | **2（预期 SKIP）** | F-2 修复前后对照，见 §5 |
| A1_verify | **0（假阳性）** | **2（预期 SKIP）** | **2（预期 SKIP）** | 同上 |
| A2_baseline | 0 | 0 | 0 | 63 pass / 0 fail |
| A3_path_naming | 0 | 0 | 0 | no verb segments |
| A3_error_codes | 0 | 0 | 0 | 0 专属 / 15 通用 |
| A3_error_map | 0 | 0 | 0 | no status-semantics drift |
| A3_validate_admin-api | 0 | 0 | 0 | 46 interactions |
| A3_validate_chat-api | 0 | 0 | 0 | 63 interactions |
| A3_validate_document-parser | 0 | 0 | 0 | 10 interactions |
| A3_consumer_refs | 0 | 0 | 0 | 三服务 OK（约 49s） |
| A3_deprecation | 0 | 0 | 0 | 三服务 OK |
| A3_diff | 0 | 0 | 0 | 0 change / 0 breaking |
| A3_openapi_validate | **1（载体）** | 0 | 0 | 镜像缺 `openapi_spec_validator` |
| A3_openapi_probe | **1（载体）** | 0 | 0 | 容器内 chat-api 依赖不全 |
| A4_deploy_tests | **1（载体）** | 0 | 0 | 容器内无 docker CLI |
| A5_smoke | 0 | 0 | 0 | 12 passed / 0 failed |
| A5_parity | 0 | 0 | 0 | 8 passed / 0 failed，`cleanup left=0` |
| A6_admin | **1（真实缺陷）** | 0 | 0 | F-1 租户清除清单 |
| A6_chat | **1（真实缺陷 + 载体）** | 0 | 0 | F-2 审计枚举 + DSH e2e |
| A6_doc | 0 | 0 | 0 | 72 passed / 6 skipped |
| A7_verify | 0 | 0 | 0 | `verify PASS` |
| A7_prod_db | 0 | 0 | 0 | live 155 集合 / backup 155 集合 |

- [x] **R2 / R3 的 26 个步骤 rc 完全一致**，两个预期 rc=2（SKIP）三轮稳定复现。
- [x] R3 总耗时 6m54s，与 R2 同量级，未见超时 / 资源退化 / 偶发失败。

---

## 3. 逐轮计数明细（测试口径）

### 3.1 A6 三服务全量 pytest

| 轮次 | admin-api | chat-api | document-parser | 合计 |
|---|---|---|---|---|
| R1 | 1637 passed / 1 skipped / **1 failed** | 3369 passed / 1 skipped / **9 failed** | 72 passed / 6 skipped | 5078 / 8 / **10** |
| R2 | 1638 passed / 1 skipped | 3378 passed / 1 skipped | 72 passed / 6 skipped | **5088 / 8 / 0** |
| R3 | 1638 passed / 1 skipped | 3378 passed / 1 skipped | 72 passed / 6 skipped | **5088 / 8 / 0** |

- [x] R2 / R3 逐服务计数**完全一致**（`1638 / 3378 / 72`），合计 5088 passed / 8 skipped / 0 failed。
- [x] R3 三轮复用同一隔离库 `mogo_regtest_20261111`，A5 parity 的 `cleanup left=0` 三轮一致，证明业务数据自清理有效、无跨轮状态泄漏。
- [x] 剩余 8 个 skip 均为环境性：admin `test_drill_credential_scripts.py` 硬编码 `127.0.0.1:27017`、chat `test_dsh_candidate_evaluation.py` 需容器内 git、doc 6 项依赖 celery/docling 运行时。
- [x] chat-api **未走 marker 过滤降级**：从 `dsh-runtime-host:83bd0973` 导出 linux `node_modules`（613MB）与 node v24.22.2 二进制只读挂载，DSH Runtime Host e2e 真实启动。

### 3.2 其余回归集

| 项目 | R1 | R2 | R3 |
|---|---|---|---|
| A2 `./mogo baseline` | 63 pass / 0 fail | 63 pass / 0 fail | 63 pass / 0 fail |
| A3 契约工具 | 8/10 rc=0 | **10/10 rc=0** | **10/10 rc=0** |
| A4 `deploy/tests` | 58 failed / 275 passed / 15 skipped | **339 passed / 9 skipped** | **339 passed / 9 skipped** |
| A5 smoke | 12 passed / 0 failed | 12 passed / 0 failed | 12 passed / 0 failed |
| A5 parity | 8 passed / 0 failed | 8 passed / 0 failed | 8 passed / 0 failed |
| A7 `verify` | PASS | PASS | PASS |

- [x] `openapi/validate.py --all`：宿主 venv + `PYTHONPATH=/tmp/qa-openapi-validator`（纯包目录）跑通；spectral CLI 未安装时回退内置 lint，chat-api 168 提示项不阻断。
- [x] `openapi/probe.py --all`：宿主 `services/chat-api/.venv/bin/python` → `probe: OK（无一致性问题）`。
- [x] A4 使用宿主 venv + `--basetemp=/tmp/qa-a4-base-${ROUND}` 规避 WorkBuddy `sitecustomize.py` 的 `pytest-of-root` 目录冲突。

---

## 4. R1 失败归因（不掩盖、不误判为产品回归）

- [x] **真实缺陷 2 项（已修并复验）**
  - F-1：admin `test_tenant_purge.py::test_every_tenant_id_keyed_collection_in_the_tree_is_covered` 全树扫描发现 050–053 新增 7 个带标量 `tenant_id` 的集合未纳入 `TENANT_SCOPED_COLLECTIONS` → 修清单，定向 30 passed。
  - F-2：chat `test_im_audit_events` 断言仍只认 4 个事件，051 新增 `im.employee.route` 后 1 failed → 更新白名单，单文件 8 passed。
- [x] **载体 / 环境 65 项（不修产品代码）**

| 载体问题 | R1 表现 | 修正方式 |
|---|---|---|
| 容器内无 `docker` CLI | A4 `docker compose config` → 58 failed（`FileNotFoundError` / rc 255） | A4 改宿主项目 venv 运行 + 独立 `--basetemp` |
| 镜像缺 `openapi_spec_validator` | A3 `openapi/validate` `ModuleNotFoundError` → rc=1 | 宿主 venv + 离线纯包 `PYTHONPATH=/tmp/qa-openapi-validator` |
| 容器内 chat-api 依赖不全 | A3 `probe` 把 9 条已声明路由误判 404 → `probe: FAILED` | 改用宿主 `services/chat-api/.venv/bin/python`，宿主同命令 = OK |
| DSH e2e 需 linux node / node_modules | chat 8 个 `DSH Runtime Host exited during startup with code 1` | 从 `dsh-runtime-host:83bd0973` 导出 linux `node_modules` + node 二进制只读挂载（首次导出有嵌套 `node_modules/node_modules`，已扁平化） |
| 宿主 pytest basetemp shim | 24 errors：`FileExistsError ... /T/pytest-of-root` | 每轮独立 `--basetemp=/tmp/qa-a4-base-${ROUND}` |
| A7 初版口径含备份集合 | R1 输出 `collections 310 docs 144638` | R2 起改为 live / backup 分列：`live_collections` / `live_docs` / `backup_collections` |

- [x] 所有载体修正**未改动任何产品代码来「适配」测试**；R2/R3 用同一批产品代码全量通过，证明 R1 的失败属载体而非回归。
- [x] 因此 **R1 定位为「载体校准 + 缺陷发现轮」，R2 为有效修后基线，R3 为稳定性轮**；R1 与 R2 的计数差不作产品回归解读。

---

## 5. 治理守卫假阳性修复（F-2 的另一半，三轮对照）

- [ ] **R1（修前）**：compose dev 栈已停机、生产由 k3s 承载，`./mogo drift` / `./mogo verify` 仍输出「比对 **0** 项 → **OK** — 与声明一致」，rc=0。这是**误导性绿灯**，会被发布门禁误读。
- [x] **R2 / R3（修后）**：`checked == 0` 时输出 `SKIP — 未发现任何运行中的 compose 服务，本次未执行比对` + 提示改用 kubectl 核对，返回 **rc=2**；JSON 模式增加 `"status": "skipped"`。
- [x] k3s 侧一致性由新增的 `A1_k3s` 实测覆盖：`HEAD=83bd0973`，8/8 镜像 tag 匹配，`tag_mismatch=0`，R2/R3 均 rc=0。
- [x] 「守卫不假装通过」与「k3s 有真实核对手段」两件事同时成立，不依赖 compose 守卫兜底。

---

## 6. 生产库文档增长归因（R3 新发现，已修文档口径）

### 6.1 现象

A7 `verify` 的生产库 `mogo_dev` 文档数三轮递增，R2/R3 并非「零偏差」：

| 轮次 | `docs` | `hex32_ids` | `natural_key_ids` | `objectid_ids` | `hex24_ids` | `residual_hex24_values` | `event_docs` |
|---|---|---|---|---|---|---|---|
| R1 | 3931 | 3617 | 314 | 0 | 0 | 0 | 0 |
| R2 | 3947 | 3633 | 314 | 0 | 0 | 0 | 0 |
| R3 | **3961** | **3647** | **314** | **0** | **0** | **0** | **0** |

- [x] `live_collections` 恒为 **155**，`backup_collections` 恒为 **155**（`__hex32_bak_*`，来自 11-11 停机窗口），集合结构零变化。
- [x] 三轮 `verify PASS`：`objectid_ids=0 / hex24_ids=0 / residual_hex24_values=0 / event_docs=0`；增量全部是**新生成的 32-hex 主键**，`natural_key_ids` 恒定 314。
- [x] **ID 归一终态未被破坏**，事件流两集合保持为空。

### 6.2 根因（按时间窗逐集合实测，非推测）

`A5_smoke` 是在 **k3s 生产 admin-api Pod 内**跑 HTTP 端到端冒烟（`kubectl exec` + stdin 喂脚本），连的是生产业务库 `mogo_dev`。脚本对自建 grant / detail 数据用完即删，但**按审计合规保留的写入不删除**：

| 时间窗（UTC） | 轮次 | 实测新增 |
|---|---|---|
| 01:59:08–02:06:15 | R2 | `mesc_ontology_perm_audit` +7、`admin_sessions` +1 |
| 02:06:21–02:13:14 | R3 | `mesc_ontology_perm_audit` +7、`admin_sessions` +1、`sys_config` +1 |

其余增量落在无 `ts` / `created_at` 字段的工具 / 网关审计集合，故时间窗统计只覆盖到 8–9 条/轮，与 `docs` 的 +14~16/轮 差额属同一批写入。

- [x] 交叉排除：`A5_parity` 传 `MONGODB_DB=mogo_regtest_20261111`，实测写在隔离库（该库 `mesc_ontology_perm_audit` 三轮后 3 条，对应 `audit write+read n=1/2/3`），**未污染生产库**。
- [x] 生产库 `mesc_ontology_perm_audit` 中 `tenant_id=parity-030` 的 23 条记录 `ts` 均为 **2026-11-05**，是历史遗留，不是本轮产生。
- [x] 结论：**这是设计内落库副作用，不是回归漂移、不是测试数据残留、也不破坏 32-hex 终态**；但「R2/R3 计数零偏差」的措辞不成立，须限定为**测试计数零偏差**。

### 6.3 已修与保留

- [x] **已修 F-12（文档口径）**：`deploy/tests/test_ontology_permission_smoke.py` 的 docstring 原称「写路径会真的落库，故对自建的冒烟数据**用完即删**」，与实际不符。现改为明确列出每轮保留的 7 条本体权限审计 / 1 条会话 / 1 条 `sys_config` 变更等，并写明「多轮回归会让生产库文档数线性增长（实测 3931→3947→3961），属设计内副作用，若要求零污染应在隔离库执行或按时间窗评估清理，审计日志不建议直接删除」；同时补上 k3s `kubectl exec deployment/admin-api` 的实际用法（原 docstring 只有 compose 的 `mogo-admin-api-1`）。
- [x] 复验：`py_compile OK`；`pytest tests/test_ontology_permission_smoke.py` 在宿主按设计 `1 skipped`（需 Pod 内 runtime secret），未引入收集错误。
- [ ] **保留项（P3，不阻断发布）**：`A5_smoke` 仍指向生产库。若要生产库零污染，需把冒烟切到隔离库（要给 k3s Pod 换 DB 配置，会动生产栈）或设计只写隔离租户的清理流程 —— 均超出本轮最小改动边界，留待维护窗口。
- [ ] 生产库当前生命周期内累积的审计 / 会话记录**未清理**：审计日志按合规不直接删除，需人工评估后再决定。

---

## 7. 稳定性与幂等结论（逐条勾）

- [x] **多轮回归完成**：R1（基线 + 缺陷发现）→ R2（修复后全量）→ R3（稳定性复跑）三轮均执行完整 A1–A7。
- [x] **R2 / R3 测试计数零偏差**：A6 每轮 5088 passed / 8 skipped / 0 failed；A2 63/0；A4 339 passed / 9 skipped；A5 12/0 + 8/0；A3 10/10；A7 `verify PASS`。
- [x] **26 个步骤 rc 三轮一致**（含两个预期 rc=2 的 SKIP），R3 无偶发失败、无超时、无资源退化。
- [x] **幂等性成立**：三轮复用同一隔离库，A5 parity `cleanup left=0`，A6 逐服务计数不变，无跨轮状态泄漏。
- [x] **k3s 运行态稳定**：三轮 10 Pod Running、8/8 镜像 tag = HEAD、网关 5 个探测全部符合预期、内部 mongo 保持 0 副本。
- [x] **32-hex 终态稳定**：三轮 `objectid_ids=0 / hex24_ids=0 / residual_hex24_values=0 / event_docs=0`，集合结构 155 live + 155 backup 不变。
- [x] **差异已全部归因**：R2↔R3 的 4 处输出差异 = ① Pod AGE 时间戳（54m→61m）；② A4 pytest 耗时（38.60s→33.47s）；③ A5 parity 的 `created_at` 与 `audit n=2→3`（隔离库累积审计，测试断言为可读写而非精确计数，不属失败）；④ 生产库 `docs 3947→3961`（§6 已归因）。**无一项是产品回归或未解释漂移。**
- [ ] **运行态不含本轮修复**：k3s Pod 仍跑修复前构建的 `83bd0973`；A6 通过 workspace 同路径挂载覆盖的是**源码**，不是运行镜像。本轮修复已单独提交并推送 `mogo/main`（非发版），发布前仍须「重建镜像 → 部署 → 补一轮 A1/A2/A4/A6」。

---

## 8. 证据落点

| 证据 | 路径 |
|---|---|
| 三轮总日志 / RC 汇总 | `/tmp/qa-regress-20261111-R{1,2,3}.log` |
| 三轮控制台输出 | `/tmp/qa-regress-20261111-R{1,2,3}.console` |
| 逐步原始输出（26 × 3） | `/tmp/qa-R{1,2,3}-*.out` |
| 回归脚本（A1–A7 定义） | `/tmp/qa_regress_20261111.sh` |
| k3s 镜像 tag 快照 | `/tmp/qa-R{1,2,3}-k3s-images.txt`（R1 无此步） |
| D1–D3 54 特性重扫 | `/tmp/qa-d1d3-20261111.log` / `.json` |
| 主审计报告 | `deliverables/QA-AUDIT-STANDARD-2026-11-11.md` |

---

*本明细与 `standard` 深度主报告配套；所有数字来自三轮实跑原始输出，未沿用 11-06 / 11-09 旧口径。*
