# OrbStack 准生产环境回归 · Round 6（2026-10-20）

> ADR-5 多轮回归第六轮。基线为 Round 5（`.round5/round5-report.md`：admin-api 1005 / chat-api 2590 / document-parser 26，全 0 失败）。
> 本轮形态与前几轮不同：**先跑四臂并行回归 → 发现 P0/P1/P2 缺陷 → 用户决策修复 → 重建部署 → 运行态验证 → Round 7 复跑确认稳定**。
> 产出提交：`c5b3624 fix(db): 修复 PanWeiDB 下新注册用户无法登录，并修正 storage 健康项`。

---

## 一、结论（一句话）

**发现并修复 1 个 P0 + 2 个 P1/P2 缺陷，回归套件全绿**：

- **P0** PanWeiDB 下新注册用户**完全无法登录**（401 `invalid_session_user`）—— 根因是 `pg_compat` 用 `uuid4().hex` 生成 32 位主键，而 `is_valid_backend_id` 只认 24 位 `ObjectId`，守卫把全部新建记录误杀。已按迁移计划 §2.9/§4 契约改回 `str(ObjectId())`（24 位），并让 `ids.py` 在 panwei 模式下兼容存量 32 位。
- **P1** 门户 SSO 按 `user_id` 解析用户必然 miss（`auth.py` 裸用 `ObjectId(user_id)`）—— 已改为 `to_backend_id`。
- **P2** `setup/status` 的 storage 健康项恒失败（三个可写卷属主 root:root）—— 已在 compose 的 bootstrap 容器加幂等 `chown` 兜底。

修复后：`MOGO_VERSION=c5b3624 ./mogo up --build` 重建 8 个镜像并重启，**11 个容器全部 healthy**；新注册用户注册→登录→建会话→列会话→追加消息全链路 **200 通过**；Round 7 复跑 deploy 守卫 **196 passed / 7 skipped**、三服务 **3624 passed / 0 failed**，与 Round 5 基线完全一致。

---

## 二、本轮四臂分工与实际交付

| 臂 | 范围 | 交付 | 备注 |
| --- | --- | --- | --- |
| **A** | deploy/tests 守卫层 + CI 门禁脚本 + 变异测试 | ✅ `/tmp/armA-report.md`（11.2KB） | 纯只读，未改文件；196 passed / 7 skipped；2 条 CI 门禁脚本 exit 1，定性为 pre-existing |
| **B** | 三服务源码级全量 pytest | ⚠️ 部分交付（subagent 中途失败） | chat-api / document-parser 产物在，admin-api 由主会话补跑 |
| **C** | 运行态 API 探针 | ✅ 由主会话接管 | **本轮 P0/P1/P2 的全部来源** |
| **D** | 前端回归 | ⚠️ 部分交付（subagent 中途失败） | 由主会话补跑 user-web 契约测试 + admin-web typecheck |
| **E** | 依赖安全审计 + 静态检查 | ⚠️ 部分交付（subagent 中途失败） | 由主会话补跑 pip-audit + pyflakes |

> **过程教训**：Arm B/D/E 三个 subagent 在完成前异常退出（"Background subagent failed before it finished"），只留下部分中间产物（`/tmp/armB-out/`、`/private/tmp/armE-venv/`、`/private/tmp/armd-tools/`），**报告文件均未生成**。工具目录与中间产物得以保留，是主会话能快速接管补跑的关键。

---

## 三、P0 缺陷：PanWeiDB 下新注册用户完全无法登录

### 3.1 现象

```bash
POST /api/auth/register  → code=0, token=u.<32hex>.<64hex>, userId=<32 位 hex>
GET  /api/auth/me        → 401 {"detail":"invalid_session_user"}   # 注册 token
POST /api/auth/login     → code=0, token
GET  /api/auth/me        → 401 {"detail":"invalid_session_user"}   # 登录 token
GET  /api/sessions?userId=…  → 401 invalid_session_user
```

