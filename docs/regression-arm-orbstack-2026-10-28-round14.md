# ARM 准生产回归 · 2026-10-28 round 14（离线 bundle 加速构建）

> 用户指令：离线 bundle 加速构建，`MOGO_VERSION` 设为当前提交短哈希；`./mogo up --build` 打包并重启全部服务；从 OrbStack 去除上个版本残留镜像；确认全部 healthy；以 OrbStack 环境作为 ARM 准生产执行回归测试。
> 本轮 **无代码改动**（HEAD `ee65305`，工作区仅有其他会话的未跟踪文档）。

---

## 一、结论（一句话）

`MOGO_VERSION=ee65305` 离线 bundle 构建成功（21m34s，7 镜像），12 容器 11 healthy（document-worker 无 healthcheck、bootstrap 一次性任务 Exited 0），上个版本镜像 **8 张 / 10.4GB 已自动清零、dangling 0**；服务套件回归 **admin-api 1484 / document-parser 28 / chat-api 3001** 全绿、网关冒烟 **5/5**、deploy 守卫 266 passed 且仅剩 2 项**既有**断言漂移。

---

## 二、首轮失败与根因（重要）

首轮（17:28）在 `dsh-runtime-host` 的 apt 离线步骤失败：

```
E: Package 'ca-certificates' has no installation candidate
E: Unable to locate package gosu
target dsh-runtime-host: failed to solve: ... exit code: 100
```

**根因：基础镜像被并行会话污染成 amd64。** 构建日志早有预警：

```
WARN: InvalidBaseImagePlatform: Base image python:3.13-slim-bookworm was pulled with
platform "linux/amd64", expected "linux/arm64" for current build (line 6)
```

本地 `python:3.13-slim-bookworm` / `node:24-bookworm-slim` / `nginx:1.31.5-alpine3.24-slim` 三个 canonical tag 当时全部是 `linux/amd64`；而离线 bundle 内的 `.deb` 与 `Packages` 索引按宿主 `TARGETARCH=arm64` 生成（`arm64/` 目录），amd64 镜像里的 apt 看不到 arm64 索引 → "no installation candidate" / "Unable to locate package"。**不是 bundle 索引命名/lz4 压缩问题**（该结论在 10-28 早前一轮已修正过，见 vault）。

污染来源：并行会话用 `--platform linux/amd64` 拉取基础镜像导出 x86 生产镜像（`prod-images-ee65305/*.tar`，rsync 到 `bonc@172.17.5.96:~/mogo-deploy`），canonical tag 被覆盖为 amd64。

**修复（仓库既有工具，未改代码）**：

```bash
./scripts/export_base_images.sh verify ./base-images/images/arm64   # 7 archive(s) verified
./scripts/export_base_images.sh load   ./base-images/images/arm64   # python/node/nginx → linux/arm64
```

修复后 `python`/`node`/`nginx` canonical tag 回到 `linux/arm64`（redis/weaviate/alpine 本就是 arm64），首轮失败的 apt 步骤在第二轮全部通过（document-parser 离线解包 177 个 deb、chat-api playwright 系统库离线安装均正常）。

---

## 三、构建与部署

| 项 | 值 |
| --- | --- |
| 命令 | `MOGO_VERSION=ee65305 COMPOSE_PARALLEL_LIMIT=1 BUILDKIT_STEP_CONCURRENCY=2 ./mogo up --build` |
| 起止 | 2026-10-28T17:36:32+08:00 → 17:58:06+08:00（**21m34s**） |
| 镜像 | 7 张（gateway / admin-api / user-web / admin-web / chat-api / dsh-runtime-host / document-parser，document-worker 共用 document-parser），**全部 `linux/arm64`** |
| 基础镜像 | `reused 3`（本地复用，未走远端），加载后全部 arm64 |
| 离线 bundle | apt / pip / playwright 三套全部命中本地 bundle（`APT_OFFLINE_INSTALL=true`、`PIP_OFFLINE_INSTALL=true`） |
| 退出码 | `EXIT=0` |

镜像体积：chat-api 4.38GB、document-parser 5.24GB、dsh-runtime-host 1.23GB、admin-api 465MB、user-web 46.9MB、admin-web 45.1MB、gateway 30.9MB。

---

## 四、健康与镜像清理

