# OrbStack 准生产环境回归 · Round 5（2026-10-28）

> ADR-5 多轮回归第五轮。用户指令：用当前提交短哈希执行 `./mogo up --build` 重建并重启全部服务、从 OrbStack 清除上个版本镜像、确认全部 healthy、以 OrbStack ARM 准生产环境执行回归测试。

---

## 一、结论（一句话）

**镜像重建零运行态回归**：`MOGO_VERSION=b6055c8` 构建 7 个服务镜像（tag `b6055c8`）→ 重启全部 12 容器全 `healthy` → 旧版本镜像 **0 残留**；Tier A 守卫 **265 passed / 13 skipped**，性能 **7 passed**，经网关冒烟 **5/5 全绿**。另有 3 个 Tier A 失败为**代码演进断言/配置漂移**（admin-web 路径迁移、两份 nginx 配置漂移、cert-guard 逻辑），与重建部署无关；2 个性能失败为测试环境缺 `fastapi` 依赖，均非部署引入。

---

## 二、执行关键事实

- **HEAD 短哈希**：构建时 `b6055c8`（当时当前提交，2026-10-28 09:13 `fix(admin-web): 214 处旧路径迁到 /api/v1`）；构建后 git HEAD 前进至 `c3a3514`（`playwright bundle 按架构分层`），`mogo/main` 已同步。部署镜像 tag=`b6055c8`，落后当前 HEAD 一个提交——该提交仅改 playwright bundle 打包，**不影响运行态**。
- **构建链路**：`MOGO_VERSION=b6055c8 APT_OFFLINE_INSTALL=false PIP_OFFLINE_INSTALL=false COMPOSE_PARALLEL_LIMIT=1 BUILDKIT_STEP_CONCURRENCY=2 ./mogo up --build`。本地 buildx 构建 7 个服务镜像（gateway / admin-api / user-web / admin-web / chat-api / dsh-runtime-host / document-parser；document-worker 共用 document-parser），`up -d --pull never` 重启。
- **OOM 坑（重要）**：OrbStack VM 仅 **3.9GiB**，build+up 叠加阶段 docker daemon 在 `up` 拉起 12 容器瞬间崩溃（`docker.sock` 消失，`MOGO_BUILD8_EXIT=1`）。根因是串行构建完成后 `up` 瞬时内存峰值压垮 VM。处置：7 个镜像已全部 `build` 落地本地后，改为纯 `./mogo up`（不带 `--build`，buildkit 已释放）启动，`COMPOSE_PARALLEL_LIMIT=4` 降低并发 → `MOGO_UP_EXIT=0`，12 容器全 healthy。
- **构建根因修复（已随提交固化进 `mogo/main`）**：
  - `apps/user-web/pnpm-workspace.yaml` 的 `allowBuilds` 需 `canvas: false`（跳过无 Python 的 slim 镜像编译 node-canvas——它仅 jsdom 传递依赖、生产静态构建不用）+ `vue-demi: true`（naive-ui 传递依赖的 postinstall 须放行，否则 pnpm 严格模式 `ERR_PNPM_IGNORED_BUILDS`）。
  - `docker-compose.build.yml` 的 `APT_OFFLINE_INSTALL` / `PIP_OFFLINE_INSTALL` 映射（默认 `true`，运行时显式 `false` 走网络绕过离线包缺料）亦已随提交固化。
- **未提交改动（其他会话在途，按 ADR-5 不动，本次未提交）**：`deploy/production/prepare-release.sh`、`services/chat-api/app/main.py` 等 `M` 文件；另有若干未跟踪新文件（portainer 模板、render 脚本、panweidb 迁移检查文档）。用户已确认**保持现状不提交**。
- **环境基线**：`MOGO_DATA_BACKEND=PanWeiDB`、`MOGO_TLS=0`、`MOGO_NGINX_CONF=./deploy/docker/nginx.conf`（纯 HTTP，探针 `http://127.0.0.1:3000`）。

---

## 三、Tier A 守卫重跑（验证重建零回归）

隔离 venv `/tmp/mogo-round5-venv`（pytest 9.1.1 + pytest-asyncio + pyyaml + requests + pydantic-settings + starlette + httpx + fastapi）：

```bash
COMPOSE_PROFILES=pool MOGO_TLS=1 PYTHONPATH=services/admin-api \
  python -m pytest deploy/tests/ -q -p no:cacheprovider \
  --ignore=deploy/tests/test_performance_us7.py \
  --ignore=deploy/tests/test_ontology_permission_mongo_parity.py
# 装齐依赖后：265 passed, 13 skipped, 3 failed
```

合计 **265 passed / 13 skipped**。**3 failed 归因（均非部署回归）**：

