# ARM 准生产回归 · kiri（2026-11-08）

> 被测环境：**kiri** 引擎（Kiri 0.1.18，OCI image store），`linux/arm64` dev profile 栈（mongo 后端），全局默认 docker context = `kiri`
> 被测构建：`ghcr.io/mogoai/<svc>:8ae25759` ×7（= 当前 HEAD，运行镜像与 HEAD 零漂移）
> 构建入口：`docs/dev-build-guide.md` §7.1（kiri 构建须固定 `BUILDX_BUILDER=kiri`）
> 回归范围：沿用 2026-11-06 OrbStack 轮的 A 组口径（A1–A6）；DR 演练 / 压测扩容 / 017 切换演练仍未纳入
> 结论：**A1–A6 全绿**（A6 合计 4828 passed / 2 环境性 skipped / 0 failed）。
> 本轮新发现缺陷 **D-7 / D-8 两项，均已修复并复验**（用户确认后执行，见 §8）；上轮遗留 D-3 / D-5 仍在。
> 环境侧处置：kiri VM 磁盘 63G 曾 100% 满，经用户确认清空两个 buildkit 缓存（约 39G），现余 36G（见 §9）。

---

## 0. 被测版本口径

- 7 个业务镜像 tag `8ae25759` = `git rev-parse --short HEAD`，`./mogo drift` / `verify` 零漂移，**本轮是纯净 HEAD 口径**（不同于 11-06 轮的「HEAD + 在途文件」混合口径）。
- 工作区基线仅有两份**已删除文档**的在途改动（`docs/2026-11-01-full-qa-audit-r13.md`、`docs/kiri-dev-build-guide.md`，属其他会话），不进镜像、不影响本轮结论。
- 轮中修复 D-8 后**单独重建了 document-parser 镜像**（当时 tag `8ae25759`，新 Image ID `62d94d8e73e0`），document-api / document-worker 已切换到新镜像；其余 6 个镜像保持轮初状态。D-7 为 compose 声明修改，随 `./mogo up` 生效。两项修复已提交为 `17a35da3`（提交后 HEAD 前移，运行态仍为 `8ae25759` 构建，`./mogo drift` 会报版本漂移属预期，下次重建即归零）。

## 1. A1 环境与镜像基线

| 项 | 结果 |
|---|---|
| 11 个业务容器 healthy（修复后，含 document-worker） | PASS（轮初 worker unhealthy → D-7，见 §8） |
| 网关入口 `/`、`/admin/`、`/admin/setup` | 200 / 200 / 200 PASS |
| 未认证契约 | `/api/v1/auth/me` 401；`/admin-api/api/ontologies/` 401 PASS |
| 初始化状态 | `/admin-api/api/setup/status` → `ready:true`（租户 `bonc-2331b8a0ecdbd2ebcbf253c4`），修复后六项服务全 `ok:true` PASS |
| 服务探针（容器网内） | chat-api `/health`+`/ready` 200（version 0.2.7、dsh_host healthy）；admin-api `/health`+`/ready` 200；document-api `/api/health`+`/ready` 200；修复后 `/api/ready` 200 且五项 checks 全 true |
| `./mogo drift` | 55 项比对 / 12 服务，零漂移 PASS |
| `./mogo check` | dev 非外部库，无检查项 PASS |
| `./mogo verify` | 11 服务运行镜像与预期产物一致 PASS |

口径更正（相对 11-06 报告）：

- 上轮 A1 写的 `/api/v1/ontologies` 401 实为当时 chat-api 的路由；现网关 `/api/` 转 chat-api，该路径已 404。本体路由在 **admin-api**（`/admin-api/api/ontologies/`），未认证 401 契约不变。
- `/admin-api/api/setup/status` 不带尾斜杠会 301，需跟随重定向（与 11-03 模型中心 308 同类坑）。
- 轮初 setup status 的 `document-processing: ok=false (HTTP 503)` 是 D-8 的连带表现（`/api/ready` 的 docling 检查恒 false），修复后转绿。

## 2. A2 容器安全基线（024 B010 口径）

