# ARM 准生产回归 · kiri 多轮（2026-11-09）

> 被测环境：**kiri** 引擎（Kiri 0.1.18，OCI image store），`linux/arm64` dev profile 栈（mongo 后端），全局默认 docker context = `kiri`
> 被测运行栈：`ghcr.io/mogoai/<svc>:8ae25759` ×7 + `dsh-runtime-host:60e8e90d`，11 个 `mogo-*` 业务容器 healthy
> 被测源码：**HEAD `fd02f69e`**（容器同路径挂载 workspace，源码级结论对 HEAD 有效）
> 回归范围：沿用 2026-11-08 kiri 轮的 **A1–A6** 口径，连续执行 **R1（修前基线）→ R2（修复后复验）→ R3（稳定性 / 幂等复跑）三轮**
> 结论：**三轮 A1–A6 全绿且计数零偏差**；A6 每轮 **4828 passed / 2 skipped / 0 failed**，三轮累计 **14484 passed / 6 skipped / 0 failed**
> 唯一未闭环项：**运行镜像与 HEAD 的 8 处漂移**（`drift` / `verify` FAIL，三轮一致），详见 §5 / `deliverables/QA-AUDIT-STANDARD-2026-11-09.md` N-1

---

## 0. 本轮口径与 11-08 的差异

- [x] **不重建全量镜像**：kiri 上运行的是 11-08 轮的 `8ae25759` 栈；HEAD 已前移到 `fd02f69e`（含 11-08 的 D-7/D-8 修复、v0.2.7 tag 后的 `4cfca2af` 与 `fd02f69e`）。重建 7 镜像耗时长且改动生产栈，本轮未执行，漂移如实登记。
- [x] **源码级与镜像级分开记账**：A6 通过 `-v /Users/cooper/mogo:/Users/cooper/mogo` 同路径挂载 workspace，pytest 收集的是 **HEAD 源码**；运行依赖与 Python 来自 `8ae25759` 镜像（pin 版本，无宿主 pydantic 偏移）。这与 11-08「纯净 HEAD 口径」等价，但镜像 tag 未同步。
- [x] **chat-api 测试依赖不重建 `-test` 镜像**：11-08 用 `INSTALL_TEST_DEPS_AT_BUILD=true` 构建了 `chat-api:8ae25759-test`。本轮改为把离线 bundle 的 6 个纯 Python 测试 wheel（`pytest 9.1.1` / `pytest-asyncio 1.4.0` / `pluggy 1.6.0` / `iniconfig 2.3.0` / `packaging 26.3` / `pygments 2.21.0`）解到 `/tmp/qa-regtest-20261109/testdeps`，以 `PYTHONPATH` 只读挂载进**原生产镜像**。效果等价（镜像内 pin 版本）、副作用更小（不新增镜像、不改生产镜像）。
- [x] **Node 门控 e2e 不降级**：从 `dsh-runtime-host:8ae25759` 镜像 `docker cp` 出 linux `node_modules`（613MB）与 `/usr/local/bin/node`（v24.21.0，117MB），只读 bind-mount 覆盖 `services/chat-api/dsh/runtime-host/node_modules` 与 `/usr/local/bin/node`；另设 `MOGO_E2E_MONGO_URI=mongodb://mongo:27017` 解锁 canvas mongo e2e。**未使用 marker 过滤**。
- [x] **三轮复用同一隔离库** `mogo_regtest_20261109`，用于验证测试自清理 / 幂等 / 无状态泄漏；不污染业务库 `mogo_dev`。

### 0.1 执行模板（三轮完全一致）

```
# admin-api（镜像自带 pytest 9.1.1）
docker run --rm --network mogo_backend \
  -v /Users/cooper/mogo:/Users/cooper/mogo -w /Users/cooper/mogo/services/admin-api \
  -e MONGODB_URI=mongodb://mongo:27017 -e MONGODB_DB=mogo_regtest_20261109 \
  --entrypoint python ghcr.io/mogoai/admin-api:8ae25759 \
  -m pytest -p no:cacheprovider -o addopts='-q'

# chat-api（生产镜像 + 只读测试依赖 + linux node）
docker run --rm --network mogo_backend \
  -v /Users/cooper/mogo:/Users/cooper/mogo -w /Users/cooper/mogo/services/chat-api \
  -v /tmp/qa-regtest-20261109/testdeps:/tmp/qa-testdeps:ro \
  -v /tmp/qa-regtest-20261109/node_modules:/Users/cooper/mogo/services/chat-api/dsh/runtime-host/node_modules:ro \
  -v /tmp/qa-regtest-20261109/node:/usr/local/bin/node:ro \
  -e PYTHONPATH=/tmp/qa-testdeps -e MONGODB_URI=mongodb://mongo:27017 \
  -e MONGODB_DB=mogo_regtest_20261109 -e MOGO_E2E_MONGO_URI=mongodb://mongo:27017 \
  --entrypoint python ghcr.io/mogoai/chat-api:8ae25759 \
  -m pytest -p no:cacheprovider -o addopts='-q'
```