1. `test_admin_web_exchanges_token_via_post` — 断言硬编码 `/api/auth/sso/exchange`，但 `b6055c8` 把 admin-web 路径迁到 `/api/v1/*`，测试断言过时（代码演进）。
2. `test_tls_configs_are_semantically_equivalent` — `deploy/nginx/nginx.conf` 与 `deploy/docker/nginx-https.conf` 两份静态配置漂移（配置演进）。
3. `test_tls_cert_guard_reads_switch_from_dotenv` — cert-guard 在 HTTP 模式（`MOGO_TLS=0`）仍生成了证书，单元级逻辑/测试预期不一致。

> 注：初跑曾现 2 个 audit 测试（`test_audit_retention_*` / `test_audit_db_is_separable_*`）因 venv 缺 `pydantic_settings` 而 `import` 失败（`ModuleNotFoundError`），装包后翻绿 → 263→265 passed。`MOGO_TLS=1` 仅让 cert-guard 守卫进入 TLS 分支断言，与部署 env 分离（Round 4 同款处理）。

---

## 四、性能测试（US7）

```bash
PYTHONPATH=services/chat-api python -m pytest deploy/tests/test_performance_us7.py -q -p no:cacheprovider
# 装齐 fastapi 后：7 passed（与 Round 4 一致）
```

> 初跑 2 个 CORS p95 测试（`test_cors_preflight_p95_under_50ms` / `test_cors_rejection_p95_under_50ms`）因 venv 缺 `fastapi` 而 `import` 失败，装包后 **7 passed**，证实为测试环境依赖缺失，非性能/部署回归。

---

## 五、经网关冒烟（运行态，重建后）

| 路径 | 直接 | 跟随 301 | 说明 |
| --- | --- | --- | --- |
| `/healthz` | 200 | — | 网关健康检查 |
| `/admin/` | 200 | — | admin-web 前端 |
| `/admin-api/api/setup/status` | 301 | **200** → `/admin-api/api/v1/setup/status` | 旧路径 301 重定向（6a5af6c 平滑迁移设计） |
| `/askai-api/health` | 200 | — | chat-api（自报 `version: 0.2.5`，`backend: panweidb`，`dsh_host: healthy`，`reachable: true`） |
| `/api/auth/me` | 301 | **401** → `/api/v1/auth/me` | 旧路径 301 重定向；跟随后正确拒绝未认证 |

**5/5 实际全绿**：2 个 301 是 gateway 对旧 `/api` 路径重定向到新 `/api/v1` 前缀的设计行为（6a5af6c），跟随后落点正常（200 / 401）。

---

## 六、镜像清理核验

| 项 | 结果 |
| --- | --- |
| 新镜像 `*:b6055c8` | 7 张存在（document-worker 共用 document-parser） |
| 旧版本镜像（570012e / 6a5af6c / cef9561 / e6289d9 等） | **0 张残留**（被此前增量部署淘汰/覆盖） |
| dangling 悬空镜像 | 0（`docker image prune` 无回收） |
| 容器运行 tag | 全部 `b6055c8`，均 `Up (healthy)`（document-worker 无 healthcheck 属正常） |

---

## 七、本轮已闭环项（Done）

- 镜像重建 `b6055c8`：7 服务本地构建（串行 OOM 规避）→ 纯 `up` 启动（daemon 恢复后）→ 旧版本镜像 **0 残留**。
- 全部 12 容器统一 `b6055c8` 且 healthy（含此前 `Exited` 的 mongo 已恢复）。
- Tier A 守卫 265/13、性能 7 passed、冒烟 5/5，运行态零回归。

---

## 八、遗留待办（Open → 移交 Round 6+）

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 3 个 Tier A 失败（admin-web 路径断言、nginx 双配置漂移、cert-guard HTTP 误生成证书） | 代码/测试演进不一致 | 需开发跟进：更新测试断言至 `/api/v1`、对齐两份 nginx 配置、修正 cert-guard 逻辑；均非部署引入 |
| 部署镜像落后 HEAD 一个提交（b6055c8 vs c3a3514） | 配置卫生 | c3a3514 仅改 playwright bundle 打包，不影响运行态；如需最新 HEAD 部署可重跑 `./mogo up --build` |
| `docker-compose.build.yml` 离线映射临时改动 | 仓库卫生 | `APT_OFFLINE_INSTALL`/`PIP_OFFLINE_INSTALL` 映射已随提交固化，默认值 `true`；离线包补全前建议保留显式 `false` 覆盖，或还原映射恢复仓库干净 |
| TLS 启用 | 维持 `MOGO_TLS=0` | 仍拍板不动 |
| 故障转移 / 压测 | 未排 | Tier C |

Open objectives: 以 OrbStack 为准生产环境执行多轮回归（ADR-5，m00002）。