| 项 | 结果 |
| --- | --- |
| 容器 | 12 个运行：11 个 `healthy`；`mogo-document-worker-1` 无 healthcheck（`Up`，历史一致）；`mogo-bootstrap-1` 一次性任务 `Exited (0)` |
| 运行镜像 tag | 全部 `ee65305` |
| 上个版本镜像 | `Pruned 8 image(s) from the previous release, reclaimed about 10469 MB`（`b6055c8` 全 7 张 + `667552a`） |
| 悬空镜像 | `Pruned untagged build leftovers, reclaimed about 19 MB`；`docker images -f dangling=true` → **0** |
| 保留未动 | `ghcr.io/mogoai/*:ee65305`（并行会话的 amd64 生产交付镜像，7 张）与 `ghcr.io/mogoai/*:43b165b`、`gateway:c3a3514`（更早的 amd64 交付 tag）——归属其他会话，未删除 |
| 容器日志 | 8 个应用容器近 6 分钟 `error/critical/traceback` 命中数均为 **0** |

---

## 五、回归测试（ARM 准生产运行态）

| 套件 | 方式 | 结果 | 对照基线（round 11/12） |
| --- | --- | --- | --- |
| admin-api 全量 pytest | 容器内，`--network mogo_backend`，`-m "not dsh_host_e2e"` | **1484 passed, 1 skipped, 0 failed**（57.5s） | 1470 passed → +14（ee65305 新增用例） |
| document-parser 全量 | 容器内 | **28 passed, 0 failed**（11s） | 28 passed，一致 |
| chat-api 全量 | 容器内，`MOGO_TEST=1`，`-m "not dsh_host_e2e and not network"` | **3001 passed, 3 skipped, 27 deselected, 0 failed**（37.4s） | 2985 passed → +16 |
| deploy/tests 守卫 | 宿主 `/tmp/deploy-venv`，`env -u MOGO_TLS` | **266 passed, 13 skipped, 2 failed**（16s） | 275 passed / 3 failed（同类漂移） |
| 网关冒烟 | `http://127.0.0.1:3000` | **5/5 PASS** | 一致 |

网关冒烟明细：

| 路径 | 直接 | 跟随 301 | 说明 |
| --- | --- | --- | --- |
| `/healthz` | 200 | — | 网关健康检查 |
| `/admin/` | 200 | — | admin-web 前端 |
| `/admin-api/api/setup/status` | 301 | **200** → `/admin-api/api/v1/setup/status` | 旧路径平滑迁移 |
| `/askai-api/health` | 200 | — | chat-api 自报 `version 0.2.5`、`backend panweidb`、`reachable true`、`dsh_host healthy` |
| `/api/auth/me` | 301 | **401** → `/api/v1/auth/me` | 跟随后正确拒绝未认证 |

---

## 六、非本轮引入的已知失败（逐项归因）

1. `deploy/tests/test_sso_token_not_in_url.py::test_admin_web_exchanges_token_via_post` —— admin-web 前端 SSO exchange 已改为经 `apiClient` 调用 `/api/v1/...`，断言仍找字面量 `/api/auth/sso/exchange`。属 round 5 已记录的"admin-web 路径迁移"类断言漂移。
2. `deploy/tests/test_tls_gateway_config.py::test_tls_configs_are_semantically_equivalent` —— `deploy/nginx/nginx.conf` 与 `deploy/docker/nginx-https.conf` 漂移（`X-Forwarded-Prefix /admin-api` vs `proxy_read_timeout 600s`）。round 5 已记录的"两份 nginx 配置漂移"。
3. chat-api 的 `tests/dsh_runtime/conversation_regression/test_conversation_capabilities.py` 3 项 `test_real_dsh_*` 在不带 marker 时会失败（`harness.py:60: DSH conversation regression requires Node ^22.19.0 or >=24.0.0`，chat-api 镜像为 Python 运行态、容器内无 Node）。属 vault「容器内跑 services 单测」记录的环境限制，按既有配方 `-m "not dsh_host_e2e and not network"` 排除后 0 failed。

> 另：`https://127.0.0.1/` 各路径返回 404（TLS 握手正常）。443 vhost 本轮未纳入 smoke（round 5 同样未覆盖），网关现行入口为 `:3000`，配置与上一轮构建同源，非本轮引入。

---

## 七、交接 / 待确认

- **基础镜像 canonical tag 现为 arm64**。若并行会话还要在本机导出 amd64 生产镜像，需先 `docker pull --platform linux/amd64` 那 3 个基础镜像（或 `scripts/export_base_images.sh load --allow-platform-mismatch ./base-images/images/amd64`），否则会再次出现 arm64/amd64 混用——本次首轮失败即此。
- 未删除任何其他会话的镜像/文件；仓库无改动（`git status` 仅 3 个未跟踪文件，与本轮无关）。
- 回归脚本与日志：`/tmp/mogo-round14/`（`up-build.log`、`svc-tests.log`、`svc-tests-marked.log`、`deploy-tests.log`、`smoke.log`、`env-*.env`、`run_*.sh`）。
