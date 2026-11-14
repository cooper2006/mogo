# 主键统一 32-hex：阶段 2 执行手册（停机窗口）

> 状态：**已于 2026-11-11 停机窗口执行完成**（代码提交 `83bd0973`，k3s 镜像 tag 同）。
> 决策（2026-11-10）：做阶段 2；事件流两集合**截断重建**；终态**只认 32-hex**；提供停机窗口。
> 相关资产：`scripts/migrate_ids_to_hex32.py`、`app/core/ids.py`、`app/core/hex32_db.py`、
> `app/core/db.py`（三服务）、`app/core/pg_compat.py`（三服务）。

---

## 1. 问题与目标

Mongo 侧 `_id` 曾是 `ObjectId`（24-hex），PanWeiDB 迁移期 `pg_compat.insert_one`
又用 `uuid4().hex`（32-hex）补过缺失主键，两套形态长期并存。直接后果：
`admin-api` 的 `_safe_oid` 在 mongo 模式用 `ObjectId(value)` 规范化，遇到 32-hex
部门 / 用户 ID 抛 `InvalidId` → `PUT /admin-api/api/v1/directory/users/...` 400。

**终态**：所有系统生成的实体主键与跨集合引用统一为 **32 位十六进制字符串**；
代码守卫只认 32-hex，24-hex / `ObjectId` 一律拒绝。

### 新 ID 形态

```
12-hex 毫秒时间戳 + 20-hex 随机数 = 32-hex
例：0199c1f2a3b4 5e8d0c1f2a3b4c5d6e7f8
```

字典序 ≈ 创建时间序，因此 `_id` 作为高水位游标（`skill_quality_collector_state.last_id`）
与分页游标（`SkillShareMemberDirectory`）的既有语义**不丢失**。存量 ObjectId 迁移时
用其 `generation_time` 作时间戳前缀，顺序不倒退；迁移脚本把 `last_id` 里的 24-hex
引用同步改写为新值，collector 无需重置。

### 例外：业务自然键（不属于实体 ID）

以下集合的 `_id` 是有业务含义的字符串，不强制 32-hex，也不经过 `is_valid_backend_id`
守卫；白名单在迁移脚本 `NATURAL_KEY_COLLECTIONS` 中：

| 形态 | 集合样例 |
|---|---|
| 组织编码 | `org_units`（`"13000"` / `"12300"` …） |
| 项目键 / 单例键 | `projects`（`"web-project-..."`）、`system_bootstrap`（`"singleton"`）、`sys_config`、`skill_quality_collector_state` |
| 复合键 | `knowledge_document_chunks`（`"<doc_id>:raw:raw_000001"`）、`position_roles`（`"system:org-<id>:full_access_admin"`） |
| 其它编码 | `business_entity_index`、`mesc_ontology_perm_audit`、`employees`、`bw_probe*` |

复合键中若含 24-hex 子串（如 chunk 的 `document_id` 前缀、角色键里的组织 ID），
迁移脚本会按**同一张映射表**替换，保证与被引用的实体 `_id` 一致。

---

## 2. 现状基线（2026-11-10 只读扫描，`mogo_dev` @ ServeBay Mongo）

| 指标 | 值 |
|---|---|
| 集合数 / 文档数 | 155 / 140,707 |
| `ObjectId` 主键 / 32-hex 主键 / 自然键 | 103,259 / 37,134 / 314 |
| 事件流两集合 | `kernel_event_inbox` 69,933 + `kernel_event_projections` 66,869 = **136,802（97.2%）** |
| **排除事件流后** | 2,475 ObjectId 主键 + 4 个 24-hex 主键 + 1,116 个 32-hex + 314 自然键 |
| 需改写的引用值 | 7,802 处（22 类字段：`user_id` / `conversation_id` / `session_id` / `provider_id` / `model_instance_id` …） |
| 映射表规模 | 2,731 条 |

事件流截断后，真正要重写的数据只有 **3,905 份文档**，这是窗口可以很短的原因。

---

## 3. 代码终态（已落地）