- `./mogo baseline`：**63 pass / 0 fail**（修复前后各跑一次，均全绿；不再需要手工带 `MOGO_VERSION`，D-2 修复持续有效）
- 运行时实测（chat-api / admin-api / document-api / gateway）：`uid=10001`、`read_only=true`、`cap_drop=[ALL]`、`no-new-privileges:true` 全 PASS

## 3. A3 025 API 契约回归

| 检查 | 结果 |
|---|---|
| `tools/api_check/path_naming.py` | OK — 无动词段路径 |
| `tools/api_check/error_codes_uniqueness.py` | OK — 0 服务专属码 / 15 通用码 |
| `tools/contract/validate.py`（逐服务） | OK — admin-api 46 / chat-api 63 / document-parser 10 interactions |
| `tools/openapi/validate.py --all` | OK — 三服务阻断项全过（chat-api 168 条提示项不阻断；spectral CLI 未装，走内置 lint） |
| admin-api `tests/api`（门控容器内） | 27 passed |

工具口径注意：`validate.py --service a --service b --service c` 只校验**最后一个**服务（参数非 append），须逐服务调用；上轮报告的合并写法实际只验了 document-parser，本轮已逐个补齐。D-3（025 quickstart 第 13–15 项）仍未修。

## 4. A4 deploy/tests 仓库级守卫

- **339 passed / 9 skipped**（轮初与 D-7 compose 修改后各跑一次，结果一致；`env -u PYTHONPATH python3 -m pytest deploy/tests -q`）
- 相对上轮 331 的 **+8 来自 `94e34d72`**（`test_deploy_push_guard.py` 新增推送判等用例），非异常增长。
- 9 项 skip 同上轮口径：ontology smoke ×1 / mongo parity ×2（已在 A5 容器内实跑）、observability alerting e2e ×6（需 `AM_E2E=1` + smtp 改造，仍可补项）。

## 5. A5 030 本体权限容器内端到端

```
docker exec -i mogo-admin-api-1 sh -c '. /run/askai-secrets/runtime.env; export ASKAI_ADMIN_JWT_SECRET; python -' \
  < deploy/tests/test_ontology_permission_smoke.py        → 12 passed / 0 failed
docker exec -i mogo-admin-api-1 sh -c '. /run/askai-secrets/runtime.env; export ASKAI_ADMIN_JWT_SECRET; python -' \
  < deploy/tests/test_ontology_permission_mongo_parity.py →  8 passed / 0 failed（cleanup left=0）
```

## 6. A6 双服务全量 pytest（门控镜像内执行）

| 服务 | 结果 |
|---|---|
| admin-api | **1568 passed / 1 skipped / 0 failed**（66s） |
| chat-api | **3260 passed / 1 skipped / 0 failed**（142s，第三跑） |
| 合计 | **4828 passed / 2 skipped / 0 failed** |

### 6.1 执行口径与上轮的差异（重要）

**kiri 的容器网段宿主不可达**（`172.19.0.3:27017` 连接超时，不同于 OrbStack 的 VM 直通），上轮「宿主跑 + `MONGODB_URI=<VM IP>`」口径在 kiri 上不可行。本轮改为**临时容器 + workspace 同路径挂载**：

```
docker run --rm --network mogo_backend \
  -v /Users/cooper/mogo:/Users/cooper/mogo -w /Users/cooper/mogo/services/<svc> \
  -e MONGODB_URI=mongodb://mongo:27017 -e MONGODB_DB=mogo_regtest_20261108 \
  <image> python -m pytest -p no:cacheprovider -o addopts='-q'
```

