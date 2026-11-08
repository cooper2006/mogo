# ARM 准生产回归 · OrbStack（2026-11-06）

> 被测环境：OrbStack `linux/arm64` dev profile 栈（mongo 后端），12 容器 + bootstrap
> 被测构建：`ghcr.io/mogoai/<svc>:ab0f7369` ×7（离线 bundle 重建）
> 构建入口（当时）：`docs/kiri-dev-build-guide.md` §6.1 `./mogo --profile dev up --build`（该指南已于 2026-11-08 停用；现行入口见 `docs/dev-build-guide.md` §7）
> 回归范围：A 组黑盒契约 + 健康回归（A1–A6）；DR 演练 / 压测扩容 / 017 切换演练未纳入本轮
> 结论：**A1/A2/A3/A5/A6 全绿**；A4 `331 passed / 9 skipped`（23:20 首跑，同夜 D-4 解除后复跑同样通过，见 §10.4）。
> 另计 6 项缺陷：D-1 应用代码 P1、D-4 在途 compose P1（阻塞 CLI）、D-2 工具链口径 P2、D-6 bootstrap chown P1（阻塞启动，D-4 修复引入）**四项已修复并复验（见 §10）**；D-3 文档口径部分修复（024 已改，025 第 13–15 项未改）、D-5 未修。

---

## 0. 被测版本口径（重要）

镜像 tag 写作 `ab0f7369`，但**内容 = `ab0f7369` + 工作区 17 个其他会话在途未提交文件**。
已核验确实进入镜像（容器内 `grep`）：

| 在途改动 | 镜像内证据 |
|---|---|
| admin-api `memories.py` 路由资源化（`GET /list`→`GET ""`、`POST /{id}/delete`→`DELETE /{id}`） | `/app/app/api/routes/memories.py:435 @router.get("")`、`:985 @router.delete("/{memory_id}")` |
| 三服务 `pg_compat.py` `quoted_col` 重构 | `/app/app/core/pg_compat.py:746` |
| admin-api `tenant_purge.py` 补 `projects` / `memory_policies` | 命中 2 处 |

因此本轮结论**不等价于对 v0.2.7 发布提交 `ab0f7369` 的纯净回归**。若需要纯净口径，
应在独立 worktree 构建（bundle 需一并复制）或待这些在途改动提交后重建。

---

## 1. 构建与环境

- 离线 bundle 全命中，0 联网：基础镜像 7 tar + 服务层 bundle 8 项（pip-wheels / apt / playwright / docling）
- 基础镜像规范名带 digest（`python@sha256:55432f…` 等），BuildKit 未重解析 manifest
- 构建结果（7 镜像全部产出）：admin-api 465MB / chat-api 4.38GB / document-parser 5.26GB / dsh-runtime-host 1.3GB / gateway 30.9MB / user-web 47.4MB / admin-web 45.7MB
- 旧 `:e7966c99` 镜像被 CLI 自动 prune（回收 ~10.7GB），回滚需按 commit 重建
- 12 容器全部 `healthy`，chat-api `/health` 报 `version 0.2.7`、`dsh_host healthy`；容器内 DSH `0.2.2-rc.1` 与 compose 声明一致

### 构建踩坑（补充到 guide 的建议）

`docker compose -f docker-compose.yml up --build` **不可用于本仓库**：不带
`docker-compose.build.yml` 时 compose 无 `build:` 段，按 pull 模式去找
`ghcr.io/mogoai/*:latest`（本地不存在），会在 recreate 阶段报
`No such image ... :latest`。唯一正确入口是 CLI（`MOGO_COMPOSE_BUILD=true` 时才并入 build overlay）：

```bash
MOGO_DATA_BACKEND=mongo ./mogo --profile dev up --build
```

本次误跑一次，13 容器在 recreate 前中止、零损伤。

---

## 2. A1 环境与镜像基线

