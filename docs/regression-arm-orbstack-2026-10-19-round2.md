# OrbStack 准生产环境回归 · Round 2（2026-10-19）

> ADR-5 多轮回归的第二轮。范围 = **Tier A**：在本地复刻 `deploy/tests/` 全套静态/集成守卫（即 CI 同款门禁、022 加固守卫、TLS 网关守卫、供应链/本体权限/数据安全/性能守卫）。
> 用户拍板：本轮**只跑 Tier A**；TLS 维持 `MOGO_TLS=0` 不动；三服务全量测试 / 故障转移 / ARM 压测暂缓（等 `services/*` 在途改动落定，避免与并行会话撞车）。

---

## 一、结论（一句话）

**Round 2 Tier A 零回归**：`deploy/tests/` 在正确调用下 **196 断言通过 / 7 跳过 / 2 环境门槛（非缺陷）**；首跑看到的 30 个「失败」**全部是测试运行器调用缺参数/缺环境变量导致的假阳性，无一对应产品缺陷**。

---

## 二、环境基线（复用 Round 1 已恢复状态）

- 11 容器全 `healthy`，gateway / chat-api 均带 D1 根治（`resolver 127.0.0.11` + 变量式 `proxy_pass`）。
- `MOGO_DATA_BACKEND=PanWeiDB`（当前数据后端为 PanWeiDB，非 mongo）。
- `MOGO_TLS=0`，`MOGO_NGINX_CONF=./deploy/docker/nginx.conf`（纯 HTTP，与 Round 1 决策一致）。
- `mogo-mongo-1` 容器 `running`（但本环境业务走 PanWeiDB，不解析 `mogo-mongo-1`）。

---

## 三、首跑（naive）结果 → 必须正确调用才能解读

naive 跑（无 `COMPOSE_PROFILES`、无 `MOGO_TLS`、无 `PYTHONPATH`）：**30 failed, 168 passed, 7 skipped**。

**首跑 30 失败 ≠ 30 缺陷**。逐类加回正确调用后，全部消失或归类为环境门槛：

| 文件 | naive 失败 | 根因（运行器侧，非产品） | 正确调用后 |
| --- | --- | --- | --- |
| `test_container_hardening.py` | 14 | 缺 `COMPOSE_PROFILES=pool` → `dsh-runtime-host-{1,2,3}` 被 profile 门控、默认 `docker compose config` 看不到 | `COMPOSE_PROFILES=pool` → **81 passed / 6 skipped** |
| `test_tls_gateway_config.py` | 4 | 缺 `MOGO_TLS=1` → `movo_tls_is_enabled`（mogo:252）把 TLS 默认判为 off，cert-guard 直接 `return 0` 不生成证书 | `MOGO_TLS=1` → **18 passed** |
| `test_data_security_us5.py` | 5 | 缺 `PYTHONPATH=services/admin-api` + 服务依赖 → `ModuleNotFoundError: No module named 'app'` | `PYTHONPATH=services/admin-api` → **23 passed** |
| `test_performance_us7.py` | 6 | 缺 `PYTHONPATH=services/chat-api` + 依赖 → `ModuleNotFoundError: app/pydantic_settings/starlette` | `PYTHONPATH=services/chat-api` → **7 passed** |
| `test_ontology_permission_mongo_parity.py` | 2 | 设计门槛：本文件须 `MOGO_DATA_BACKEND=mongo` + 能解析 `mogo-mongo-1`（文件头注释明确）；当前 PanWeiDB 环境触发 `assert not is_panweidb_backend()` + `psycopg_pool.PoolTimeout` | **环境门槛，非缺陷，按设计 skip/blocked** |

> `deploy/tests` 未被 CI 自动调用（仅在 spec/quickstart 文档里作为手动守卫被引用），因此没有统一的 `pytest.ini` / conftest 注入 `COMPOSE_PROFILES` / `PYTHONPATH`。这正是 naive 跑误报的根因——调用姿势要按文件补齐。

---

## 四、Tier A 正确调用（canonical，可复刻）