- 挂载必须保持 `/Users/cooper/mogo` 原深度：`tests/api/test_semantics.py:29` 用 `Path(__file__).parents[4]` 定位仓库根，浅挂载会 `IndexError`。
- 隔离库 `mogo_regtest_20261108`，不污染业务库 `mogo_dev`。
- 两个镜像都没有 `pytest-timeout`（runner 闭包只含 pytest + pytest-asyncio 六件套），用 `-o addopts='-q'` 覆盖 pyproject 里的 `--timeout=120`；asyncio 模式等其余配置不受影响。
- admin-api 用现网镜像 `admin-api:8ae25759`（自带 pytest 9.1.1）；chat-api 现网镜像无 pytest，按 2026-11-04 的门控口径构建了测试镜像 `chat-api:8ae25759-test`（`INSTALL_TEST_DEPS_AT_BUILD=true` + overlay 同款系统依赖/playwright 参数，离线 bundle 全命中，chromium launch OK）。**这是权威口径**（镜像内 pin 版本，无宿主 pydantic 偏移问题）。

### 6.2 chat-api 三轮归因（首跑红 → 全绿，均环境性，非代码回归）

| 轮次 | 结果 | 归因 |
|---|---|---|
| r1 | 3 failed / 3249 passed / 9 skipped | 容器无 Node：3 个 conversation_regression 用例 `pytest.fail`，6 个 Node 门控 e2e skip |
| r2 | 8 failed / 3252 passed / 1 skipped | 补 node v24.21.0（从 dsh-runtime-host 镜像复制到 volume）后 Node 门控用例转跑，但 workspace 挂载的 `dsh/runtime-host/node_modules` 是 **macOS 安装**，缺 linux 原生绑定：`No usable native binding found for node-addon-require-builtin-linux-arm64-gnu`，DSH host 起不来 |
| r3 | **3260 passed / 1 skipped** | 从 `dsh-runtime-host:8ae25759` 镜像 `docker cp` 出 linux 版 node_modules（613MB）到宿主磁盘，bind-mount 覆盖 `runtime-host/node_modules`；另设 `MOGO_E2E_MONGO_URI=mongodb://mongo:27017` 解锁 canvas mongo e2e |

剩余 1 skip：`test_dsh_candidate_evaluation.py:59` 需容器内有 git（镜像无 git，非 root 无法 apt），环境性。
admin-api 的 1 skip：`test_drill_credential_scripts.py:112` 硬编码 `127.0.0.1:27017` 本地 mongod，容器内不可达，环境性。

## 7. 缺陷清单（本轮）

| ID | 级别 | 标题 | 位置 | 现状 |
|---|---|---|---|---|
| D-7 | **P1（探针恒红）** | document-worker healthcheck 用 `celery@$HOSTNAME`：`HOSTNAME` 是 bash 自设变量，镜像 `/bin/sh`(dash) 不导出，目标退化成 `celery@` 恒不应答；worker 本体正常（celery ready、广播 ping OK），FailingStreak 380+ | `docker-compose.yml:1122` | **已修并复验**：改 `celery@$$(hostname)`，容器重建后 healthy |
| D-8 | **P1（功能不可用）** | docling 模型 bundle tar 顶层目录带 `0700 root`，解包后运行用户 10001 读不到 → `docling_runtime_status` 恒报 assets missing、`/api/ready` 恒 503（docling:false）、setup status document-processing 红；**文档解析运行时实际不可用** | `services/document-parser/Dockerfile:272`（解包处） | **已修并复验**：解包后 `chmod -R a+rX`，重建镜像后 api/worker 两容器 `docling_runtime_status=(True,…)`、`/api/ready` 200 五项全 true |
| D-3 | P2 | 025 quickstart 第 13–15 项命令口径（上轮遗留） | `specs/025-api-contract-hardening/quickstart.md` | 未修 |
| D-5 | P3 | OTel instrumentation 依赖缺失，`Instrumentor init failed`（上轮遗留，本轮启动日志仍在） | `app/common/observability_base.py` + requirements | 记录，非阻断 |

D-1 / D-2 / D-4 / D-6（上轮已修）本轮复验持续有效：三服务 `/ready` 200、检查命令免 `MOGO_VERSION`、compose 校验通过、bootstrap 正常退出。

## 8. D-7 / D-8 修复与复验记录

用户确认「两个都修」后执行：

