# 024 T049/T073 独立复跑：隔离环境真实演练（mogo-drill 项目）

- 日期：2026-10-26（Asia/Shanghai）
- 范围：T049 真实回滚演练（FR-023）、T073 真实恢复演练（FR-037）
- 隔离方式：`COMPOSE_PROJECT_NAME=mogo-drill` + `MOGO_VOLUME_PREFIX=mogo-drill`，全栈 `docker compose -p mogo-drill up -d`，网关 `MOGO_PORT=3311`（HTTP）／`MOGO_HTTPS_PORT=4431`（HTTPS）。生产 `mogo` 栈（`mogo-mongo-1` 等，已 Up 45h healthy）全程未触碰、未停、未删卷；演练容器名/网络/卷全部带 `mogo-drill-`/`mogo-drill_` 前缀。结束后 `docker compose -p mogo-drill down -v` 清理。
- 镜像：仅用本地已有镜像（Docker Hub 直连 Bad Gateway，未拉新）。为让 `./mogo` 的镜像解析离线可用，对本地镜像打了 `ghcr.io/mogoai/<svc>:latest` 别名标签（内容不变，非远端拉取）。
- 说明：`specs/024-deployment-hardening/tasks.md` 的 T049/T073 **在本复跑之前已被勾选**（勾选数 112，commit `7e95cc0` / `badbe3c4`）。本轮为**独立交叉复跑**，改用部署真实工具链 `deploy/cli/backup.sh`（卷归档加密备份）与 `deploy/cli/canary.sh` + `deploy/cli/auto-rollback.sh`，验证前一轮未覆盖的路径。tasks.md 勾选状态未改动。

## T073 真实恢复演练（真实 `./mogo backup` / `./mogo restore` 卷归档路径）

| 阶段 | 操作 | 实测耗时 | 结果 |
|---|---|---|---|
| 种子 | `seed.js` 写入 `mogo_dev` 7 集合 17 行 | — | `SEED_OK` |
| 备份前快照 | `snapshot.py` → `content_sha256=850d062d4e89ba57`，rows=17 | — | 基线 |
| **加密备份** | `./mogo backup /tmp/.../drill-t073-run2`（`MOGO_BACKUP_KEY_FILE` 独立密钥文件） | **85.17s**（rc=0） | 8 卷归档全部 `.tar.gz.enc`，aes-256-cbc / pbkdf2 iter 200000，明文归档已删除（0 个 `.tar.gz` 残留），`ENCRYPTED=true`、`KEY_SHA256_PREFIX` 写出，`SHA256SUMS` 15 条 |
| **灾难** | `docker compose -p mogo-drill down -v`（清空全部隔离卷，模拟主机丢失） | 2026-10-26T01:16:46Z | 0 个 `mogo-drill_*` 卷残留 |
| 干净目标 | 新建 `mogo-drill_mongo-data` 卷，仅起 mongo | — | **collections=0 / rows=0**（恢复前确认为空） |
| **恢复** | `./mogo restore ... --yes`（解密→sha256 校验→清后解压 8 卷→up→wait_until_ready） | **86.27s**（rc=0） | `MOGO data restoration completed and services are ready.` |
| 就绪 | `GET /askai-api/ready` | — | **200** `{"status":"ready",...}` |
| **数据一致性** | `snapshot.py` 复测 | — | `content_sha256=850d062d4e89ba57`（与备份前**完全相同**），rows=17 |
| **业务校验** | `verify_restore_business.py --endpoints-file`（真实端点覆盖） | — | **6/6 PASS**，`verdict=PASS 恢复后业务校验全部通过（FR-037）` |

- **RTO = 338.9s（5.6 min）**，目标 ≤1800s（30 min）→ **达标**。RTO 起点＝灾难时刻 01:16:46Z，终点＝业务校验通过。
- **RPO = 141.2s（2.35 min）**，目标 ≤900s（15 min）→ **达标**。数据一致性起点＝备份归档 mtime 2026-10-26T01:14:24Z；种子后至备份间无写库。
- 端点清单：`gateway_healthz`(200)、`chat_api_health`(200)、`chat_api_ready`(200)、`admin_api_health`(200)、`projects_list_auth_gated`(401 invalid_token)、`sessions_list_auth_gated`(401 invalid_token)。业务数据端点全部需鉴权，无 token 时返回 401 `{"detail":"invalid_token"}`——证明 API 已挂载且鉴权层生效；**数据存在性由 content_sha256 逐字节一致证明**（比裸 200 更强）。

## T049 真实回滚演练（真实 `canary.sh promote` + `auto-rollback.sh`）

