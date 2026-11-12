# 远端 PanWeiDB 主键统一 32-hex：执行手册（待停机窗口）

> 状态：**已于 2026-11-12 08:53–08:58 CST 停机窗口执行完成**
> （`apply --schema public` → 代码回到终态 → 服务重启 → 验收通过）。详见 §9 执行记录。
> 历史状态：脚本先完成全流程演练（见 §5），当时尚未对 `public` 执行 `apply`。
> 适用环境：远端离线部署 `ssh://bonc@172.17.5.96:22`，数据后端
> `MOGO_DATA_BACKEND=panweidb`，`PANWEIDB_HOST=172.17.5.145:17700`，`dbname=mogo`，`schema=public`。
> 脚本：`scripts/pg/migrate_ids_to_hex32_panweidb.py`（依赖 `psycopg[binary]` 3.x，
> 用 `services/admin-api/.venv/bin/python` 运行）。
> 上游参考：`docs/id-unification-hex32-runbook.md`（Mongo 版）、
> `docs/mongo-vs-panweidb-data-diff-2026-11-11.md`。

---

## 1. 为什么要做

阶段 2（`83bd0973`，2026-11-11 08:43）把代码终态收敛为「实体主键只认 32-hex」，
配套停机迁移当日 09:02 **只覆盖了本地 k3s + ServeBay Mongo `mogo_dev`**。
11-11 晚的离线 amd64 部署把该代码推上远端，但远端 PanWeiDB 仍是 24-hex 遗留主键快照，
于是浏览器编辑用户时 `PUT /admin-api/api/v1/directory/users/{id}` 返回 400「用户ID无效」。

当前以 `services/admin-api/app/api/routes/directory.py` 的
`_legacy_hex24_allowed()` 做**临时止血**（仅 `panweidb` 后端放行 24-hex）。
本手册执行完成后必须删除该兼容分支，让代码回到终态。

## 2. 现状基线（2026-11-12 只读扫描，`public`）

| 指标 | 值 |
|---|---|
| `public` 表 / 含 `id+doc` 的表 | 192 / 156 |
| 总行数 | 96,044 |
| 24-hex 主键 / 32-hex 主键 / 自然键 | 64,054 / 31,951 / 39 |
| `doc` 内含 24-hex 字符串值的行 | 95,700 |
| `doc->_id` 与列 `id` 不一致 | **0** |
| 非事件流表行数 / 24-hex 主键 | 1,742 / 1,170 |
| 事件流两表行数 | `kernel_event_inbox` 48,137 + `kernel_event_projections` 46,165 = **94,302** |
| 24-hex → 32-hex 映射条目 | 1,243 |

事件流占 98% 的 24-hex 主键；按阶段 2 已确认的决策**截断重建**
（mongo 侧这两表现状就是 0），真正需逐行改写的只有 1,742 行。

## 3. 与 Mongo 版脚本的差异（不能直接复用）

`scripts/migrate_ids_to_hex32.py` 是 pymongo/BSON 专用（`--uri mongodb://… --db mogo_dev`），
无法操作 PanWeiDB。PanWeiDB 侧额外复杂度：

1. 表结构 `(id TEXT PRIMARY KEY, tenant_id, doc JSONB NOT NULL, created_at, updated_at)`，
   `doc` 内另存 `_id` 原值 → 列与 JSONB 必须同时改写；
2. **81 张表有 R3 扁平化映射列**（`user_id` / `session_id` / `owner_user_id` /
   `created_by` / `parent_id` / `provider_id` …）与 doc 双写，必须按同一映射表同步改写；
3. 复合键（`"<doc_id>:raw:raw_000001"`、角色键）含 24-hex 子串，用带前后 hex 边界的正则
   `(?<![0-9a-fA-F])[0-9a-fA-F]{24}(?![0-9a-fA-F])` 做子串替换，**不会误伤 32-hex**；
4. 业务自然键（`org_units` 的 `13000`、`projects` 的 `default` /
   `web-project-…`、`system_bootstrap` 的 `singleton`、`sys_config`、
   `end_user_org_relations` 的 `rel-*-001`）不含 24-hex 子串，天然不参与转换；
5. 备份/回滚改为表级 `CREATE TABLE … AS SELECT` + 原地 `UPDATE`，全过程单事务。

### 新 ID 生成规则（确定性、时间有序）

```
前 12 位 = ObjectId 前 4 字节（Unix 秒）× 1000 的 48-bit 毫秒时间戳
后 20 位 = sha256("mogo-hex32-v1:" + lowercase(old24hex))[:20]
```

保留 `_id` 作为高水位 / 分页游标的字典序语义；同一输入永远得到同一输出，
中断后重跑幂等，无需随机数。

## 4. 脚本子命令与安全设计