| 改动 | 说明 |
|---|---|
| `app/core/ids.py` ×3 | `is_valid_backend_id` / `to_backend_id_strict` **只认 32-hex**；`to_backend_id` 只做字符串化（不再转 `ObjectId`）；新增 `new_backend_id()` 生成时间有序 32-hex |
| `app/core/hex32_db.py` ×3（新增） | 在 `get_db()` / `get_audit_db()` 返回句柄外包一层门面，对 `insert_one` / `insert_many` / `replace_one(upsert)` / `update_*(upsert)` / `find_one_and_*(upsert)` / `bulk_write` 统一注入 32-hex `_id`，拦截驱动默认的 `ObjectId`。**不改 150+ 个业务写入调用点** |
| `app/core/db.py` ×3 | mongo 分支接线到上述门面；PanWeiDB 兼容门面仍走自己的 `new_backend_id` |
| `app/core/pg_compat.py` ×3 | `new_backend_id()` 由 `str(ObjectId())` 改为 32-hex |
| 20+ 个直接 `ObjectId(...)` 构造点 | 改为 `to_backend_id_strict` / `is_valid_backend_id` 或直接使用字符串；含 `directory._safe_oid`、`model_group_repository`、`plugin_management`、`session_shares`、`session_access`、`turn_cancellation`、`session_live`、`sessions.py`、`model_router.is_model_config_id` |
| 测试 | `test_ids.py` 重写；新增 `test_hex32_db.py`；33 处测试夹具 24-hex → 32-hex；`test_resilience_wiring._new_id()` 改用 `new_backend_id()` |

**已验证**：

- 定向回归：admin-api 61 项、chat-api 69 项、模型路由 19 项、
  document-parser 5 项，全部通过；
- 全量回归：`admin-api` 与 `chat-api` / `document-parser` 全量套件中，
  与本次改动相关的失败已全部修复；剩余失败均为**既有环境问题**，
  逐项确认与 ID 改动无关：
  - `pymongo ConfigurationError: Empty host`（未设置 `MONGODB_URI`）——
    补上 URI 后对应测试即通过；
  - `DSH Runtime Host did not become healthy` / e2e 超时（需要真实 Runtime Host）；
  - `ModuleNotFoundError: numpy`（document-parser venv 缺 OCR 依赖）；
  - `test_every_tenant_id_keyed_collection_in_the_tree_is_covered` 与
    `test_im_audit_events`（其它会话新增集合 / 审计事件未同步清单）。
- 真实驱动烟测：motor 10 组 / pymongo 3 组写入路径 + `chat-api get_db()` 接线，
  全部生成 32-hex `_id`（`_id` 为 `str` 而非 `ObjectId`）；
- 迁移脚本在**临时库**完整演练：`plan → apply(12s) → verify PASS → rollback 恢复`，
  155 个集合与全部索引零缺失。

---

## 4. 迁移脚本

`scripts/migrate_ids_to_hex32.py`（pymongo / bson，无项目依赖）。

| 子命令 | 作用 |
|---|---|
| `plan` | 只读：全库 BSON 快照 + 索引定义 + 映射表，输出每个集合的改写量与总报告 |
| `apply --confirm-stopped` | 写库：事件流截断重建、其余集合归一；**必须**显式传 `--confirm-stopped` |
| `verify` | 断言：无 `ObjectId` / 24-hex `_id`、无 24-hex 引用残留、事件流为空、自然键集合在白名单内 |
| `rollback --confirm-stopped` | 从库内备份集合一键恢复（索引随原集合一起恢复） |

**安全设计**：

- 每个集合先 `rename` 成 `<name>__hex32_bak_<ts>`（库内备份），再以转换后的文档
  重建同名集合并恢复索引；旧数据全程在库里，不 `delete`。
- 磁盘上另有 BSON 快照 + `manifest.json` + `id_map.json`，独立于库内备份。
- 映射表持久化：`old 24-hex → new 32-hex`；重复执行复用同一映射，幂等。
- 找不到映射的 24-hex 引用用 `sha256` 确定性兜底，不引入随机。
- `verify` 自动在 `apply` 末尾执行；失败则 `rollback`。

**演练结果**（临时库 `mogo_hex32_rehearsal2`，从正式库 BSON 快照完整恢复 155 个
集合后跑全流程，已清理）：

```
[plan]  collections=155, 备份 473 MB, 映射 2,731 条
        ids=2,479, refs=7,802, 事件流丢弃 136,802        （13.1 s）
[apply] 12.0 s，自动 verify：
        {"collections":155, "docs":3905, "objectid_ids":0, "hex24_ids":0,
         "hex32_ids":3591, "natural_key_ids":314,
         "residual_hex24_values":0, "event_docs":0}
[verify] PASS
[索引]  155 个集合逐一比对 manifest，缺失索引 0
[rollback] 155 个集合完整恢复，事件流 69,933 条与 ObjectId 主键均回来
```

