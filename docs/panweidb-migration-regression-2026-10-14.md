# PanWeiDB 迁移完整回归测试报告

**日期**：2026-10-14
**分支 / 提交**：`feat/migrate-mongo-to-panweidb` @ `cf249ab`（隔离 worktree `/tmp/mogo-mig`）
**目标**：验证在**完全不使用 MongoDB** 的前提下，应用在 PanWeiDB 后端下能够正常运行。

## 测试条件

- `MOGO_DATA_BACKEND=panweidb`
- PanWeiDB 3.2.0 @ `127.0.0.1:5432`（`bonc` 库；回归使用独立 schema `regress_*`，不污染真实 `mogo_dev` 数据）
- **`MONGODB_URI=mongodb://127.0.0.1:1`（不可达）** —— 若任何代码路径偷偷依赖 mongo，会立即失败暴露
- 各服务自带 venv（含 `pytest-asyncio`），`--basetemp` 指向受控目录（绕开沙箱 shim 对 `tmp_path` 的干扰）

## 结果

### 1. 全量测试套件（panwei 后端，无 mongo）

| 服务 | 用例数 | 结果 |
|---|---|---|
| admin-api | 926 | ✅ rc=0，0 failed / 0 error |
| chat-api | 2583（另 8 个 `dsh_host_e2e` 因需真实 Node 运行时被排除） | ✅ rc=0，0 failed / 0 error |
| document-parser | 22 | ✅ rc=0，0 failed / 0 error |
| **合计** | **3531** | ✅ 全绿 |

### 2. 兼容层守卫

| 项 | 结果 |
|---|---|
| `pg_compat` 单测（聚合 / 更新 / 索引 / 正则 / TTL 等） | ✅ |
| 三副本 parity（异步两份逐字节一致 + 同步副本等于机械变换） | ✅ |
| **合计** | ✅ **73 项全过** |

### 3. 端到端（连真实 PanWeiDB）

| 服务 | 验证内容 | 结果 |
|---|---|---|
| admin-api | FastAPI lifespan 启动 + `GET /health`（200，`backend=panweidb`，`reachable=true`）+ DB 写入/读取/删除往返 | ✅ PASS |
| chat-api | panwei 后端初始化 + DB 往返（insert/find/delete） | ✅ PASS |
| document-parser | panwei 后端初始化 + DB 往返 | ✅ PASS |

### 4. 静态检查

- mongo 客户端（`AsyncIOMotorClient` / `MongoClient`）的创建**只出现在 `init_db()` 的 mongo 分支**，panwei 模式不会触发；无模块级 eager 连接。

## 边界与未覆盖

- `dsh_host_e2e`（8 个）：需 spawn 真实 Node DSH Runtime Host 子进程 + loopback 端口，属**环境依赖**（与 mongo 无关），已排除。
- chat-api 的**完整** lifespan 会拉起 DSH runtime host 子进程，沙箱内被 SIGTERM；故 chat 端到端改用「后端初始化 + DB 往返」等价验证（其 app 启动路径已在 2583 个用例中经 TestClient 覆盖）。
- 本轮聚焦用户要求的「无 mongo」场景；**未**执行 mongo 模式（默认路径）回归。

## 结论

在 **无 MongoDB** 环境下，三服务（admin-api / chat-api / document-parser）在 PanWeiDB 后端下**全部回归通过**：

- 3531 个用例全绿；
- 兼容层守卫 73 项全过；
- 端到端启动与 DB 往返正常。

T083（TTL 应用层清理）与 T085（主键调用点后端解耦）改造**未引入对 mongo 的残留依赖**，应用可在完全不使用 MongoDB 的情况下正常运行。