> 三个必备细节（沿用 11-08 踩坑结论）：① 挂载必须保持 `/Users/cooper/mogo` 原深度，`tests/api/test_semantics.py:29` 用 `Path(__file__).parents[4]` 定位仓库根；② 用 `-o addopts='-q'` 覆盖 pyproject 的 `--timeout=120`（镜像无 pytest-timeout）；③ chat-api 现网镜像无 pytest、且已卸载 pip，靠只读 PYTHONPATH 注入而非 `pip install`。

---

## 1. 环境与准备（逐条勾）

- [x] `docker context show = kiri`；11 个 `mogo-*` 业务容器 healthy（含 document-worker、dsh-runtime-host）。
- [x] kiri VM 磁盘：overlay 62.4G，已用 29.3G（47%），余 33.1G —— 足够容纳本轮挂载产物。
- [x] 离线 wheel 准备：首次误把 `arm64/*.whl` 全量装进 `--target`，被 `PyYAML-6.0.2-cp313-...-linux_aarch64.whl` 的平台标记拒绝；改为**只取 6 个 `py3-none-any.whl`** 后成功（14MB）。
- [x] `PYTHONPATH=/tmp/qa-regtest-20261109/testdeps` 下 `pytest 9.1.1` / `pytest_asyncio 1.4.0` 导入校验通过。
- [x] `dsh-runtime-host:8ae25759` 的 node 与 linux node_modules 已落到宿主磁盘（`/tmp/qa-regtest-20261109/`），不占 kiri VM 盘。
- [x] 静态工具的宿主依赖缺口用项目 venv 与临时 `openapi-spec-validator` 环境补齐（`services/admin-api/.venv/bin/python`、`/tmp/qa-openapi-validator`），**未修改任何 requirements 或镜像**。

---

## 2. 三轮结果总表（逐条勾）

| 项 | R1 修前基线 | R2 修复后复验 | R3 稳定性复跑 | 一致性 |
|---|---|---|---|---|
| A1 环境 / 镜像基线 | 容器全 healthy、网关 200/401、setup 六项 ok；drift FAIL 8 / verify FAIL 8 | 同 R1 | 同 R1 | 三轮一致 |
| A2 安全基线 | 修前 `0 pass / 1 fail`（PyYAML 缺失）→ 修后 `63 / 0` | `63 pass / 0 fail` | `63 pass / 0 fail` | 修复后一致 |
| A3 API 契约 | 46 / 63 / 10 interactions、8 类工具全绿 | 同 R1 | 同 R1 | 三轮一致 |
| A4 deploy/tests | 333 passed / 15 skipped | 333 / 15 | 333 / 15 | 三轮一致 |
| A5 本体权限容器内 | smoke 12 + parity 8 | 12 + 8 | 12 + 8 | 三轮一致 |
| A6 admin-api | 1568 passed / 1 skipped | 1568 / 1 | 1568 / 1 | 三轮一致 |
| A6 chat-api | 3260 passed / 1 skipped | 3260 / 1 | 3260 / 1 | 三轮一致 |
| **A6 合计** | **4828 / 2 / 0 failed** | **4828 / 2 / 0 failed** | **4828 / 2 / 0 failed** | **零偏差** |

- [x] 三轮耗时：R1 64.72s + 131.39s；R2 65.12s + 133.77s；R3 63.43s + 127.88s（波动 < 5%，无性能异常）。
- [x] 三轮复用同一隔离库，后两轮无新增失败 → 测试自清理与幂等成立。
- [x] **本轮修复（文档 + 1 个守卫脚本）未对 A6 引入任何回归**（修前 R1 与修后 R2/R3 计数完全相同）。

---

## 3. 逐轮明细

### 3.1 R1（修前基线）