---

## 5. 停机窗口

### 窗口设计：预构建 + 短停机

镜像构建与导入**不需要停服**，先在预窗口完成；真正中断业务只是「停服 → 切库 →
部署 → 验收」这一段。建议窗口 **60 分钟**（保守），其中业务不可用约 **15 分钟**。

| 时刻 | 动作 | 耗时依据 | 业务状态 |
|---|---|---|---|
| **T−40 ~ T−10** | 预窗口：离线重建 7 个业务镜像（`BUILDX_BUILDER=kiri-bk2 MOGO_BASE_IMAGE_POLICY=local ...`），导出并导入 k3s containerd；更新 `deploy/k8s/generated/06-deployments.yaml` 的 tag（**先不 apply**） | 演练外，按历史构建经验 20–30 min | ✅ 在线 |
| **T−10** | 通知使用方；确认无长任务 / 上传 / 解析在跑；记录当前 tag 以便回退 | 5 min | ✅ 在线 |
| **T0** | **停机开始**：`kubectl scale deployment --replicas=0` 业务 8 个 Deployment（gateway / admin-api / chat-api / document-api / document-worker / dsh-runtime-host / user-web / admin-web），保留 redis / weaviate / ServeBay Mongo | 1 min | ⛔ 停服 |
| **T0+1** | `plan`：全库备份 + 映射表，审阅 `plan.json` | 13 s（实测） | ⛔ |
| **T0+2** | `apply --confirm-stopped`：截断事件流 + 归一 + 索引重建 + 自动 `verify` | 12 s（实测） | ⛔ |
| **T0+3** | 部署新镜像：`kubectl apply -f 06-deployments.yaml`，`rollout status`；恢复 replicas | 3–5 min | ⛔ |
| **T0+8** | 冒烟验收（见 §6） | 5 min | ⛔ |
| **T0+15** | **窗口结束**，恢复流量；观察 30 min | — | ✅ 在线 |
| **T+1d** | 确认无异常后清理库内备份集合与磁盘快照（或保留 7 天） | — | ✅ |

数据库**不可写**区间：T0 → T0+15；其中真正改库只有 ~25 秒。

### 前置条件

1. 代码改动已合入并构建成新镜像（**必须先部署新代码，再启动服务**；旧代码会继续
   写入 `ObjectId`，也会用 `ObjectId.is_valid` 守卫误杀 32-hex）。
2. `MOGO_MONGODB_URI=mongodb://host.docker.internal:27017` 在 k3s Secret 中生效
   （当前配置，指向 ServeBay Mongo）；脚本在 Mac 侧用 `mongodb://127.0.0.1:27017`
   连的是**同一个库**。
3. 磁盘余量 ≥ 1 GB（BSON 快照约 473 MB）。
4. 网卡 / `mogo-gateway-relay` 正常，窗口后 host 3000 可访问。

### 命令清单

```bash
cd /Users/cooper/mogo

# ── 预窗口（服务在线）────────────────────────────────────────────
# 1) 构建 7 个业务镜像（离线），并导入 k3s；记录新 tag
BUILDX_BUILDER=kiri-bk2 MOGO_BASE_IMAGE_POLICY=local MOGO_DATA_BACKEND=mongo \
  APT_OFFLINE_INSTALL=true PIP_OFFLINE_INSTALL=true ./mogo build <service>
# 2) 备份当前部署清单，供回退
cp deploy/k8s/generated/06-deployments.yaml /tmp/06-deployments.before-hex32.yaml

# ── T0 停机 ──────────────────────────────────────────────────────
K='docker --context kiri exec kiri-k8s kubectl -n mogo'
for d in gateway admin-api chat-api document-api document-worker \
         dsh-runtime-host user-web admin-web; do
  $K scale deployment/$d --replicas=0
done
$K get pods -n mogo          # 确认业务 Pod 已全部消失

# ── T0+1 备份与计划 ──────────────────────────────────────────────
OUT=backups/id-hex32-$(date -u +%Y%m%dT%H%M%SZ)
python3 scripts/migrate_ids_to_hex32.py --db mogo_dev --out "$OUT" plan
cat "$OUT/plan.json" | head -40

# ── T0+2 执行（务必确认服务已停）──────────────────────────────────
python3 scripts/migrate_ids_to_hex32.py --db mogo_dev --out "$OUT" \
  --confirm-stopped apply          # 末尾自动 verify
python3 scripts/migrate_ids_to_hex32.py --db mogo_dev --out "$OUT" verify

# ── T0+3 部署新代码 ──────────────────────────────────────────────
# 把 06-deployments.yaml 的 image tag 换成新 tag 后：
$K apply -f deploy/k8s/generated/06-deployments.yaml
for d in gateway admin-api chat-api document-api document-worker \
         dsh-runtime-host user-web admin-web; do
  $K rollout status deployment/$d --timeout=180s
done

# ── 回滚（任何一步失败）──────────────────────────────────────────
python3 scripts/migrate_ids_to_hex32.py --db mogo_dev --out "$OUT" \
  --confirm-stopped rollback
$K apply -f /tmp/06-deployments.before-hex32.yaml   # 代码镜像一起回退
```