| 项 | 结果 |
|---|---|
| 12 容器 healthy + 全部新 tag | PASS |
| 网关入口 `/`、`/admin/`、`/admin/setup` | 200 / 200 / 200 PASS |
| 未认证契约 | `/api/v1/auth/me` 401、`/api/v1/ontologies` 401 PASS |
| 初始化状态 | `/admin-api/api/setup/status` → `"ready":true`（租户 `bonc-2331b8a0ecdbd2ebcbf253c4`）PASS |
| 服务探针（容器网内） | chat-api `/health`+`/ready` 200；admin-api `/health` 200；document-api `/api/health` 200 |
| `./mogo drift` | 7 服务声明一致（需带 `MOGO_VERSION`，见 D-2）；dsh-runtime-host 报命名口径漂移（声明 `:dsh-0.2.2-rc.1` vs 构建 `:ab0f7369`） |
| `./mogo check` | dev profile 非外部库，无检查项 PASS |
| TLS | 本栈按 `.env` 走 `MOGO_NGINX_CONF=./deploy/docker/nginx.conf`（HTTP-only 兜底），容器内无 443；宿主 443/IPv4 被第三方代理（Steam++）占用 → 本轮不评 TLS |

## 3. A2 容器安全基线（024 B010 口径）

- `./mogo baseline`（带 `MOGO_VERSION`）：**55 pass / 2 fail**，2 项均为 `image-present` 命名口径（见 D-2），非加固缺陷
- 不带 `MOGO_VERSION` 时 7 项 `image-present` 找 `:latest` → 假失败
- 运行时实测：`read_only` / `cap_drop ALL` / `no-new-privileges` / `user=10001:10001` 全 PASS；
  `docker exec ... id -u` = 10001（chat-api / admin-api / document-api / gateway）

## 4. A3 025 API 契约回归

| 检查 | 结果 |
|---|---|
| `tools/api_check/path_naming.py` | OK — 无动词段路径 |
| `tools/api_check/error_codes_uniqueness.py` | OK — 0 服务专属码 / 15 通用码 |
| `tools/contract/validate.py --service admin-api/chat-api/document-parser` | OK — 46 / 63 / 10 interactions |
| `tools/openapi/validate.py --all` | OK — 三服务阻断项全过（chat-api 168 条提示项不阻断；spectral CLI 未装，走内置 lint） |
| `services/admin-api/tests/api` | 27 passed |
| quickstart 第 13–15 项命令 | **不可执行**：`validate.py --side` 与 `diff.py --fail-on-breaking` 参数已不存在（见 D-3） |

## 5. A4 deploy/tests 仓库级守卫

- **331 passed / 9 skipped**（23:20，`env -u PYTHONPATH python3 -m pytest deploy/tests -q`）
- 9 项 skip 的处置：
  - `test_ontology_permission_smoke.py` ×1 → 已在容器内实跑 **12/12 PASS**（见 A5）
  - `test_ontology_permission_mongo_parity.py` ×2 → 已在容器内实跑 **8/8 PASS**，自建数据 `left=0`
  - `test_observability_alerting_e2e.py` ×6 → 仍未跑：需 `AM_E2E=1` + 临时改 `deploy/alertmanager/alertmanager.yml` 的 `smtp_smarthost`（宿主非 root 绑不了 25）；本地有 `prom/alertmanager:v0.27.0` 镜像，属可补项
- 23:22 起同一命令转为 **57 failed**，根因是并行会话在 `docker-compose.yml` 加了 compose 不支持的顶层键 `no_new_privileges: true`（4 处），使 `docker compose config` 直接校验失败（见 D-4）。`git show ab0f7369:docker-compose.yml` 校验通过，可确认与本轮回归无关。**截至本报告收尾（23:5x）该文件仍为 23:22:48 版本、仍校验失败，故 A4 无法复跑**；本轮以 23:20 的 `331 passed / 9 skipped` 为 A4 结论。

## 6. A5 030 本体权限容器内端到端

```
docker exec -i mogo-admin-api-1 sh -c '. /run/askai-secrets/runtime.env; export ASKAI_ADMIN_JWT_SECRET; python -' \
  < deploy/tests/test_ontology_permission_smoke.py        → 12 passed / 0 failed
docker exec -i mogo-admin-api-1 sh -c '. /run/askai-secrets/runtime.env; export ASKAI_ADMIN_JWT_SECRET; python -' \
  < deploy/tests/test_ontology_permission_mongo_parity.py →  8 passed / 0 failed
```

覆盖：列表/sync/config/批量授权去重/回读/角色四态/删除/审计/开关复原/未认证 401/内部无凭证 401；
对拍侧覆盖 upsert 保真、`for_subjects` 命中、审计读写、`sys_config`、确定性 `_id`、清理 `left=0`。

