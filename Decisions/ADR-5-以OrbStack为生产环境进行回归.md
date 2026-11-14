# ADR-5：以 OrbStack 为准生产环境进行多轮回归

- **状态**：Accepted（active）
- **日期**：2026-10-18（决策）/ 2026-10-19（落库）
- **决策人**：cooper
- **相关目标**：以 OrbStack 作为准生产（pre-production）回归靶场，按多轮（Round）推进质量门禁

---

## 1. 背景（Context）

`cooper/mogo` 的部署形态是 OrbStack 上的多容器编排（11 个 mogo 容器 + 独立 `panweidb` 容器，镜像 tag 与 git HEAD 对齐）。历史上回归报告（如 `docs/regression-arm-orbstack-2026-10-12.md`）已基于 OrbStack 验证过 TLS 生效版本。

需要一份稳定的、可重复的**准生产回归机制**，覆盖：

- 环境恢复与就绪（DB / 崩溃服务 / 健康链路）
- 路由 / 鉴权 / 版本一致性冒烟
- 韧性 / 故障转移（upstream 重启是否自愈）
- 配置一致性（TLS 方向、镜像版本、compose 校验）
- 与 CI 同款门禁、ARM 架构、022 加固守卫

由于 OrbStack 是本地 ARM 准生产环境，且 `panweidb` 等组件跨会话状态易漂移，**以 OrbStack 为持续回归靶场**比每次临时起环境更可控、可复现。

## 2. 决策（Decision）

1. **以 OrbStack 作为准生产回归靶场**，按多轮（Round N）递进式回归，每轮产出独立报告 `docs/regression-arm-orbstack-YYYY-MM-DD-roundN.md`。
2. **每轮开工纪律**：
   - 先 `git status --porcelain` 记基线；未提交改动默认视为其他会话在途工作，不回滚、不覆盖、不批量暂存（`git add -A` 禁用）。
   - 先确认环境就绪（DB `panweidb_up.sh --status`、容器健康、崩溃循环根因），再采集基线。
   - 正确探针：视 `.env` 的 `MOGO_TLS` 而定——关闭时用 `http://127.0.0.1:3000`（3000→80），开启时用 `https://localhost`（443）。
3. **TLS 基线方向（Round1 拍板）**：当前保持 `MOGO_TLS=0`（非 TLS，443 为死映射端口）。若后续要求 TLS 生效，需 `MOGO_NGINX_CONF=./deploy/nginx/nginx.conf`（或 `nginx-https.conf`）+ 挂载 `MOGO_TLS_CERTS_DIR` 证书 + 复验就绪探针。
4. **镜像重建纪律**：本地镜像模板 `ghcr.io/himovo/<svc>:${MOGO_VERSION:-latest}`；registry 链路已废弃（`denied`），重建须带 `MOGO_VERSION=<tag>` 且 `docker compose up -d --no-deps --pull=never <svc>`，或直接 `MOGO_<SVC>_IMAGE=<local-tag>` 指向本地标签，避免误去远端拉取。
5. **网关配置是 bind mount，改完须重建容器重挂**：`docker compose up -d --force-recreate --no-deps --pull=never gateway`（不用 `restart`——`restart` 不重挂 bind mount，改了宿主文件也不生效）。

## 3. 后果 / 已知约束（Consequences）

- OrbStack 单容器 `read_only: true` + 单文件 bind mount 在 `docker compose up -d`（非 recreate）下表现为「已运行容器直接跳过、不改挂载」——**这不是 OrbStack 缺陷，是常规行为**；改 gateway 配置后必须 `--force-recreate`。
- `panweidb` 是独立容器（不在 mogo compose 内），DB 进程（`gs_ctl`）若不运行，三服务（`admin-api/chat-api/document-api` 在 `MOGO_DATA_BACKEND=PanWeiDB` 下）会 `psycopg_pool.PoolTimeout` 无限重启。开工前先 `bash scripts/pg/panweidb_up.sh --status` 确认 `db: ready`。
- `.env` 的 `PANWEIDB_PASSWORD`（24 字符）与 `scripts/pg/panweidb_up.sh:42` 硬编码 `APP_PW='1qaz!QAZ'` 已分叉（DB 口令后被改过，脚本默认连不上）。属配置卫生，不阻断；后续同步脚本默认密码。

## 4. 关联文档

- 回归报告目录：`docs/regression-arm-orbstack-*.md`
- Round1 报告（含 D1 根治愈证）：`docs/regression-arm-orbstack-2026-10-19-round1.md`
- 网关配置：`deploy/docker/nginx.conf`（当前 `.env` 指向）、`deploy/nginx/nginx.conf`（TLS 默认）、`deploy/docker/nginx-https.conf`（TLS 兼容入口）
- 崩溃恢复脚本：`scripts/pg/panweidb_up.sh`