| 子命令 | 作用 |
|---|---|
| `plan` | **只读事务**：全库收集 24-hex 值、生成 `plan.json` / `id_map.json`；不写库 |
| `apply --confirm-stopped` | 库内备份 → 改写 `id` / `doc` / 扁平化列 → 截断事件流 → **自动 `verify`**；单事务，失败全回滚 |
| `verify` | 断言零 24-hex 主键 / 零 doc 与列内 24-hex 引用 / 事件流为空 / 行数与自然键数与 plan 一致 |
| `rollback --confirm-stopped` | 从 `manifest.json` 记录的库内备份表整表恢复（备份表保留） |

- `apply` / `rollback` **必须**显式传 `--confirm-stopped`；
- `plan` 里记录 `schema`，`apply` 会校验一致，**拒绝跨 schema 执行**；
- 备份表命名 `h32bak_<序号>_<UTC时间戳>`，规避 PG 63 字节标识符上限，
  且被 `discover_tables` 排除，不会被误当成业务表；
- 连接串默认读仓库根 `.env` 的 `PANWEIDB_*`，可用 `--dsn` 覆盖。

## 5. 演练记录（2026-11-12，已完成，未碰 `public`）

```bash
PY=services/admin-api/.venv/bin/python
SC=scripts/pg/migrate_ids_to_hex32_panweidb.py

# 只读 plan（生产 public）
$PY $SC --schema public --out backups/hex32-pw-plan plan
#   tables=156  non_event_rows=1742  hex24_ids=1170  mapping=1243  event_rows=94302

# 独立 schema 副本（CREATE SCHEMA hex32_rehearsal + 156 张 CTAS，96,044 行）
# 演练全流程
$PY $SC --schema hex32_rehearsal --out backups/hex32-pw-rehearsal plan
$PY $SC --schema hex32_rehearsal --out backups/hex32-pw-rehearsal --confirm-stopped apply
$PY $SC --schema hex32_rehearsal --out backups/hex32-pw-rehearsal verify
$PY $SC --schema hex32_rehearsal --out backups/hex32-pw-rehearsal --confirm-stopped rollback
```

**演练结果**

```
[apply] 库内备份完成：156 张
[apply] 改写 rows=1556 hex24_ids=1170
[apply] 事件流已截断：kernel_event_inbox, kernel_event_projections
[verify] PASS checked_rows=1742 tables=154
[rollback] 已从库内备份恢复 156 张表
```

提交后独立抽查：

| 检查项 | 结果 |
|---|---|
| `end_users` 全 32-hex（9 行） | True |
| `end_users.doc._id == id` | True |
| `chat_sessions.user_id` 旧值按映射表 == 新值 | True |
| `chat_sessions.user_id` 命中 `end_users.id` | 43/43 |
| `end_user_org_relations` doc 与扁平化列一致（13 行） | True |
| 事件流两表行数 | 0 / 0 |
| 自然键 `13000` / `12100` / `default` | 保留 |
| rollback 后 `hex32_rehearsal` vs `public` | `96044 / 64054` 完全一致 |

## 6. 停机窗口（正式执行，**当前未执行**）

### 前置条件

1. 通知使用方、确认无长任务 / 上传 / 解析在跑；
2. 记录当前 7 个应用镜像 `.Id` 与 `deploy/k8s`/compose 清单，供回退；
3. 磁盘余量充足（库内备份会再复制一份 96,044 行）；
4. 本地 `.env` 目前是 **dev 口径**（`mongo` / `linux/arm64` / `60e8e90d`），
   远端 compose 调用必须用环境变量覆盖，**不要直接改 `.env`**；
5. 基础镜像干净名当前为 arm64；重建 amd64 镜像前需先切 amd64，完成后切回。

### T0 停机

```bash
# 远端 8 个业务服务停写（保留 redis / weaviate）
docker -c mogo-remote compose -f docker-compose.yml \
  -f docker-compose.prod-external-panweidb.yml stop \
  gateway admin-api chat-api document-api document-worker \
  dsh-runtime-host user-web admin-web
docker -c mogo-remote compose -f docker-compose.yml \
  -f docker-compose.prod-external-panweidb.yml ps   # 确认已停
```

> 注意：远端是 docker compose 单机部署，不是 k3s；不要照搬 Mongo 版 runbook 的 `kubectl scale`。

### T0+1 备份与计划

```bash
PY=services/admin-api/.venv/bin/python
SC=scripts/pg/migrate_ids_to_hex32_panweidb.py
OUT=backups/hex32-pw-$(date -u +%Y%m%dT%H%M%SZ)

$PY $SC --schema public --out "$OUT" plan
cat "$OUT/plan.json" | head -40      # 审阅映射与统计
```

### T0+2 执行