1. `docker-compose.yml`：worker healthcheck `celery@$$HOSTNAME` → `celery@$$(hostname)`，注释同步更正（原注释声称「既不会假阳也不会假阴」不成立）。
2. `services/document-parser/Dockerfile`：离线 bundle 解包后追加 `chmod -R a+rX "${DOCLING_ARTIFACTS_PATH}"`（在线下载分支默认 755 不受影响，未动）。
3. 单镜像重建：`docker buildx build --builder kiri --load` + overlay 同款 args（INSTALL_SYSTEM_DEPS / INSTALL_PYTHON_DEPS / INSTALL_DOCLING_MODELS=true、APT/PIP_OFFLINE=true、PYTORCH_ACCELERATOR=cpu），产出新 `document-parser:8ae25759`（ID `62d94d8e73e0`）。未走 `./mogo up --build` 全量重建，避免无谓重打其余 6 镜像。
4. `MOGO_BASE_IMAGE_POLICY=local ./mogo up` 应用新镜像与新探针。

复验：

```
document-worker / document-api   Up (healthy)
worker 探针容器内实测             rc=0
docling_runtime_status           api/worker 均 (True, '/opt/docling/models')
document-api /api/ready          200，checks mongo/redis/weaviate/worker/docling 全 true
setup status                     ready:true，六项服务全 ok
./mogo baseline                  63 pass / 0 fail
./mogo drift                     55 项 / 12 服务，零漂移
./mogo verify                    11 服务 OK
deploy/tests（修复后复跑）        339 passed / 9 skipped
```

两项修复已提交为 `17a35da3`（fix(deploy) 一笔，本报告另笔）。

## 9. 环境侧处置：kiri VM 磁盘满

- 现象：A6 需要把 runtime-host 镜像的 linux node_modules 拷入 volume 时 `No space left on device`；容器内 `df` 显示 **63G 已用 100%（余 223MB）**。宿主磁盘充足（684G 可用），瓶颈在 kiri VM 虚拟盘。
- 占用大头：两个 buildkit 缓存——`kiri`(kiri-build0) 19.4G + 遗留 `buildx_buildkit_kiri-cn0` 容器 16.9G（其 builder 配置已不存在，`buildx ls` 查无）。
- 用户确认「清两个缓存」后：`docker buildx prune --builder kiri -f`（释放 20.78GB）+ `docker exec buildx_buildkit_kiri-cn0 buildctl prune --all`（释放 18.15GB）。VM 盘降至 **42%（余 36.4G）**。
- 代价：暖缓存清空，本轮 document-parser 重建全层重跑（离线 bundle 命中，实际耗时可接受）；后续首次全量构建会明显变慢，需重新暖缓存。
- node_modules 改用 `docker cp` 落宿主磁盘（`/tmp/mogo-regtest-20261108/dsh-node-modules`，613MB）再 bind-mount，不占 VM 盘。

## 10. 未纳入本轮 / 待办

- 同上轮：024 DR 演练 / 压测扩容 / B004 全链路重启 / B005 备份恢复真实模式 / 017 切换演练 / 需真实账号凭据的项。
- alertmanager e2e ×6（A4 的 skip 大头）仍属可补项。
- D-7 / D-8 修复已提交推送（`17a35da3`）；测试产物（`-test` 镜像、`mogo-node-bin` volume、`/tmp/mogo-regtest-20261108/`、隔离库）经用户确认已清理。遗留 `buildx_buildkit_kiri-cn0` 容器与 `buildx_buildkit_default_state` 卷未动，待后续决定。
- 建议把本轮 A6 口径（kiri 网段宿主不可达 → 门控镜像 + 同路径挂载 + linux node_modules 覆盖）补进 `docs/dev-build-guide.md`，避免下轮重踩 r1/r2 两个坑。

---

*执行者：Qoder Desktop 会话；数据落点：`/tmp/a4-20261108.log`、`/tmp/a4-20261108-r2.log`、`/tmp/a6-admin-20261108.log`、`/tmp/a6-chat-20261108.log`（r1）、`/tmp/a6-chat-20261108-r2.log`、`/tmp/a6-chat-20261108-r3.log`、`/tmp/a6-chat-test-image-build-2.log`、`/tmp/d8-docparser-rebuild.log`、`/tmp/d7d8-up.log`*