即：**注册成功、登录成功拿到 token，但任何需要鉴权的接口都 401**。存量 24 位用户（`6ab9dd0382f60252a4a40aa6` = zhujunfeng@bonc.com.cn）不受影响 —— 缺陷只打「迁移后新建」的记录。

### 3.2 根因链（三层，全部代码级 + 容器内实测确认）

1. **主键形态错位**：`services/{chat-api,admin-api,document-parser}/app/core/pg_compat.py` 的 `insert_one` / `replace_one` / `_update` 在 `_id` 缺失时用 `uuid.uuid4().hex` 生成 **32 位** hex（引入自 commit `0f13656`「feat(db): 引入 PanWeiDB 后端与 Mongo 兼容层（027 R1）」，2026-10-13）。
   - 与 `docs/mongo-to-panweidb-migration-plan.md` §2.9 / §4 的约定冲突：主键应统一落成 `str(ObjectId)`（**24 位**十六进制）。
   - 该文档 §2.9 当时写的「`ObjectId.is_valid(s)` 守卫：`_id` 恒为 24-hex，结果与原一致，不影响」在 uuid4 实现下**已被证伪**；文档同段的改造方向其实写的是「校验改为字符串长度/hex 判断」，实现偷懒用了 `ObjectId.is_valid`。
   - `deploy/pg/schema.sql` 全部表 `id TEXT PRIMARY KEY`，长度不限，24-hex 存得下。
2. **合法性守卫误杀**：`services/*/app/core/ids.py` 的 `is_valid_backend_id` 只认 `ObjectId.is_valid`（24 位），32 位一律判非法。调用点共 **81 处**（chat-api 41 / admin-api 18 / document-parser 4，另 `to_backend_id_strict` 10 处）。
3. **守卫转 401**：`services/chat-api/app/services/end_user_session.py:90-92`
   ```python
   user_id = str(session_doc.get("user_id") or "")
   if not is_valid_backend_id(user_id):
       raise HTTPException(status_code=401, detail="invalid_session_user")
   ```
   （该守卫由 `cf249ab` 从 `ObjectId.is_valid` 改名为 `is_valid_backend_id`，语义未变；最早来自 `7c5f63e` 022 安全加固 Phase 2。）

**容器内实测数据**（Round 6 修复前）：`end_users` 7 条 = 1 条 24 位（迁移期遗留）+ **6 条 32 位**（全部迁移后新建）；`end_user_sessions` 6 条 user_id 全 32 位；`to_backend_id('3522820d…')` 原样返回且 `find_one({'_id': …})` **能查到** → 证明查询本身没问题，**仅合法性守卫误杀**。

### 3.3 修复（用户决策 m00521 选「方案 b：把 id 生成为 24 位」）

| 文件 | 改动 |
| --- | --- |
| `services/*/app/core/pg_compat.py`（3 份） | 新增 `new_backend_id() -> str`（`return str(ObjectId())`），三处主键生成点全部改用它；`import uuid` 删除，`from bson import ObjectId` 接入（`pymongo==4.18.2` 已在依赖里，**无需新依赖**） |
| `services/*/app/core/ids.py`（3 份） | `is_valid_backend_id`：panwei 模式下额外接受 **32 位 hex**（`_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")`）；mongo 模式**语义不变**（仍只认 24-hex）。`to_backend_id_strict` 改用 `is_valid_backend_id` 判定（原先是 `ObjectId.is_valid`） |
| `services/chat-api/app/api/endpoints/auth.py` | `_find_active_user_by_id` 由 `ObjectId(user_id)` 改为 `is_valid_backend_id` + `to_backend_id`（非法主键 fail-closed 返回 None，**绝不自动建号**）；删除该文件已无用的 `from bson import ObjectId` |

**兼容性设计**：新记录一律 24 位（对齐文档契约），存量 32 位（`end_users` 6 条 / `chat_messages` 2 条 / 历史 `end_user_sessions`）**仍被接受**，老用户无需数据回填即可继续登录。

**不变量**：`deploy/tests/test_pg_compat_parity.py` 要求 admin-api 与 chat-api 的 `pg_compat.py` **byte identical**、document-parser 版本是 `scripts/pg/sync_pg_compat.py` 的机械同步产物 —— 改动后校验通过（14 passed）。