```bash
VENV=/tmp/mogo-round2-venv   # 隔离 venv：python3 -m venv + pip install pytest pytest-asyncio -r services/<svc>/requirements.txt
cd /Users/cooper/mogo

# 主体（除 performance_us7 与 ontology mongo_parity）：需要 pool profile + TLS 开关 + admin-api 路径
COMPOSE_PROFILES=pool MOGO_TLS=1 PYTHONPATH=services/admin-api \
  "$VENV/bin/python" -m pytest deploy/tests/ -q -p no:cacheprovider \
  --ignore=deploy/tests/test_performance_us7.py \
  --ignore=deploy/tests/test_ontology_permission_mongo_parity.py
# → 189 passed, 7 skipped

# 性能守卫（chat-api 路径，纯离线 import，不需活服务）
PYTHONPATH=services/chat-api "$VENV/bin/python" -m pytest deploy/tests/test_performance_us7.py -q
# → 7 passed

# ontology mongo 等价守卫：仅在 MOGO_DATA_BACKEND=mongo 且 mogo-mongo-1 可达时跑（否则按设计 blocked）
```

**注意 `MOGO_TLS=1` 只是让 cert-guard 守卫用例进入「TLS 开启」分支去断言生成/重启逻辑**——它不真正改 `.env`、不动运行环境（Round 1 已拍板 `MOGO_TLS=0` 维持不变）。测试运行器的 env 与部署 env 是两回事。

---

## 五、覆盖到的守卫（全部绿）

- **022 加固守卫**（`test_container_hardening.py`）：4 应用镜像 `USER appuser`/UID 10001、8 服务 `cap_drop ALL`/`no-new-privileges`/`read_only`/tmpfs（含 `dsh-runtime-host` 池副本 + `single-host` profile 不被绕过）、nginx 非 root 主配置、`bootstrap umask 022`。**81 passed / 6 skipped（镜像本地缺失时运行时用例自动 skip）**。
- **TLS 网关守卫**（`test_tls_gateway_config.py`）：`$connection_upgrade` map 定义、两份 TLS 配置语义等价、私钥 0644、`setup-certs.sh` 自检、compose 挂载只读 + 443 暴露、`mogo` cert-guard 生成/不覆盖/跳过 HTTP 侧/无 openssl 快速失败/重启网关/读 `.env` 开关、i18n 双语。**18 passed**。
- **数据安全 US5**（`test_data_security_us5.py`）：TLS 协议/套件/301/HSTS/转发头、密文存储、日志脱敏、审计防篡改+保留期(180d)+库分离、数据地图、仓库层明文扫描。**23 passed**。
- **性能 US7**（`test_performance_us7.py`）：口令校验/登录链路/JWT 解码/令牌拒绝/CORS 预检与拒绝 p95（阈值为目标 2 倍，纯回归检测）。**7 passed**。
- **供应链 US6 / GET 无副作用 / SSO token / PG 兼容 parity / supply chain** 等其余 `deploy/tests` 文件：**均随主体 PASS A 一并 189 passed 覆盖**。

---

## 六、本轮已闭环项（Done）

- **Tier A 守卫全绿 + 误报定性**：确认 022 加固、TLS 网关、数据安全、性能、供应链等 CI 同款门禁在 OrbStack 准生产环境**无回归**；澄清 30 首跑失败 100% 为调用缺参假阳性，避免误判为缺陷。
- **`deploy/tests` 正确调用配方固化**（见第四节），供后续轮次 / 其他会话直接复刻，不再重踩 naive 误报。

---

## 七、遗留待办（Open → 移交 Round 3+）

| 项 | 状态 | 说明 |
| --- | --- | --- |
| TLS 启用 | 维持 `MOGO_TLS=0` | 用户本轮仍拍板不动；若后续启用，需改 `.env` + 挂证书 + 用 `nginx-https.conf`（已含 D1 根治）并复验就绪探针 |
| `.env` 口令与 `panweidb_up.sh` 默认分叉 | 配置卫生 | 脚本硬编码 `APP_PW='1qaz!QAZ'` 已连不上，不阻断，后续同步 |
| 三服务全量测试 | 暂缓 | 等 `services/*/main.py` 等并行会话在途改动提交后再排，避免撞车（容器内仅 admin-api 有 pytest；chat-api/document-api 按 R8 方法） |
| ARM 架构 / 故障转移压测 | 未排 | Tier C，依赖环境稳定与在途改动落定 |
| ontology mongo 等价守卫 | 环境门槛 | 须 `MOGO_DATA_BACKEND=mongo` + `mogo-mongo-1` 可达；当前 PanWeiDB 环境下按设计 blocked，**非缺陷** |

Open objectives: 以 OrbStack 为准生产环境执行多轮回归（ADR-5，m00002）。