```bash
$PY $SC --schema public --out "$OUT" --confirm-stopped apply   # 末尾自动 verify
$PY $SC --schema public --out "$OUT" verify
```

### T0+3 让代码回到终态（**关键**）

1. 删除 `services/admin-api/app/api/routes/directory.py` 中的
   `_legacy_hex24_allowed()` / `_is_acceptable_entity_id()`，
   `_safe_oid` 恢复为无条件拒绝 24-hex，`list_users` 的过滤改回 `is_valid_backend_id(uid)`；
2. 重建并推送 admin-api amd64 镜像（参考 11-11 的做法：
   `switch-base-image-arch.sh amd64` →
   `DOCKER_BUILDKIT=1 DOCKER_DEFAULT_PLATFORM=linux/amd64 docker -c kiri build …` →
   `docker -c kiri save … | docker -c mogo-remote load`），收尾切回 arm64；
3. 用与 11-11 相同的 10 个 `export` 生产变量 + `--force-recreate --no-deps` 重启 admin-api，
   或跑完整 `deploy/production/deploy-remote-push.sh --force-push --check`
   （注意大镜像层摘要指纹会假告警，以 `.Id` + `verify_running_images` + healthy 为准）。

> **回滚必须代码与数据一起回退**：新库全是 32-hex，旧代码 / 未迁移数据会互相误杀。

### T0+4 启动与验收

```bash
docker -c mogo-remote compose -f docker-compose.yml \
  -f docker-compose.prod-external-panweidb.yml up -d
```

**数据层**

- [ ] `verify` PASS：0 个 24-hex 主键、0 个 24-hex 引用残留、事件流两表为 0；
- [ ] 抽查 `end_users` / `chat_sessions` / `org_units` 的 `id` 形态与 `doc._id` 一致；
- [ ] 抽查引用完整性：`chat_sessions.user_id` 能在 `end_users.id` 命中；
- [ ] 新写入一条记录，`_id` 是 32-hex（`hex32_db` / `pg_compat` 门面生效）；
- [ ] 自然键 `13000` / `default` / `singleton` 未被改动。

**服务层**

- [ ] 远端 11 个容器全部 healthy；
- [ ] **浏览器真实登录态**：编辑用户并保存，`PUT /admin-api/api/v1/directory/users/{id}` 返回 200，
      自定义字段 `GET/PUT .../custom-fields` 返回 200（即 11-11 的三个 400 消失）；
- [ ] 登录 → 新建会话 → 发消息 → 文档上传解析链路可通；
- [ ] 观察 30 分钟无 `InvalidId` / `illegal id` / `用户ID无效` / 5xx。

### 回滚（任一步失败）

```bash
$PY $SC --schema public --out "$OUT" --confirm-stopped rollback
# 并把代码镜像回退到迁移前记录的版本（连同 24-hex 兼容补丁一起）
```

## 7. 窗口后清理（观察 1 天）

`manifest.json` 里记录了本轮所有 `h32bak_*` 备份表。确认无异常后清理：

```sql
-- 先列出，人工确认再删
SELECT table_name FROM information_schema.tables
WHERE table_schema='public' AND table_name LIKE 'h32bak_%';
-- DROP TABLE public."<name>"; 逐张执行
```

磁盘侧的 `plan.json` / `id_map.json` / `manifest.json` 建议至少保留 7 天。

## 8. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 服务未停干净，旧代码继续写 24-hex | T0 后 `compose ps` 确认业务容器已停；`verify` 会立即发现残留 |
| 事件流 94,302 行历史日志被截断 | 阶段 2 已决策截断；`apply` 前已建库内备份表 + 磁盘 plan/manifest，可按需恢复 |
| R3 扁平化列漏改导致 doc 与列错位 | 所有列（含 JSONB）走同一 `Mapper.transform`；演练已验证 doc/列一致 |
| 复合键 / 跨表引用遗漏 | 带边界正则做全字段子串替换，映射表覆盖全库 24-hex 值；演练已验证 43/43 引用命中 |
| 32-hex 被误当成 24-hex 前缀 | 正则带前后 hex 边界；演练后 `hex32_ids` 数量保持 |
| 主键更新冲突 | 新 ID 确定性且唯一；全过程单事务，冲突即整体回滚 |
| 标识符超长 | 备份表用序号命名，不拼原表名 |
| 浏览器 / 缓存里残留旧 24-hex ID | 窗口后要求刷新并重新登录 |

---

## 9. 正式执行记录（2026-11-12，UTC+8）

窗口 **08:53:10 → 08:57:39**（约 4.5 分钟），按「停服 → plan → apply+verify → 收尾代码镜像 → 启动 → 验收」顺序执行。
回退基线已记录：7 个应用镜像 `.Id`（admin-api 当时为兼容补丁版 `5885d130e13c…`）、
11 个容器 healthy、本地 dev 口径、基础镜像 arm64。