## 7. A6 双服务全量 pytest

| 服务 | 结果 |
|---|---|
| admin-api | **1565 passed / 0 skipped / 0 failed**（`ADMIN_RC=0`） |
| chat-api | **3261 passed / 0 skipped / 0 failed**（`CHAT_RC=0`） |
| 合计 | **4826 全绿**，与 2026-11-06 真环境复跑基线计数一致 |

执行口径：`env -u PYTHONPATH -u NO_PROXY -u no_proxy -u HTTP_PROXY -u HTTPS_PROXY MONGODB_URI=mongodb://192.168.97.2:27017 MONGODB_DB=mogo_regtest_20261106 python3 -m pytest -q -p no:cacheprovider`
——真实 MongoDB 走**隔离库** `mogo_regtest_20261106`，不污染业务库 `mogo_dev`。

### 7.1 首轮红、净化后转绿的归因（不是代码回归）

未净化时 admin-api 2 failed / chat-api 28 failed，逐条归因如下：

| 失败簇 | 例数 | 根因 | 处置 |
|---|---|---|---|
| `pymongo ConfigurationError: Empty host` | admin 2 / chat 9 | 宿主未设 `MONGODB_URI`（chat 读 `MONGODB_URI` 而非 `MONGO_URI`），与 2026-11-04 记录同一坑 | 补 `MONGODB_URI` 后消除 |
| `httpx.InvalidURL: Invalid port: ':1]'` | chat 19 | 宿主 `NO_PROXY` 含 `[::1]`（第三方代理注入），httpx 解析代理白名单时炸；容器内无该环境变量 | `-u NO_PROXY` 后消除 |

镜像与宿主 `httpx` 同为 0.28.1（非版本偏移）；`pydantic` 宿主 2.14.2 vs 镜像 pin 2.11.7
存在偏移，故**宿主跑只能作指示，权威口径应在门控测试镜像内跑**
（`INSTALL_TEST_DEPS_AT_BUILD=true`，见 2026-11-04 记录；本轮因 D-4 阻塞未做）。

---

## 8. 缺陷清单

| ID | 级别 | 标题 | 位置 | 现状 |
|---|---|---|---|---|
| D-1 | **P1** | `/ready` 在 admin-api/document-parser 两服务恒 503（就绪探针恒失败） | `services/admin-api/app/observability/health.py:41`、`services/document-parser/app/observability/health.py:24-25`、`app/core/resilience.py:253`（两处） | **已修**，见 §10；根因比原判断更深 |
| D-2 | P2 | CLI 检查脚本不解析构建期版本，恒按 `:latest` / release-train 比对 | `deploy/cli/drift-check.sh`、`deploy/cli/verify-artifact.sh`、`deploy/cli/baseline-check.sh` | **已修（两笔）**：§10.6 baseline/drift/verify 镜像解析对齐；§10.7 `drift-check.sh:45` bash 3.2 空数组崩溃 + 024 quickstart 裸调口径 |
| D-3 | P2 | 025 quickstart 第 13–15 项命令与工具现状不符 | `specs/025-api-contract-hardening/quickstart.md` | 未修 |
| D-4 | **P1（环境阻塞）** | 并行会话给 `docker-compose.yml` 加了 compose 不支持的服务级键 `no_new_privileges`，`docker compose config` 校验失败，`./mogo status/up/down` 全线不可用 | `docker-compose.yml`（未提交，23:22 起） | **已修**（经用户确认后删掉 4 行非法键，改用 compose 认可的 `security_opt`），见 §10 |
| D-5 | P3 | admin-api 启动日志 `Instrumentor init failed`（镜像未装 `opentelemetry-instrumentation-*`），追踪降级关闭 | `app/common/observability_base.py:275/295` + `requirements.txt` | 记录，非阻断 |
| D-6 | **P1（环境阻塞）** | 重建 `60e8e90d` 时 `bootstrap` 退出 1（`chown: /storage/weaviate/askaiknowledgechunks/*/lsm: Permission denied`），所有依赖它的应用服务不起 | `docker-compose.yml` bootstrap 的 `cap_add: [CHOWN, FOWNER]` + 递归 chown（D-4 修复引入） | **已修**，见 §10.8：`cap_add` 补 `DAC_OVERRIDE` |

### D-1 细节

复现：