### 3.4 修复后运行态验证（全部 200）

```
POST /api/auth/register {tenantId: bonc-2331b8a0ecdbd2ebcbf253c4, email, password}
  → code=0, userId=6ad72e0cebf6e1b2e8a2ace8 （24 位 hex ✅）
GET  /api/auth/me (register token) → code=0 ✅
POST /api/auth/login → code=0, token ✅
GET  /api/auth/me (login token)    → code=0 ✅
POST /api/sessions {user_id}        → code=0, id=6ad72e11ebf6e1b2e8a2acec（24 位 ✅）
GET  /api/sessions?userId=&tenantId= → code=0，返回刚建的会话 ✅
GET  /api/sessions/{id}              → code=0 ✅
POST /api/sessions/{id}/messages     → code=0, message_count=1 ✅
```

**存量 32 位用户兼容验证**（容器内构造 32 位 user_id 的会话文档）：
```
resolve_session_user(32hex legacy) -> OK, user=regress6_1792480777@test.local ✅
_find_active_user_by_id(32hex)     -> regress6_1792480777@test.local ✅
_find_active_user_by_id(invalid)   -> None（fail-closed）✅
```

修复后 id 长度分布：`end_users {24: 2, 32: 6}`、`end_user_sessions {24: 2}`、`chat_sessions {24: 4}`、`chat_messages {24: 18, 32: 2}` —— **新建全 24 位，存量 32 位原样保留**。

> **P0 附带发现（同一根因）**：`services/chat-api/app/services/session_persistence_service.py:432/595` 的 `append_messages` / `end_session` 用 `to_backend_id_strict(session_id)`，32 位 session_id 会抛 `ValueError("非法 id")`。随 ids.py 放宽一并解除。

---

## 四、P1 缺陷：门户 SSO 按 user_id 解析用户必然 miss

`services/chat-api/app/api/endpoints/auth.py` 的 `_find_active_user_by_id` 裸用 `ObjectId(user_id)`。panwei 下 `_id` 是字符串，32 位 hex 必然 `InvalidId` → 查询抛错 → fail-closed 返回 None → 门户（`auth.py:998`、`:1065` 两处调用）永远解析不到新用户。

**已修**（见 3.3 表）。全仓残留裸 `ObjectId` 构造仅剩 `services/admin-api/app/api/routes/directory.py:64` 的 `_safe_oid`，其 panwei 分支已提前 `return str(value)`，不触发。

**附带修复的测试**：首次复跑时 `services/chat-api/tests/api/test_auth_portal_sso.py` 8 个用例失败 —— 根因是**测试自身的假 DB 是 mongo 形状**（种子写死 `ObjectId(USER_ID)`），而端点已改为后端感知查询。仓内已有同款写法（`services/chat-api/tests/test_security_session_timeout.py:212` 的 `"_id": to_backend_id(USER_ID)`），据此把种子改为 `to_backend_id(USER_ID)`，8 个用例恢复通过。

---

## 五、P2 缺陷：`setup/status` 的 storage 健康项恒失败

### 5.1 现象与根因

`GET /admin-api/api/setup/status` → `storage: ok=false, message="目录不可写: /data/knowledge-documents"`。探针代码在 `services/admin-api/app/api/routes/setup.py:151-161`（`os.access(path, os.W_OK)`）。

实际原因不是「`/data` 不可写」这么简单：

1. `/data` 本身是 rootfs 目录（`read_only: true`），但挂到 `/data/knowledge-documents` 的 `knowledge-storage` 卷**本身可写**。
2. 真正的失败点是卷内内容：卷内多出一层 `knowledge-documents/` 嵌套目录，且**所有目录属主是 `root:root 0755`**（2026-09-29 创建的老卷，Docker 只在卷**首次创建且为空**时继承镜像目录属主，后续重建镜像不会修正已有卷）。
3. 应用容器以 `appuser`（UID 10001）运行 → 写不进去。chat-api / document-api 同挂该卷，同样 `Permission denied`。
4. 嵌套目录**不是缺陷**：`_read_json_storage` 用 `settings.knowledge_oss_prefix`（默认 `"knowledge-documents"`）拼 storage_key，卷挂到 `/data/knowledge-documents` 后卷根多一层属设计。