> **回滚必须代码与数据一起回退**：新库全是 32-hex，旧代码的
> `is_valid_backend_id`（mongo 模式只认 24-hex）会误杀全部新建记录。

### 窗口后清理（建议观察 1 天再执行）

```bash
# 库内备份集合（manifest.json 里的 backup_suffix）
python3 - <<'PY'
import json, sys
from pathlib import Path
from pymongo import MongoClient
out = Path(sys.argv[1])
suffix = json.loads((out / "manifest.json").read_text())["backup_suffix"]
db = MongoClient("mongodb://127.0.0.1:27017")["mogo_dev"]
names = [n for n in db.list_collection_names() if n.endswith(suffix)]
for n in names:
    db.drop_collection(n)
print("dropped", len(names), "backup collections")
PY
```

---

## 6. 验收清单

**数据层**

- [ ] `verify` PASS：0 个 `ObjectId` / 24-hex `_id`，0 个 24-hex 引用残留；
- [ ] `kernel_event_inbox` / `kernel_event_projections` 文档数为 0，索引已恢复；
- [ ] 每个集合的索引数量与 `manifest.json` 一致（含唯一索引 / TTL / partial）；
- [ ] 抽查 `end_users` / `org_units` / `chat_sessions` 的 `_id` 均为 32-hex 字符串；
- [ ] 抽查引用完整性：`chat_sessions.user_id` 能在 `end_users._id` 中找到；
  `knowledge_document_chunks._id` 前缀等于其 `document_id`；
- [ ] 新写入一条记录，`_id` 是 32-hex（验证 `hex32_db` 门面生效）。

**服务层**

- [ ] 8 个业务 Deployment 全部 `Running` / `Ready`；
- [ ] `http://localhost:3000/admin/setup` 返回 200；各服务 `/health` 正常；
- [ ] **原 400 消失**：编辑用户并保存 32-hex 部门 ID 的 `PUT /directory/users/{id}` 返回 200；
- [ ] 登录 → 新建会话 → 发一条消息 → 文档上传解析，链路可通；
- [ ] 触发一次事件写入后，事件流两集合新文档的 `_id` 是 32-hex（验证 bulk_write 注入）；
- [ ] 观察 30 分钟无 `illegal id` / `InvalidId` / `is_valid_backend_id` 相关 5xx。

---

## 7. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 服务未在停机窗口停干净，旧代码写回 `ObjectId` | `apply` 前 `kubectl get pods` 确认；窗口内先 scale 0 再操作；`verify` 会立刻发现残留 |
| 事件流截断丢失历史 kernel 事件 | 决策已确认截断；原集合 rename 成库内备份 + 磁盘 BSON 快照，可按需恢复 |
| 复合键 / 引用级联遗漏 | 不按字段名枚举：对**所有**字段值中的 24-hex 子串按同一映射表替换；`verify` 断言零残留 |
| `_id` 时间有序性丢失 | 新 ID 用 12-hex 毫秒前缀；存量用 `ObjectId.generation_time` 作前缀，游标语义保留 |
| 唯一索引在重建时冲突 | 采用「整集合 rename → 新集合插入」，不与旧文档共存 |
| 旧文档 24-hex 约定误导 | 本文为唯一现行约定；`docs/mongo-to-panweidb-migration-plan.md` 顶部已加废弃注记 |
| 前端 / 浏览器缓存的旧 24-hex ID | 窗口后前端需刷新并重新登录；会话、事件流本就重置 |

---

## 8. 执行记录（2026-11-11，UTC+8）

代码改动已提交并推送到 `mogo/main`（`83bd0973 refactor(ids): 统一实体 ID 为 32-hex 字符串（阶段 2）`）。