```
admin-api     GET /ready → 503 {"backend":"mongo","reachable":false,"reason":"error","error":"AttributeError","redis":"ok"}
document-api  GET /ready → 503 {"backend":"mongo","reachable":false}
```

根因（两条不同）：

1. `health.py:41` 调 `db.get_admin_db()`，但 admin-api `app/core/db.py` 只有 `get_db()` / `get_audit_db()`
   → `AttributeError` → 探测被 `except` 吞成「不可达」，mongo ping **从未真正执行**。
2. `document-parser/app/observability/health.py:24-25` 对**同步**客户端用 `await client.admin.command("ping")`：
   `get_db()` 返回 `pymongo.synchronous.database.Database`（不是 MongoClient，`.admin` 不存在），
   且同步对象不可 await；PanWeiDB 模式下返回 `PgDatabase` 门面同样不可 await
   → **两种后端都恒 503**。

影响面：本 dev 栈容器仍 healthy（healthcheck 走 `/health`），但
`deploy/docker-compose.prod.yml:127` 用 `deploy/probes/readiness.sh http://127.0.0.1:8200`
（打 `/ready`）作 document-api 健康检查，且探针对非 200 直接 `exit 1`
→ 走 024 跨 AZ 生产 compose 时 document-api 永不健康，`depends_on: service_healthy`
会连带卡住 chat-api/admin-api 启动。远程 amd64 生产用的 portainer 模板走
`/health`+`/api/health`，不受影响。admin-api 在 PanWeiDB 模式走 `pg.ping_async()`
（可用），仅 mongo 模式受影响。

建议最小修改（待确认后执行）：admin-api 改 `db.get_db()` 取 client 后 `await client.admin.command("ping")`
（或新增 `get_admin_db()` 返回 client）；document-parser 改为同步
`get_db().client.admin.command("ping")`（PanWeiDB 分支另走 `pg.ping()`）。

> **该建议本身有一处错误，修复时已纠正**：`database.admin.command("ping")` 在 motor 里同样不通
> （见 §10.1），真正可用的形状是 `Database.command("ping")`。

### D-2 细节

`./mogo verify` 报 8 处「镜像不一致 预期=…:latest 实测=…:ab0f7369」，
`./mogo drift` 不带 `MOGO_VERSION` 时报同样漂移，`./mogo baseline` 报 7 处 `image-present` 失败。
脚本用 `docker compose … config` 解析声明，而 `.env` 未设 `MOGO_VERSION` →
回退 `${MOGO_VERSION:-latest}`，与 CLI 构建期 `mogo_default_version()`（`git rev-parse --short HEAD`）不同源。
dsh-runtime-host 另有第二处口径差：声明默认 `${MOGO_DSH_RUNTIME_HOST_IMAGE:-…:dsh-0.2.2-rc.1}`，
构建产物 tag 为 commit 哈希（容器内 DSH 实际版本 `0.2.2-rc.1` 已核验一致，属命名而非内容问题）。

另：`drift-check.sh:45` `export SERVICE_LIST="${SERVICES[*]}"` 在 macOS bash 3.2 + `set -u` 下，
不带 `--service` 时数组为空 → `unbound variable` 直接崩（`./mogo drift` 全量口径不可用）。

---

## 9. 未纳入本轮（按用户口径 A 组范围外）

024 T081/T085/T086（DR 演练）、T106/T107（压测/扩容）、B004（`mogo up` 全链路重启演练）、
B005（备份恢复脚本真实模式）、017 T042/T045（切换演练，需写入冻结）、
017 T031 / 049 T022 与 T025（需 admin + A/B/C 真实账号凭据）。
这些正是「准生产环境」本可解锁的项目，待 D-4 解除后可继续。

---

## 10. D-1 / D-4 修复与复验（同夜续，HEAD `8d135867`）

用户确认范围：「删掉那 4 行后重建」+「D-1、D-4 有问题，你修复一下」。

### 10.1 D-1 的真实根因比原报告更深一层

修 `get_admin_db()` 时先只做这一处，宿主机复跑探针仍 `reachable: False, error: TypeError`。
逐层打开后确认：

```
d.admin          -> AsyncIOMotorCollection   # motor 把未知属性当集合名，没有 command
d.client.admin   -> AsyncIOMotorDatabase     # 可用
await d.command("ping")                       # 可用，且 PgDatabase.command 同样存在
```