| 时刻 | 动作 | 结果 |
|---|---|---|
| 08:53 | `compose stop` 8 个业务服务 | 全部 Stopped；仅剩 redis / weaviate / 独立 mongo / admin-api-compat |
| 08:54 | `plan --schema public --out backups/hex32-pw-apply-20261112` | 156 表 / 1,742 行 / 1,170 个 24-hex / 事件流 94,302 / 映射 1,243 |
| 08:54 | `apply --schema public --confirm-stopped` | 备份 156 张、改写 `rows=1556 hex24_ids=1170`、事件流截断、自动 `verify PASS` |
| 08:54 | 独立 `verify` | `PASS checked_rows=1742 tables=154` |
| 08:55–08:56 | 删除 `directory.py` 兼容补丁（`git diff` 归零 = 回到 HEAD 终态）；构建终态 admin-api 镜像 | 新 ID `d231e19afd1a1882…`，amd64；镜像内 `has_compat_helper=False`、24-hex → 400 |
| 08:56 | `save \| load` 推送 | 本地/远端 `.Id` 一致 |
| 08:57 | `up -d --force-recreate --no-deps` 8 个服务 | 全部 Started，admin-api 绑定 `d231e19afd1a1882…` |

**数据层验收**

- 全库 `rows=1742 24hex=0 32hex=1703 其它=39`（自然键）；
- `end_users` 全 32-hex、`doc._id == id`；`chat_sessions.user_id` 43/43 命中用户表且全 32-hex；
- 事件流两表 0 / 0；`13000` / `12100` / `default` 保留；
- 库内备份表 `h32bak_*` 共 156 张，**按 §7 观察 1 天后再清理**。

**服务层验收**

- 11 个容器全部 healthy；网关 `GET /admin-api/health` → `HTTP/1.1 200 OK`；
- 远端容器内实测 `backend=panweidb`、`compat_helper=False`、
  `new_backend_id()` 为合法 32-hex 且 `safe_oid(32hex)` 通过、`safe_oid(24hex)` → 400；
- 用库中真实用户 ID `01a1a5626720b8cf67e171fd4df796c8` 过守卫成功；
- 启动日志只有既有的两条 `opentelemetry.instrumentation` 缺失告警，无 400 / 5xx / 业务 Traceback。

**仍需人工触发**：浏览器真实登录态下「编辑用户并保存 PUT 200」与
「登录 → 新建会话 → 发消息 → 文档上传」全链路（本轮无登录态，未代跑）。
容器重建过，如提示登录失效请重新登录。

### 回滚路径（代码与数据必须一起回退）

远端 `ghcr.io/mogoai/admin-api:latest` 当前指向 `c8c0e5fd…`
（ID 归一终态 `d231e19afd…` + 09:10 追加的 topic-admission `$unwind` 修复）；
兼容补丁版 `5885d130e13c…` 仍以 dangling 镜像存在于**远端 daemon**（本地 kiri 已无）。
若只需回退 topic 修复而**保留数据迁移结果**，把 `d231e19afd…` 重新 tag 为 `:latest` 并重启 admin-api 即可；
下面的完整回滚路径（数据回到 24-hex）才必须用 `5885d130e13c…`。

```bash
# 1) 数据回到 24-hex
services/admin-api/.venv/bin/python scripts/pg/migrate_ids_to_hex32_panweidb.py \
  --schema public --out backups/hex32-pw-apply-20261112 --confirm-stopped rollback

# 2) 代码回到兼容补丁版（在远端把旧镜像重新打 tag）
docker -c mogo-remote image tag sha256:5885d130e13c831a37c0e9c4dfe1a1b5fbcc3c1da4dfdb4205290bc26ae691df \
  ghcr.io/mogoai/admin-api:latest

# 3) 重启 admin-api（用本文 §6 的 10 个 export 生产变量）
docker -c mogo-remote compose -f docker-compose.yml \
  -f docker-compose.prod-external-panweidb.yml up -d --force-recreate --no-deps admin-api

# 4) 本地 services/admin-api/app/api/routes/directory.py 也需重新加回兼容补丁
#    （11-11 的 +23/-3 改动，见 .workbuddy-ai/memory/2026-11-11.md）
```

> 若 `5885d130e13c…` 已被 prune，改为按 11-11 记录重新应用补丁、重建并推送镜像。

### 收尾状态

- 本地基础镜像 6/6 切回 arm64、docker context `kiri`、`.env` 保持 dev 口径；
- `services/admin-api/app/api/routes/directory.py` **`git diff` 为空**（= HEAD 终态），
  临时止血分支已彻底删除；
- 本轮脚本 / runbook / 11-11 的其它改动均**未提交**。