### 5.2 修复

- **运行时**：对三个可写卷执行 `chown -R 10001:10001` → storage 健康项恢复 `ok=true`。
- **compose 层持久化**（防新部署复现，`docker-compose.yml`）：
  - bootstrap 服务新增 `cap_add: [CHOWN, FOWNER]`（原 `cap_drop: ALL` 保留），新增三个卷挂载 `knowledge-storage:/storage/knowledge`、`admin-static:/storage/admin-static`、`askai-storage:/storage/askai`（挂 `/storage/*` 而非 `/data/*`，因为镜像的 `/data` 在 rootfs 上）；
  - bootstrap 脚本在写完 secrets 后追加 `chown -R 10001:10001 /storage/knowledge /storage/admin-static /storage/askai`（幂等：已是 10001 时无副作用）。

**验证**（模拟老卷回退 root 属主 → 跑 bootstrap → 属主自动恢复）：
```
before: uid=0 gid=0
docker compose run --rm bootstrap
after:  uid=10001 gid=10001   ✅
```

---

## 六、回归套件结果

### 6.1 Round 6（修复前基线，Arm A 交付）

| 套件 | 结果 | 与 Round 5 比较 |
| --- | --- | --- |
| deploy Tier A 主体 | **189 passed / 7 skipped / 0 failed**（10.59s） | 完全相等 |
| 性能守卫 `test_performance_us7.py` | **7 passed**（4.73s） | 完全相等 |
| **合计** | **196 passed / 7 skipped** | **完全相等** |
| mongo parity 守卫 | 2 failed | **按设计 blocked**（前置断言 `assert not is_panweidb_backend()` 主动拒绝在 PanWeiDB 下跑） |
| CI 门禁脚本 10 条 | 8 exit 0 / **2 exit 1** | pre-existing（见下） |
| 变异测试 `verify_assertions.sh` | 9/9 全捕获 | — |

### 6.2 Round 7（修复后复跑，本轮自跑）

| 套件 | 结果 | 对照 |
| --- | --- | --- |
| deploy Tier A 主体 | **189 passed / 7 skipped**（8.97s） | 与 Round 5/6 完全相等 |
| 性能守卫 | **7 passed**（3.98s） | 相等 |
| **合计** | **196 passed / 7 skipped** | **零回归** |
| mongo parity（compose 网络内 + `MOGO_DATA_BACKEND=mongo`） | **2 passed** | 宿主直跑失败仅因 `app.ontology_permission` 在 admin-api 而非 chat-api |
| admin-api | **1008 passed**（7.30s） | Round 5 为 1005，+3 = 本轮新增 ids 用例 |
| chat-api | **2590 passed / 8 deselected**（55.88s） | **与 Round 5 完全相等** |
| document-parser | **26 passed**（9.62s） | **与 Round 5 完全相等** |
| `deploy/tests/test_pg_compat_parity.py` | 14 passed | 三服务 pg_compat 一致性 |

**测试执行配方**（踩坑已记录）：
```bash
docker run --rm --entrypoint python -w /mogo/services/<svc> \
  -v /Users/cooper/mogo:/mogo:ro -v /tmp/pytestlib_extracted:/tmp/pytestlib:ro \
  -e PYTHONDONTWRITEBYTECODE=1 -e MOGO_TEST_ROOT=/mogo \
  $(docker inspect mogo-<svc>-1 --format '{{range .Config.Env}}-e {{.}} {{end}}') \
  -e MOGO_DATA_BACKEND=PanWeiDB -e PANWEIDB_HOST=192.168.107.1 \
  -e PYTHONPATH=/tmp/pytestlib:/mogo/services/<svc> \
  <svc>:c5b3624 -m pytest tests -o addopts= -q --asyncio-mode=auto -p no:cacheprovider
```
坑位：
1. **`PYTHONPATH` 必须放在 `docker inspect` 复刻 env 之后** —— 复刻 env 含 `PYTHONPATH=/app`，会覆盖前面的赋值 → `No module named pytest`。
2. **必须 `-o addopts=`** —— 镜像内 pyproject 的 `addopts = "-q --timeout=120"`，而镜像无 `pytest-timeout` 插件 → `unrecognized arguments: --timeout=120`。
3. **必须挂整个 repo 到 `/mogo`**（`MOGO_TEST_ROOT=/mogo`）—— 5 个契约元测试与 4 个 quickstart/contract 存在性测试用 `Path(__file__).parents[N]` 推断 repo 根。
4. chat-api 需 `--ignore` 5 个契约元测试文件 + `-m "not dsh_host_e2e"`（8 项，需 Node Runtime Host）。