| 时刻 | 动作 | 结果 |
|---|---|---|
| 08:50–08:58 | 预窗口：离线串行构建 7 个业务镜像 `83bd0973`，export → scp → 导入 k3s containerd | 7m49s，7/7 成功；服务仍在线（旧 tag `e5a5f447`） |
| 09:02 | T0：8 个业务 Deployment scale 0 | 16s 内业务 Pod 全部退出，仅剩 redis / weaviate |
| 09:02 | `plan` | 155 集合 / 140,707 文档；映射 2,731、ids 2,479、refs 7,802、事件流丢弃 136,802、兜底 0；备份 473 MB |
| 09:02 | `apply --confirm-stopped` + 独立 `verify` | 12.24s；双 PASS：`objectid_ids=0, hex24_ids=0, hex32_ids=3591, natural_key_ids=314, residual_hex24_values=0, event_docs=0` |
| 09:04 | `kubectl apply` 新清单（临时清单把 `mongo.replicas` 保持 0） | 8 个 rollout 23s 全部成功，全部切到 `83bd0973` |
| 09:05–09:12 | 验收 | 见下 |

**数据层验收**：155 个集合索引与 `manifest.json` 逐一比对，缺失 0；`end_users` / `chat_sessions` / `admin_accounts` / `admin_model_instances` 抽查全为 32-hex 字符串（`org_units` 中 9 个为白名单自然键）；事件流两集合 0 文档且索引已恢复；`chat_sessions.user_id → end_users._id` 的 8 个未命中在迁移前后完全一致（24-hex → 32-hex 对应），属既有数据状态。

**代码/服务层验收**：新镜像内 `is_valid_backend_id(32hex)=True` / `(24hex)=False`、`to_backend_id_strict(24hex)` 抛 `ValueError`、`new_backend_id()` 输出 32-hex；`_validate_departments()` 对真实 32-hex 部门 ID 不再抛 400（原 400 根因消除）；`get_db()` 门面在 `insert_one` / `insert_many` / `bulk_write` / `update_one(upsert)` 四条路径全部注入 32-hex（6/6 文档）；真实登录失败请求触发 `admin_login_challenges` / `admin_sessions` 新文档，均为 32-hex；8 个 Deployment 全 Ready；`localhost:3000/admin/setup` 与 `/admin-api/health` 均 200；近 3 分钟 admin-api / chat-api / document-api 日志无 `InvalidId` / `illegal id` / Traceback / 5xx。

**窗口期插曲**：`mogo-gateway-relay` 容器在部署期间消失（不是退出，是容器被删），host 3000 一度 502。按 `deploy/k8s/relay/nginx-stream.conf` 重建（create → cp 配置 → start，接入 `mogo-build-net`）后恢复 200。与 ID 迁移无关。kiri 上 5 个 dev 容器（`mogo-chat-api-1` / `admin-api-1` / `user-web-1` / `mongo-1` / `redis-1`）已 `docker stop`（未删，可恢复）；它们连独立 `mongo:27017`，不是本次迁移的库。

**备份与回滚（观察 1 天后再清理）**：

```
备份目录   backups/id-hex32-20261111T0102Z/   （473 MB，BSON 快照 + manifest + id_map）
库内备份   155 个集合，后缀 __hex32_bak_20261111T010214Z
旧清单     /tmp/06-deployments.before-hex32.yaml   （tag e5a5f447）
数据回滚   python3 scripts/migrate_ids_to_hex32.py --db mogo_dev \
             --out backups/id-hex32-20261111T0102Z --confirm-stopped rollback
镜像回滚   kubectl apply -f /tmp/06-deployments.before-hex32.yaml（代码与数据必须一起回退）
```

**仍需人工/业务触发的验收项**：浏览器真实登录态下「编辑用户并保存」的完整 PUT 200；登录 → 新建会话 → 发消息 → 文档上传全链路；事件流新文档 `_id`（当前两集合仍为 0，未产生业务事件，`bulk_write` 注入已在真实镜像烟测通过）；恢复流量后 30 分钟观察。

> 注：`deploy/k8s/generated/06-deployments.yaml` 镜像 tag 已改为 `83bd0973`，但仓库清单里 `mongo.replicas` 仍为 1；本次 apply 用的是临时清单把它压到 0，后续若要直接 apply 仓库清单，需先把 mongo 副本数改为 0。