- [x] **A1**：`./mogo drift` FAIL 8 处漂移；`./mogo verify` FAIL 8 处不一致；`./mogo check` = dev 非外部库无检查项（正常）；`/`、`/admin/`、`/admin/setup` = 200/200/200；`/api/v1/auth/me` = 401；`/admin-api/api/ontologies`（`-L`）= 401；`/admin-api/api/setup/status`（`-L`）= 200、`ready:true`、六项 `ok:true`。
- [ ] **A2 修前**：`./mogo baseline` → `ModuleNotFoundError: No module named 'yaml'` → `0 pass, 1 fail`，rc=1。**守卫未真正执行**（这是本轮发现的代码级缺陷，见 §5）。
- [x] **A3**：宿主 `python3 tools/contract/validate.py` 因缺 PyYAML 失败 → 改在 kiri 容器内（`admin-api:8ae25759` 带 PyYAML）逐服务执行：`admin-api 46 / chat-api 63 / document-parser 10 interactions` 全 OK；`path_naming` OK；`error_codes_uniqueness` 0 专属 / 15 通用；`error_code_mapping` 无 drift；`consumer_refs --all`、`deprecation_check --all` 三服务 OK；`diff.py --old/--new` 自比对 0 breaking；`openapi/validate.py --all` 三服务结构级 + 内置 lint 通过（chat-api 168 提示项不阻断，spectral CLI 未装走内置 lint）；`openapi/probe.py --all` rc=0。
- [x] **A4**：`333 passed, 15 skipped`（20.10s）。
- [x] **A5**：容器内 smoke `12 passed / 0 failed`；mongo parity `8 passed / 0 failed`（cleanup left=0）。
- [x] **A6**：admin `1568 passed / 1 skipped / 0 failed`；chat `3260 passed / 1 skipped / 0 failed`。

### 3.2 R2（修复后复验）

- [x] **A1**：与 R1 完全一致（drift / verify 仍 FAIL 8，属未变更的环境状态）。
- [x] **A2**：`./mogo baseline` → **63 pass / 0 fail**，rc=0（宿主 Python 直接执行，无需手工切 venv 或带 `MOGO_VERSION`）。
- [x] **A3**：三服务契约 46/63/10、path_naming、error_codes 全绿；**quickstart 修正后的 10 条命令逐条实跑 rc=0**。
- [x] **A4**：`333 passed / 15 skipped`（20.04s）—— 证明 `baseline-check.sh` 改动未破坏仓库守卫用例。
- [x] **A5**：12 + 8 passed。
- [x] **A6**：1568 / 1 + 3260 / 1。

### 3.3 R3（稳定性 / 幂等复跑）

- [x] **A1**：与 R1/R2 一致。
- [x] **A2**：`63 pass / 0 fail`。
- [x] **A3**：46/63/10、path_naming、error_codes 全绿。
- [x] **A4**：`333 passed / 15 skipped`（19.33s）。
- [x] **A5**：12 + 8 passed。
- [x] **A6**：1568 / 1 + 3260 / 1（63.43s / 127.88s）。
- [x] **额外幂等校验**：三轮同一隔离库 `mogo_regtest_20261109` 连续执行，未出现「数据残留导致的失败」或计数漂移；A5 每轮 `cleanup left=0`。

---

## 4. 口径坑与差异归因（逐条勾）

- [x] **HTTP 尾斜杠（本轮补齐 11-08 未写全的坑）**：`/admin-api/api/setup/status` 与 `/admin-api/api/ontologies` 不带尾斜杠会 301 到 `/api/v1/...`，必须 `curl -L`；**带尾斜杠**会 301 到带斜杠的 v1 路径并返回 **404**。R1 首次探测用带斜杠路径得到 404，已校正后三轮统一用不带斜杠 + `-L`。
- [x] **A4 与 11-08 差 6 项**：本轮 333 passed / 15 skipped，11-08 为 339 / 9，**总用例数同为 348**。多出的 6 个 skip 全部来自 `test_container_hardening.py:497`「镜像 `<svc>:fd02f69e` 未在本机构建」——是 §5 镜像漂移的连带结果，**非代码回归**；其余 9 skip 与 11-08 同口径（alertmanager e2e ×6、ontology smoke ×1 + mongo parity ×2，后 3 项已在 A5 容器内实跑覆盖）。
- [x] **宿主 Python 不可作为权威**：宿主 `python3`（WorkBuddy 3.13.12）无 `yaml` / `pytest` / `openapi_spec_validator`，直接跑契约工具与基线守卫都会失败；本轮全部改为「kiri 容器内」或「项目 venv」，这正是「以 kiri 为准」的落点。
- [x] **`tools/contract/validate.py` 参数非 append**：`--service a --service b --service c` 只验最后一个；本轮逐服务调用（无参数亦可一次验三份）。
- [x] **`openapi/probe.py --all` 在宿主 venv 的 chat-api 探测 0 端点**（venv 缺 `tenacity`，日志有 `ModuleNotFoundError`），工具仍报 `probe: OK`；环境性，未纳入阻断。
- [x] **chat-api 剩余 1 skip**：`test_dsh_candidate_evaluation.py:59` 需容器内 git（镜像无 git、非 root 无法 apt）；admin-api 剩余 1 skip：`test_drill_credential_scripts.py:112` 硬编码 `127.0.0.1:27017`。两项与 11-08 同，均环境性。

---

## 5. 本轮缺陷与处置（逐条勾）

