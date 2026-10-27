# ARM 准生产回归 · 2026-10-27 round 12（mongo 后端完整回归）

> 本轮形态：**用户将后端切到 mongo（`.env` 的 `MOGO_DATA_BACKEND=mongo`）→ 重启服务应用 → 确认 healthy → 全套件回归**。镜像 `570012e` 不变，无代码改动。

## 一、后端切换与运行

| 项 | 结果 |
| --- | --- |
| `.env` 设置 | `MOGO_DATA_BACKEND=mongo`（第 24 行） |
| 重启命令 | `./mogo up`（不重建镜像，仅重建容器配置），`EXIT=0` |
| gateway `/askai-api/health` | `{"status":"ok","backend":"mongo", ...}` |
| chat-api / admin-api 容器 env | `MOGO_DATA_BACKEND=mongo` |
| mongo ping | `{ ok: 1 }` |
| 服务健康 | gateway / chat-api / admin-api / document-api / mongo 全部 `healthy` |

## 二、回归结果（全部在 mongo 后端下）

| 套件 | 跑法 | 结果 | 对照 round 11 |
| --- | --- | --- | --- |
| admin-api 全量 pytest | 容器 `--network mogo_backend`，`-m "not dsh_host_e2e"` | **1470 passed, 1 skipped, 0 failed**（65s） | 一致 |
| document-parser 全量 pytest | 容器内 | **28 passed, 0 failed**（20s） | 一致 |
| chat-api 全量 pytest | 容器内，`MOGO_TEST=1`，`-m "not dsh_host_e2e and not network"` | **2985 passed, 3 skipped, 27 deselected, 0 failed**（49s） | 一致 |
| deploy/tests 守卫 | 宿主 `/tmp/deploy-venv`，`env -u MOGO_TLS`，忽略 mongo-only 文件 | **275 passed, 13 skipped, 0 failed**（19s） | 一致 |
| deploy mongo 判权等价 | admin-api:570012e 容器内，`MOGO_DATA_BACKEND=mongo` | **8 passed / 0 failed** | 一致 |

## 三、宿主 deploy/tests 的差异说明

- 初次宿主跑（系统 `python3`，未忽略 mongo-only 文件）得到 `1 failed, 276 passed, 13 skipped`。失败用例 `test_ontology_permission_mongo_parity::test_mongo_backend_repository_parity` 报 `pymongo.ConfigurationError: Empty host`。
- 根因：该文件文档化要求**容器内 `--network mogo_backend`** 运行（宿主无 `MONGODB_URI`、也无法解析 `mogo-mongo-1`），宿主直接跑不满足条件；round 11 即用**忽略该文件** + **容器内单独跑**的方式处理。
- 按 round 11 正确方式重跑后：宿主 `275 passed, 13 skipped, 0 failed`；容器内直跑该文件 `8 passed / 0 failed`。与基线逐字一致，**非本轮引入**。

## 四、结论

- 后端切换到 mongo 后，`570012e` 镜像下四套件 + mongo 判权等价**全绿**，与 round 11（PanWeiDB）基线逐字一致；
- 本轮未修改任何 tracked 文件（`git status` 仅既有未跟踪文件：`.dsh-tmp/`、`docs/panweidb-migration-daily-inspection-2026-10-27.md`、`docs/regression-arm-orbstack-2026-10-27-round11.md`）。