即 `resilience.probe_mongo()` 里的 `await database.admin.command("ping")`
（admin-api `app/core/resilience.py:253`、chat-api `:250`）**本身就恒抛 TypeError**，
被 `except Exception` 归一成「不可达」。它一直绿灯，是因为
`services/chat-api/tests/resilience/test_dependency_boundaries.py` 用只带 `.admin.command`
的假对象 `_FakeDatabase` 打桩——假对象的形状和真实 motor 不一致。

最终改法（三处统一成 `Database.command("ping")`，与 `setup.py:132` 既有可用写法一致）：

| 文件 | 改动 |
|---|---|
| `services/admin-api/app/observability/health.py:41` | `db.get_admin_db()` → `db.get_db()` |
| `services/admin-api/app/core/resilience.py:249-256` | `database.admin.command` → `database.command` |
| `services/chat-api/app/core/resilience.py:246-250` | 同上（同一段复制代码） |
| `services/document-parser/app/observability/health.py:18-31` | 同步句柄不再 await，改 `await asyncio.to_thread(database.command, "ping")`（pymongo 与 `PgDatabase` 两种后端都走得通） |
| `services/chat-api/tests/resilience/test_dependency_boundaries.py:29-40` | `_FakeDatabase` 改为真实形状（直接暴露 `command`），删掉多余的 `_FakeAdmin` |

复验（宿主机 + 容器内双向）：

```
mongo 在   → admin-api {'reachable': True, 'reason': 'ok', 'redis': 'ok'}
             document-parser {'reachable': True}
mongo 关闭 → admin-api {'reachable': False, 'error': 'ServerSelectionTimeoutError'}
             document-parser {'reachable': False, 'error': 'ServerSelectionTimeoutError'}
容器内 GET /ready → admin-api 200、document-api 200（此前恒 503）
受影响测试        → chat-api tests/resilience 19 passed、admin-api tests/observability 25 passed
```

chat-api 的 `/ready` 走的是另一套实现（返回 `{'status':'ready',…}`），本就 200；
`probe_mongo` 的修正让它在 mongo 模式下具备可观测性，不是把红灯改成绿灯。

### 10.2 D-4 的修法：非法键换 compose 认可的写法

`no_new_privileges: true` 不是 compose 服务键（4 处：dsh 模板 / bootstrap / redis / weaviate），
删除后以 `security_opt: ["no-new-privileges:true"]` 表达同一意图；redis、weaviate 原本没有
`security_opt`，本次补上——这才是运行态真正生效的写法。相关注释一并改正（原文声称
「门禁读的就是这个布尔键」，不成立）。

配套改 `deploy/cli/drift-check.sh`：
- 声明侧 `decl_nnp` 从 `security_opt` 派生（与 `baseline-check.sh:180` 同口径）；
- 实测侧不能只看 `HostConfig.NoNewPrivileges`——Docker 在该值为 false 时把整个键
  `omitempty` 掉，实际证据在 `HostConfig.SecurityOpt`，两处都读。

### 10.3 顺带发现：bootstrap 的 `user` 声明让它失去 chown 能力

`user: "10001:10001"` 是同一批在途改动加上的，实测：

```
docker run --user 10001 --cap-add CHOWN alpine chown …  → Operation not permitted
```

Docker 不会把 `cap_add` 放进非 root 进程的 ambient 集，所以 bootstrap（它的职责就是
chown 卷）被钉成 10001 后 chown 必失败，而它的 command 用 `/bin/sh -ec`，一失败就整体退出。
weaviate 同理：镜像内无 uid 1000 用户、`mogo_weaviate-data` 属主 root:root，
直接声明 `user: "1000:1000"` 会写不进 `PERSISTENCE_DATA_PATH`。

按用户选择「保留加固 + 用 bootstrap chown」落地为：
- bootstrap 去掉 `user` 钉版（root + `cap_drop ALL` + `cap_add CHOWN,FOWNER` + `no-new-privileges`），
  这是它 chown 能工作的前提；
- bootstrap 挂载 `weaviate-data:/storage/weaviate` 并追加 `chown -R 1000:1000 /storage/weaviate`；
- weaviate 补 `depends_on: bootstrap: service_completed_successfully`，保证 chown 先于启动。

### 10.4 重建与运行态复验（`8d135867`）

