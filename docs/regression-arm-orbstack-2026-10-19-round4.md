# OrbStack 准生产环境回归 · Round 4（2026-10-19）

> ADR-5 多轮回归第四轮。用户明确指令：用 `MOGO_VERSION=$(git rev-parse --short HEAD)` 执行 `./mogo up --build` 重建并重启服务，并从 OrbStack 清除上个版本镜像。

---

## 一、结论（一句话）

**镜像重建零回归**：`MOGO_VERSION=b05f445 ./mogo up --build` 本地构建 8 个服务镜像（tag `b05f445`）→ 重启全部容器 → 自动 prune 清除旧 `030b017`（残留 0 张）；Tier A 守卫与 Round2/3 完全一致（**196 passed / 7 skipped**），经网关冒烟全绿。

---

## 二、执行关键事实

- **HEAD 短哈希**：`b05f445`（`git describe` 实际为 `v0.2.3-9-gb05f445`；`up --build` 中 `MOGO_VERSION` 显式设为 `b05f445`）。
- **构建链路**：`MOGO_VERSION=b05f445 ./mogo up --build` 走 `docker-compose.yml -f docker-compose.build.yml`，本地 buildx 构建 8 个服务（gateway / admin-api / user-web / admin-web / chat-api / dsh-runtime-host / document-parser，document-worker 共用 document-parser 镜像），`up -d --pull never` 重启，`--build` 成功后再 `prune_previous_release_images`（删非 `b05f445` 的本项目镜像）+ `prune_dangling_images`。
- **沙箱坑（重要）**：首次构建在 workspace-write 沙箱下失败，报 `failed to update builder last activity time: open /Users/cooper/.docker/buildx/activity/.tmp-...: operation not permitted`。根因是 DSH 文件沙箱拦截 docker buildx 写宿主 `~/.docker/buildx/activity/` 时间戳文件。放宽到 danger-full-access 后构建正常。**后续从 DSH 内跑 `./mogo up --build` 需带危险沙箱权限**。
- **未提交改动（其他会话在途，按 ADR-5 不动）**：`apps/user-web/src/App.vue`、`apps/user-web/src/composables/useChatRuntimeStore.ts`、`services/document-parser/docling-models-bundle.tar.gz`。本次仅重建镜像/容器，未触碰、未提交源码。
- **环境基线**：panweidb `db: READY`；11 个 mogo 容器 + 独立 panweidb 全部 Up（重建后 `b05f445` 全 healthy）；`MOGO_DATA_BACKEND=PanWeiDB`、`MOGO_TLS=0`、`MOGO_NGINX_CONF=./deploy/docker/nginx.conf`（与 Round1 决策一致，纯 HTTP，探针 `http://127.0.0.1:3000`）。

---

## 三、Tier A 守卫重跑（验证重建零回归）

调用配方（隔离 venv `/tmp/mogo-round2-venv`，pytest 9.1.1 + pytest-asyncio）：

```bash
COMPOSE_PROFILES=pool MOGO_TLS=1 PYTHONPATH=services/admin-api \
  python -m pytest deploy/tests/ -q -p no:cacheprovider \
  --ignore=deploy/tests/test_performance_us7.py \
  --ignore=deploy/tests/test_ontology_permission_mongo_parity.py
# → 189 passed, 7 skipped

PYTHONPATH=services/chat-api python -m pytest deploy/tests/test_performance_us7.py -q -p no:cacheprovider
# → 7 passed
```

**合计 196 passed / 7 skipped，与 Round 2/3 完全相等** → 镜像滚动重建（gateway 带 D1 resolver 根治、chat-api 版本对齐 0.2.3）未引入任何守卫级回归。

覆盖到的守卫：022 加固、TLS 网关、数据安全 US5、性能 US7、供应链 US6 / GET 无副作用 / SSO token / PG 兼容 parity / supply chain 等，均随主体一并 PASS。

> `MOGO_TLS=1` 仅让 cert-guard 守卫用例进入「TLS 开启」分支断言生成/重启逻辑，不真正改 `.env`、不动运行环境（Round1 已拍板 `MOGO_TLS=0` 维持不变）。测试运行器的 env 与部署 env 是两回事。

---

## 四、经网关冒烟（运行态，重建后）

| 路径 | 结果 | 说明 |
| --- | --- | --- |
| `/healthz` | 200 | 网关健康检查 |
| `/admin/` | 200 | admin-web 前端 |
| `/admin-api/api/setup/status` | 200 | admin-api |
| `/askai-api/health` | 200 | chat-api（自报 `version: 0.2.3`，backend `panweidb`） |
| `/api/auth/me` | 401 | 到达 chat-api 并正确拒绝未认证 |

---

## 五、镜像清理核验

| 项 | 结果 |
| --- | --- |
| 新镜像 `*:b05f445` | 7 张存在（8 服务，document-worker 共用 document-parser） |
| 旧镜像 `*:030b017` | **0 张残留**（被 `prune_previous_release_images` 清除） |
| 容器运行 tag | 全部 `b05f445`，均 `Up (healthy)` |

---

## 六、本轮已闭环项（Done）

- 镜像重建 `b05f445`：8 服务本地构建 + 容器 recreate + 旧 `030b017` 镜像自动清理（0 残留）。
- Tier A 守卫零回归（196 passed / 7 skipped）。
- 经网关冒烟全绿（5/5 路径符合预期）。

---

## 七、遗留待办（Open → 移交 Round 5+）

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 三服务源码级全量测试 | 暂缓 | 等 `services/*/main.py` 等未提交改动提交后再开；用「挂载 `services/<svc>/tests` 进容器 + 装 pytest（只读）」方式 |
| TLS 启用 | 维持 `MOGO_TLS=0` | 仍拍板不动 |
| `.env` 口令与 `panweidb_up.sh` 默认分叉 | 配置卫生 | 脚本硬编码 `APP_PW='1qaz!QAZ'` 已连不上，不阻断 |
| 故障转移 / 压测 | 未排 | Tier C |

Open objectives: 以 OrbStack 为准生产环境执行多轮回归（ADR-5，m00002）。