| ID | 级别 | 标题 | 处置 |
|---|---|---|---|
| N-2 | P2 | `./mogo baseline` 宿主无 PyYAML → 0 pass / 1 fail，安全基线守卫静默失效 | **已修**（自动选带 PyYAML 的解释器），R2/R3 复验 63/0 |
| N-6 | P2 | 025 quickstart 命令口径（上轮遗留 D-3 扩大） | **已修**，全部命令本轮实跑 rc=0 |
| N-3/4/5/7/9 | P2/P3 | README 中英 017 范围 / 计数 / contracts 目录、PPT 统计日期、演练文档断链 | **已修**（文档类，不影响 A6） |
| **N-1** | **P1** | **运行镜像 8 处漂移，`drift` / `verify` FAIL** | **未修**：需重建 7 镜像 + `./mogo up`，影响 kiri 生产栈，待用户决定 |
| N-10 | P3 | OTel instrumentation 依赖缺失（三服务各 8 条 `Instrumentor init failed`），离线 bundle 0 个相关 wheel | **未修**：需补 wheel + 重建镜像 |
| N-11 | P3 | `./mogo baseline --json` stdout 混入诊断行，非纯 JSON | **未修**：局部修复尝试未生效已回退；CI 可用直接脚本 `--json` |
| D-3 / D-5 | P2 / P3 | 11-08 遗留：D-3 本轮已修；**D-5 仍在**（见 N-10） | D-3 闭合 / D-5 保留 |

- [x] 11-06 的 F-1 / F-2 / F-8 与 11-08 的 D-7 / D-8 在 kiri 运行态复验持续有效（探针 healthy、docling 就绪、路径契约 OK、tenant purge 集合完整、测试隔离补丁在位）。

---

## 6. 稳定性结论（逐条勾）

- [x] 三轮 A1–A6 全部执行完成，无中断、无 flaky、无计数偏差。
- [x] A6 每轮 4828 passed / 2 skipped / 0 failed，与 11-08 权威基线零偏差。
- [x] 修复动作（7 项）未引入任何回归：R1（修前）与 R2/R3（修后）A4/A5/A6 计数完全一致。
- [x] 同一隔离库连续三轮 → 测试隔离 / 自清理 / 幂等成立。
- [x] 唯一未闭环的是**环境态镜像漂移**（N-1），不是代码或测试缺陷；它同时解释了 A4 的 6 个 skip 与 `verify` FAIL。
- [ ] 若要求「运行态与 HEAD 零漂移」作为发布门禁，需在重建镜像后**再补一轮 A1/A2/A4 + `drift`/`verify` 复验**；本轮尚未执行。

---

## 7. 未纳入本轮 / 保留项

- [ ] 024 DR 演练（T081 / T085 / T086）、压测扩容（T106 / T107）、B004 全链路重启、B005 备份恢复真实模式、017 切换演练、需真实账号凭据的 049 T022 / T025 与 017 T031 / T042 / T043 / T045 / T046-B·C。
- [ ] alertmanager e2e ×6（A4 skip，需 `AM_E2E=1` + smtp 改造）。
- [ ] `spectral` 规则级 lint（CLI 未装，走内置 lint；规则集在 `specs/025-api-contract-hardening/openapi/.spectral-ruleset.yaml`）。
- [ ] 结构级 OpenAPI 校验在宿主需临时补 `openapi-spec-validator`；kiri 生产镜像未含该包，CI 需自行安装。

---

## 8. 产物与清理建议

| 产物 | 位置 | 大小 | 状态 |
|---|---|---|---|
| linux node_modules | `/tmp/qa-regtest-20261109/node_modules` | 613MB | 保留（三轮复用完毕，可清理） |
| node v24.21.0 二进制 | `/tmp/qa-regtest-20261109/node` | 117MB | 保留（同上） |
| pytest 测试依赖 | `/tmp/qa-regtest-20261109/testdeps` | 14MB | 保留（同上） |
| openapi validator 环境 | `/tmp/qa-openapi-validator` | — | 保留（静态工具用） |
| 隔离测试库 | `mogo_regtest_20261109`（mongo 内） | — | 保留（三轮数据，业务库 `mogo_dev` 未污染） |
| PPT 改前备份 | `/tmp/intro-v4.pptx.bak-20261109` | 143KB | 保留（回滚用） |
| 日志 | `/tmp/qa-d1d3-20261109.log`、`/tmp/qa-r1-a1a2-20261109.log`、`/tmp/qa-r1-a6-20261109.log`、`/tmp/qa-r2r3-a6-20261109.log` | — | 保留 |

> 按工作区规约不擅自删除文件；上述均为 `/tmp` 临时产物与 mongo 隔离库，**未占 kiri VM 盘**（node_modules 落宿主磁盘）。若需清理，请用户确认后单独执行；本轮未新建任何镜像、未改运行容器、未推送远端。

---

*执行者：WorkBuddy 会话；配套审计报告：`deliverables/QA-AUDIT-STANDARD-2026-11-09.md`。*