```
MOGO_DATA_BACKEND=mongo ./mogo --profile dev up --build   → 成功，prune 回收约 1368 MB
11 容器全部 healthy；7 个应用镜像 tag = 8d135867
mogo-weaviate-1  uid=1000，/var/lib/weaviate 属主 1000:1000，healthy
mogo-redis-1     uid=999，/data 属主 redis:redis，healthy
./mogo baseline  → 55 pass / 2 fail（document-parser image-present、dsh-runtime-host release-train tag，均 D-2 口径）
./mogo drift     → 50 项比对 / 10 服务，仅剩上面那 1 处 D-2 命名漂移，no-new-privileges 零假阳性
./mogo status    → 正常（D-4 期间全线不可用）
deploy/tests     → 331 passed / 9 skipped（A4 复跑已解锁）
```

### 10.6 D-2 第一笔：检查命令的镜像解析对齐（HEAD `8d135867` 之后）

用户确认后按两笔执行。原报的「dsh 假漂移 / baseline 2 处 fail」其实是**同一个根因的两种表现**：
`command_up` 会 `export MOGO_VERSION=$(mogo_default_version)` 再 `mogo_configure_images true`
（[mogo:502-514](../mogo)），而 `command_baseline` / `command_drift` / `command_verify` 直接
`bash` 转给子脚本、从不导出 —— 子脚本里的 `docker compose config` 于是永远看到 `.env`
默认声明（`MOGO_DSH_RUNTIME_HOST_IMAGE` 钉在 `dsh-0.2.2-rc.1`），与运行态的 `:8d135867`
一比就假漂移，`image-present` 也因本地没有钉版 tag 而失败。

改动：

| 文件 | 改动 |
|---|---|
| `mogo:767-775` | 新增 `mogo_configure_check_images()`（复刻 `command_up` 的两行），`command_baseline` / `command_drift` / `command_verify` 各调用一次 |
| `deploy/cli/baseline-check.sh:83-102` | `document-parser` 是共享镜像，compose 无同名服务 → 加 `SERVICE_FOR_IMAGE = {"document-parser": "document-api"}`；本地 tag 兜底原来只按 `name + ":"` 前缀匹配，统一命名后本地是 `<registry>/<service>:<ver>` 匹配不上，补 `endswith("/" + name)` 分支 |

复验（都不再需要手工带 `MOGO_VERSION`）：

```
./mogo --profile dev baseline                      → 63 pass / 0 fail   （此前 55 pass / 2 fail）
./mogo --profile dev drift --service …（10 服务）    → 比对 50 项 / OK，零漂移  （此前 1 处 dsh 假漂移）
./mogo --profile dev verify                        → 11 服务比对 OK     （此前 8 处「预期=…:latest」）
deploy/tests                                       → 331 passed / 9 skipped
```

> **注意**：`specs/024-deployment-hardening/quickstart.md:70` 教的 `bash deploy/cli/drift-check.sh`
> 裸调绕开了 CLI 的镜像导出，仍会报那处 dsh 假漂移；文档口径已在 §10.7 改为 `./mogo drift`。
> 裸调 `./mogo drift`（不带 `--service`）崩在 `drift-check.sh:45` 的 bash 3.2 空数组，
> 即 D-2 的第二笔，同样见 §10.7。

### 10.7 D-2 第二笔 + 文档口径（HEAD `d4c8fbc2` 之后）

两件事一起修：

| 文件 | 改动 | 原因 |
|---|---|---|
| `deploy/cli/drift-check.sh:45` | `export SERVICE_LIST="${SERVICES[*]}"` → `"${SERVICES[*]:-}"` | macOS 自带 bash 3.2 在 `set -u` 下把空数组的 `${arr[*]}` 当未绑定变量直接退出；`:-` 兜底后空数组导出空串，Python 侧 `if os.environ.get("SERVICE_LIST")` 自然走全服务比对，语义不变 |
| `specs/024-deployment-hardening/quickstart.md:70` | `bash deploy/cli/drift-check.sh` → `./mogo drift` | 裸调子脚本不经过 `mogo_configure_check_images`（§10.6），compose 里的 dsh 钉版声明会与运行态比对出假漂移；文档教什么用户就跑什么，口径必须指向 CLI |

复验：