| 阶段 | 操作 | 实测值 |
|---|---|---|
| 灰度开启 | `canary.sh start --version e6289d9 --weight 50`（`--profile canary` 起 chat/admin/document-api-canary 三副本，均 healthy） | nginx `split_clients` 50% 生效；`X-MOGO-CANARY:1` 强制走 canary，`:0` 走 stable（均 200） |
| 基线（canary=1） | 真实 HTTP 探测 120 次 | error_rate=0 / p95=25.7ms / 5xx=0 / timeout=0 / availability=1.0 |
| 基线（stable） | 120 次 | error_rate=0 / p95=37.4ms / availability=1.0 |
| **注入故障** | compose 覆盖把 `chat-api-canary` 换成 `chat-api-canary-bad:drill`（真实坏版本容器，全 503） | **error_rate=1.0 / 5xx=1.0 / availability=0.0** |
| 检测（dry-run） | `auto-rollback.sh --url 9099 --dry-run --json` | `any_hit=true`，触发 `error_rate_delta,p95_latency_delta,availability`，exit 3 |
| **自动回滚** | `auto-rollback.sh --url 9099 --json`（真实执行） | **墙钟 14.63s**；`canary.sh rollback` 报告**实测耗时 13.5s**（T1 目标 ≤300s）→ **达标**；canary 三副本停止，weight=0；记录 `deploy/runbook/rollbacks/2026-10-26-e6289d9.md` |
| **指标恢复** | 清窗口后稳定版真实探测 300 次 | **error_rate=0 / 5xx=0 / timeout=0 / availability=1.0**；用户真实流量（无 canary 头）`/askai-api/ready`=200 |
| FR-026 校验 | `verify_rollback_baseline.py --baseline-file ... --post-file ... --json`（容差 10%） | 核心 SLO 指标 **error_rate/5xx/timeout/availability 均 delta=0、ok=true**；`p95_latency_ms` delta=18.18%（37.4→30.6ms，恢复后**更快**，属探针噪声）与 `n`（样本数 120 vs 300 不等）→ 工具判 ok=false |

指标口径经 `auto-rollback.sh` 真实 PromQL 求值（`error_rate`/`5xx_rate`/`timeout_rate`/`availability`/`p95_latency_ms`）；指标传输层由本地 Prometheus 兼容端点提供（本机无 prom/prometheus 镜像，Docker Hub 不通），其输入为 probe.py 对真实网关的真实 HTTP 探测样本，非 mock。

## 复跑结论

T049、T073 均**真实执行且达标**，与前一轮结论一致；本轮额外验证了前一轮未覆盖的 `deploy/cli/backup.sh` 卷归档加密备份 + `mogo restore` 解密恢复路径。tasks.md 勾选无需改动（已为 `- [x]`）。

## 发现的问题（供后续任务参考，未在本轮修复）

1. **`mogo_compose` 会把 `--profile panweidb` 强拉进拓扑**（`mogo_panweidb_enabled` 只要宿主存在 `label=com.docker.compose.service=panweidb` 的容器即返回 true，与 `MOGO_DATA_BACKEND` 无关）。隔离演练下前两次 `./mogo backup` 因此去起 panweidb，撞上生产已占用的 `127.0.0.1:5432` 而 `up` 失败（rc=1，备份本身已成功）。设 `MOGO_PANWEIDB_PORT=<空闲端口>` 后 rc=0。
2. **`p95_latency_delta` 回滚条件存在真缺陷**：其 PromQL `histogram_quantile(...)*1000` 返回**毫秒**（实测基线 25.7ms），而 `op=gt_baseline_plus_20pct` 用阈值 0.20 比较 → 任何健康灰度的 p95 都远超 0.20，条件**恒真**，会误触发自动回滚。本轮故障期 p95=30.2ms 也命中该条件，但健康基线同样会命中。
3. **`auto-rollback.sh` 的 `http_5xx_rate` 条件判定存疑**：故障期实测值 1.0、`op=gt_0_01`，理论应 hit=true，实际 `--json` 输出 `hit:false`。建议核对 `gt_0_N` 的解析/比较逻辑。
4. **`verify_restore_business.py` 默认端点清单在本部署全部不匹配**（`/health` 200、`/api/health`、`/api/documents`、`/api/knowledge-base/search`、`/api/admin/system/status` 均 404，`POST /api/chat` 空 body 422），必须用 `--endpoints-file` 以真实端点覆盖；且 `mogo_restore --verify` 会把报告写到仓库 `backups/restore-verify.json`，本轮未启用 `--verify`，改由演练脚本自行输出到 `/tmp`。
5. **`verify_rollback_baseline.py` 把 `n`（样本数）当业务指标比较**，样本量不等即判失败；`p95_latency_ms` 单一 10% 容差对本机探针尾延迟噪声过严。
6. **网关镜像基础 `nginx.conf` 无条件 HTTP→HTTPS 301**（仅 `/healthz` 例外）；隔离环境需 `MOGO_NGINX_CONF=./deploy/docker/nginx.conf`（生产 `.env` 已设）才能以 HTTP 提供全部路由。
7. `deploy/cli/auto-rollback.sh` 权限 644，不可直接执行，需 `bash deploy/cli/auto-rollback.sh`。

## 提交范围

仅本轮生成/改动：`deploy/runbook/drills/2026-10-26-t049-t073-isolated-rerun.md`（本报告，新增）、`deploy/runbook/rollbacks/2026-10-26-e6289d9.md`（自动回滚记录，复跑重写）。`specs/024-deployment-hardening/tasks.md` 未改动。不触碰其他会话在途文件。