### 6.3 前端（Arm D 补跑）

| 项 | 结果 |
| --- | --- |
| user-web 契约测试 14 项 | **13 PASS / 1 FAIL**（`test:execution-v3`） |
| `test:execution-v3` 失败根因 | **环境问题，非产品回归**：脚本 `esbuild ... --external:jsdom` 后在 `/tmp` 下 `node` 解析不到 `jsdom`（`jsdom` 只是 `fabric` 的 optionalDependency，未提升到 `apps/user-web/node_modules` 顶层）。用 `NODE_PATH=apps/user-web/node_modules/.pnpm/jsdom@26.1.0_canvas@3.2.3/node_modules` 重跑 → **"execution-v3 store tests passed"** ✅ |
| user-web typecheck | **exit 0** ✅ |
| admin-web typecheck | **7 处 TS2678/TS2367 报错** —— 全部在 `src/components/setup/SetupModelFields.vue:77-91`（`"anthropic"/"gemini"/"ollama"` 与类型 `"" \| "openai_compatible" \| "azure_openai"` 不兼容），来自 commit `6a2e46b`「docs(specs): 补 031 模型供应商发现与多协议接入规格并扩展首次向导字段提示」—— **pre-existing，本轮未改前端任何文件** |
| 静态资源冒烟 | `/admin/` 200、`/app/` 200、`/admin/assets/index-659cc768.js` 200 (239165B)、`/assets/index-DqtcL8dP.js` 200 (399208B)、CSS 各 200、favicon 200 ✅ |

### 6.4 依赖安全审计（Arm E 补跑，pip-audit 2.10.1）

| 服务 | 结果 |
| --- | --- |
| admin-api | **No known vulnerabilities found** ✅ |
| document-parser | **No known vulnerabilities found** ✅ |
| chat-api | **11 条**：`idna 3.11` → PYSEC-2026-215（修 3.15）；`pypdf 6.16.2` → PYSEC-2026-4153/4154/4155/4156/4157/4158/4159/4160（修 6.17.0 ~ 6.19.0）；`requests 2.32.5` → PYSEC-2026-2275（修 2.33.0） |

chat-api 的 `requirements.txt` 是全量锁文件（2530+ 行）。**本轮未升级依赖**（超出 P0/P1/P2 修复范围，且属独立风险面），作为待办上报。

### 6.5 静态检查（pyflakes 4.0.3）

| 范围 | 结果 |
| --- | --- |
| admin-api / chat-api / document-parser 的 `app/` | 41 / 214 / 8 处提示 |
| **本轮改动的 9 个文件** | 仅 2 类，且**均在改动前已存在**（`git show HEAD~1:…` 复现）：`pg_compat.py:266 f-string is missing placeholders`（三份同源）、`document-parser/app/core/pg_compat.py:2003 undefined name 'AsyncIterator'` |

---

## 七、部署与镜像