```
./mogo --profile dev drift                         → 55 项比对 / 12 服务，不再崩（此前 unbound variable 直接退出）
MOGO_VERSION=8d135867 ./mogo --profile dev drift    → OK，零漂移
MOGO_VERSION=8d135867 ./mogo --profile dev drift --service gateway --service dsh-runtime-host → 10 项 / OK
deploy/tests                                        → 无引用 drift-check，未受影响
```

> 第一次裸跑报 8 处「镜像漂移 声明=`:d4c8fbc2` 实测=`:8d135867`」是**真漂移**：检查命令现在会把
> `MOGO_VERSION` 默认成 `git rev-parse --short HEAD`，而运行中的 7 个镜像是提交前在 `8d135867`
> 上构建的。带上构建期版本即一致；重跑 `./mogo up` 建新 tag 镜像后裸跑也会归零。

### 10.8 D-6：bootstrap 递归 chown 在 cap_drop ALL 下 EACCES（重建 `60e8e90d` 时暴露）

`./mogo --profile dev up --build` 7 个镜像全部构建成功，但卡在启动：
`Container mogo-bootstrap-1 Error service "bootstrap" didn't complete successfully: exit 1`，
容器日志只有一行 `chown: /storage/weaviate/askaiknowledgechunks/E96OBDOxkzRl/lsm: Permission denied`，
连带 admin-api / chat-api / document-api / dsh-runtime-host / gateway 全部不起。

根因是 **D-4 修复自己引入的**：`cap_drop: [ALL]` 把 `CAP_DAC_OVERRIDE` 也摘了，uid 0 于是失去
「root 无视文件权限」的默认能力；而 weaviate（uid 1000）在 `PERSISTENCE_DATA_PATH` 下建的目录是

```
/d                                     1000:1000 755
/d/askaiknowledgechunks                1000:1000 755
/d/askaiknowledgechunks/<uuid>         1000:1000 755
/d/askaiknowledgechunks/<uuid>/lsm     1000:1000 700   ← chown -R 在这里中止
```

`CHOWN`/`FOWNER` 只保证「能改属主」，不保证「能进入目录」。前三个卷（knowledge/admin-static/askai）
没有这种 0700 子目录所以通过，属主兜底看上去有效，实际是**幂等语义不成立**：卷一旦运行过一段时间，
bootstrap 就会永久失败。这是那笔修复的隐藏前提错误，不是 024 T029 加固方向的问题。

修法：bootstrap 的 `cap_add` 补 `DAC_OVERRIDE`（一次性 root helper，只挂 4 个数据卷，
`no-new-privileges` 与 `cap_drop ALL` 保持不变；长期运行的服务侧加固项一个都没动）。

复验（`./mogo --profile dev up`，镜像不重建）：bootstrap 正常退出，11 容器全 healthy，
7 镜像 tag `:60e8e90d`，三服务容器内 `/ready` 均 200（端口 8100/8200/8000，不是我先前猜的 8000 通用），
gateway `http://localhost:3000/admin/setup` 与 `/ready` 均 200；
`baseline` **63 pass / 0 fail**、`drift` **55 项 / 零漂移**、`verify` **11 服务 OK**。

> 旧 `:8d135867` 7 个 tag 仍在（`up --build` 失败路径不触发 prune，保留回滚能力），
> 与新镜像共享层、体积无增量；清理需用户确认。

### 10.5 仍待处理

- D-2：**两笔均已完成**（§10.6 镜像解析对齐 + §10.7 空数组与文档口径）。
- D-6：**已修**（§10.8，`docker-compose.yml` bootstrap 补 `DAC_OVERRIDE`），但该改动**未提交**，需与后续 compose 变更一起收口。
- D-3：025 quickstart 第 13–15 项命令口径未修；024 quickstart `bash deploy/cli/drift-check.sh`
  已于 §10.7 改为 `./mogo drift`。
- D-5：OTel instrumentation 依赖缺失。
- `services/chat-api/backups/`（046 回填运行产物）仍不入库，未动。

---

*执行者：Qoder Desktop 会话；数据落点：`/tmp/mogo-build-ab0f7369.log`、`/tmp/a6b-admin.log`、`/tmp/a6b-chat.log`、`/tmp/mogo-images-before-ab0f7369.txt`、`/tmp/mogo-up-build-8d135867.log`、`/tmp/a4.log`*
