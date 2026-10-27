# ARM 准生产回归 · 2026-10-27 round 11

> 本轮形态：**离线 bundle 加速构建 → `MOGO_VERSION` 取当前提交短哈希 → `./mogo up --build` 重建 7 个应用镜像 → 清理旧版本残留镜像 → 确认 13 容器 healthy → 容器内/宿主回归测试 → 产出报告**。

## 一、构建与运行

| 项 | 结果 |
| --- | --- |
| 构建命令 | `./mogo up --build`（离线 bundle 加速） |
| 构建退出码 | `EXIT=0`（`/tmp/mogo-round11/up-build2.log`） |
| 镜像 tag | `git rev-parse --short HEAD` = **`570012e`**（7 个应用镜像统一） |
| 运行容器 | 13 个 Up，其中 12 个 `healthy`（`document-worker` 无 healthcheck，设计如此） |
| 旧镜像清理 | `a0a6a08` 已从 orbstack 移除，dangling = 0 |
| 健康端点 | gateway `/askai-api/health`→200、`/healthz`→200；admin-api `/health`→200，`backend=panweidb, reachable=true` |

构建 tag 由 `mogo` 脚本默认逻辑决定（`mogo_default_version` → `git -C "$ROOT_DIR" rev-parse --short HEAD`），显式 `MOGO_VERSION` 环境变量仍可覆盖。

## 二、回归结果（全部在新镜像 `570012e` 内 / 宿主跑）

| 套件 | 跑法 | 结果 |
| --- | --- | --- |
| admin-api 全量 pytest | 容器 `--network mogo_backend`，`-m "not dsh_host_e2e"` | **1470 passed, 1 skipped, 0 failed**（20:05） |
| document-parser 全量 pytest | 容器内 | **28 passed, 0 failed**（12s） |
| chat-api 全量 pytest | 容器内，`MOGO_TEST=1`，`-m "not dsh_host_e2e and not network"` | **2985 passed, 3 skipped, 27 deselected, 0 failed**（36s） |
| deploy/tests 守卫 | 宿主 `/tmp/deploy-venv`，干净 env（`env -u MOGO_TLS`），忽略 mongo-only 文件 | **275 passed, 13 skipped, 0 failed**（19s） |
| deploy mongo 判权等价 | admin-api:570012e 容器内，`MOGO_DATA_BACKEND=mongo` | **8 passed / 0 failed** |

**对照基线**：deploy 干净环境 275 + 2（mongo parity，容器内跑）= **277 passed, 13 skipped, 0 failed**，与 `a2801db` 记录的基线完全一致。chat-api 较 `a2801db` 基线 +8，源于 `570012e` 为 030 判权修复新增的冒烟用例（admin +68 行 / chat +24 行）。

## 三、失败归因（非构建回归）

`./mogo up --build` 后跑 deploy 守卫时，在 `MOGO_TLS=1` 父环境下出现 3 条失败，逐条核实均为环境/测试夹具问题：

| 用例 | 现象 | 根因 |
| --- | --- | --- |
| `test_ontology_permission_mongo_parity::test_mongo_backend_selected` | `assert not is_panweidb_backend()` 失败 | 该文件须 `MOGO_DATA_BACKEND=mongo` + mongo 网络（文档化「容器内跑」）；宿主 PanWeiDB 环境按设计不满足。容器内跑已 8 passed。 |
| `test_ontology_permission_mongo_parity::test_mongo_backend_repository_parity` | `ModuleNotFoundError: No module named 'psycopg_pool'` | 宿主 deploy venv 缺 `psycopg_pool`（admin-api 运行时依赖），容器内镜像具备。非构建引入。 |
| `test_tls_gateway_config::test_tls_cert_guard_reads_switch_from_dotenv` | `.env` 指定 HTTP 侧配置仍生成证书 | 父进程 `MOGO_TLS=1` 泄漏进 `_run_ensure_tls` 的 `env`（测试用 `env.update(...)` 而非 `setdefault` 是有意的，但父级已设的值不会被清除）。`env -u MOGO_TLS` 下该用例通过。 |

## 四、既有软降级（记录，非本轮引入）

admin-api / chat-api 启动日志出现 `opentelemetry.instrumentation` 缺失告警，来自 `app/common/observability_base.py:275/295` 的 try/except 软降级路径。核实：

- `git log -S "opentelemetry-instrumentation"` 在 `requirements.in` 无命中 —— 该 instrumentation 包**从未进入依赖**；
- `requirements.in` 只声明 `opentelemetry-api/sdk/exporter-otlp`；
- 服务健康不受影响（`/health` 均 200，PanWeiDB reachable）。

属既有观测性软降级，非 `570012e` 构建引入，本报告仅记录、不处理。

## 五、结论

- 构建、打包、重启、旧镜像清理、healthy 确认均达成；
- 四套件 + mongo 判权等价全绿（或与基线逐字一致），**`570012e` 未引入回归**；
- 本轮未修改任何 tracked 文件（`git status` 仅 2 个既有未跟踪文件：`.dsh-tmp/`、`docs/panweidb-migration-daily-inspection-2026-10-27.md`）。