| 项 | 结果 |
| --- | --- |
| 构建 | `MOGO_VERSION=c5b3624 ./mogo up --build` → 本地 buildx 构建 8 个镜像（document-worker 共用 document-parser 镜像） |
| 沙箱坑 | 首次构建在 workspace-write 沙箱下失败：`failed to update builder last activity time: open /Users/cooper/.docker/buildx/activity/.tmp-…: operation not permitted` → **需放宽到 danger-full-access**（与 Round 4 同一坑） |
| 容器状态 | 11 个 mogo 容器 + panweidb **全部 healthy**；`/askai-api/health` → `status=ok, version=0.2.4, backend=panweidb, reachable=true, dsh_host=healthy` |
| 镜像清理 | `prune_previous_release_images` 清掉 7 张旧镜像（~1359MB），现仅存 `*:c5b3624` 7 张，无 `v0.2.4` 残留 |
| 数据卷 | `movo_knowledge-storage` / `movo_admin-static` / `movo_askai-storage` 属主均 `10001:10001` |

**网关冒烟**：`/askai-api/health` 200、`/admin/` 200、`/app/` 200、`/admin-api/api/setup/status` 200（`ready=true`，services 全 ok）、`/api/auth/me` 无 token → 401（正确拒绝）。

---

## 八、发现但本轮未修的项（待办）

| 级别 | 问题 | 位置 | 说明 |
| --- | --- | --- | --- |
| 中 | admin-web typecheck 7 处 TS 报错 | `apps/admin-web/src/components/setup/SetupModelFields.vue:77-91` | pre-existing（`6a2e46b`），031 规格扩展了供应商类型但未同步联合类型 |
| 中 | chat-api 3 个依赖有 11 条 CVE | `services/chat-api/requirements.txt`（idna 3.11 / pypdf 6.16.2 / requests 2.32.5） | 需独立评估升级 |
| 中 | CI 门禁脚本 2 条 exit 1 | `services/chat-api/scripts/check_dsh_upgrade_contract.py`（阻断 `runtime-guard.yml:62`、`dsh-migration-step1.yml:61`）、`scripts/check-secrets.sh --all`（阻断 `quality-gate.yml:45`） | pre-existing，Arm A 在 Round 5 基线提交 `5792799` 上逐字复现 |
| 低 | `test:execution-v3` 需 `NODE_PATH` 才能跑 | `apps/user-web/package.json` | `jsdom` 只是 `fabric` 的 optionalDependency，未提升到顶层；CI 侧 `npm ci` 但仓库只有 `pnpm-lock.yaml`，无 `package-lock.json` |
| 低 | `apps/user-web` 的 CI 用 `npm ci` 但无 `package-lock.json` | `.github/workflows/dsh-migration-step1.yml:118` | 同上 |

---

## 九、提交与工作区

| 提交 | 内容 |
| --- | --- |
| `c5b3624` | `fix(db): 修复 PanWeiDB 下新注册用户无法登录，并修正 storage 健康项` —— 10 个文件，+183 / -37：`docker-compose.yml`、三份 `ids.py`、三份 `pg_compat.py`、`services/chat-api/app/api/endpoints/auth.py`、`services/admin-api/tests/test_ids.py`、`services/chat-api/tests/api/test_auth_portal_sso.py` |

工作区终态干净（`git status --porcelain` 为空），仅暂存并提交本轮确认改过的 10 个具体路径，未用 `git add -A`。

---

## 十、下一轮建议（Round 8）

1. **回归基线已更新**：Round 7 = admin-api 1008 / chat-api 2590 / document-parser 26 / deploy 196+7 skipped。后续轮次以此为基线。
2. **优先修 admin-web typecheck**（阻断 `pnpm run typecheck`，是唯一的红）。
3. **单独排期升级 chat-api 三个依赖**（idna / pypdf / requests）。
4. **补 `apps/user-web` 的 `package-lock.json` 或把 CI 改成 pnpm**，让 `test:execution-v3` 在 CI 里真跑起来。
5. **补 Arm D / Arm E 的 subagent 稳定性** —— 本轮三个臂中途失败，被迫由主会话接管；建议下次拆得更小或改用 workflow 脚本编排。
6. **P0 修复后建议补一条端到端守卫**（`deploy/tests/`）：注册 → `/api/auth/me` → 建会话 → 列会话，锁死「新建用户可登录」这条不变量，避免主键形态再次漂移。
