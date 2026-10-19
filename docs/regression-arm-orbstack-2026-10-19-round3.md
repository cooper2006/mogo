# OrbStack 准生产环境回归 · Round 3（2026-10-19）

> ADR-5 多轮回归第三轮。用户拍板：**收尾存档，不碰 `services/*`**（三服务源码级测试留待并行会话把 `services/*` 在途改动提交后再开 Round 4）。
> 本轮实际完成两块零风险、高价值工作：① Tier A 重跑确认环境滚动重建零回归；② ARM 架构原生核验（ADR-5 点名项）。

---

## 一、结论（一句话）

**Round 3 零回归 + ARM 原生全绿**：Tier A 守卫重跑与 Round 2 完全一致（**196 passed / 7 skipped**）；宿主与全部 11 个业务镜像均为 `linux/arm64`，**无 amd64 串台、无 rosetta 回退**。三服务源码级测试按用户决策暂缓，不触碰 `services/*` 在途改动边界。

---

## 二、环境基线（本轮开工）

- 11 容器全 `healthy`。但相对 Round 2，**gateway / chat-api / admin-api / document-api 已被滚动重建**（状态 `Up 2-3 hours`）；这正是 Tier A 重跑要严格验证的对象。
- `MOGO_DATA_BACKEND=PanWeiDB`；`MOGO_TLS=0`；纯 HTTP 网关。
- `git status` 仍显示 `services/admin-api/app/main.py`、`services/chat-api/app/main.py`、`pyproject.toml` 等**未提交改动**——属其他会话在途工作，本轮不碰、不提交。

---

## 三、Tier A 重跑（验证滚动重建零回归）

调用与 Round 2 canonical 配方一致（隔离 venv `/tmp/mogo-round2-venv`）：
```bash
COMPOSE_PROFILES=pool MOGO_TLS=1 PYTHONPATH=services/admin-api \
  python -m pytest deploy/tests/ -q -p no:cacheprovider \
  --ignore=deploy/tests/test_performance_us7.py \
  --ignore=deploy/tests/test_ontology_permission_mongo_parity.py
# → 189 passed, 7 skipped
PYTHONPATH=services/chat-api python -m pytest deploy/tests/test_performance_us7.py -q -p no:cacheprovider
# → 7 passed
```
**结果 = 196 passed / 7 skipped，与 Round 2 完全相等**。证明这几小时的镜像滚动重建（gateway 带 D1 根治、chat-api 版本对齐 0.2.3、document-api 共用 document-parser 镜像）**未引入任何守卫级回归**。

---

## 四、ARM 架构原生核验（ADR-5 点名项）

| 项 | 结果 |
| --- | --- |
| 宿主 arch（Apple Silicon + OrbStack） | `arm64` |
| 业务镜像平台 | **全部 `linux/arm64`**（admin-api 421MB / chat-api 4.46GB / document-parser 6.2GB / dsh-runtime-host 1.23GB / gateway 30.9MB / user-web / admin-web / bootstrap 等） |
| mongo / redis / weaviate 基础镜像 | `linux/arm64/v8` 官方镜像 |
| amd64 串台 / rosetta 模拟回退 | **无** |

准生产环境在 ARM 上**原生运行**，符合 ADR-5「ARM 架构」验收。

---

## 五、历史判断修正（供后续轮次校准）

- **「R8 方法」是误称**：仓库里 `R8` 仅指另一会话遗留的 chat-api 版本号未提交改动（`0.2.1→0.2.3`），**不是测试方法**。Round 2 报告照搬该说法，此处纠正。
- **「document-api 独立源码」不存在**：`mogo-document-api-1` 与 `document-worker` 共用 `document-parser` 镜像（`docker-compose.build.yml:29-34` 注释明确），源码树在 `services/document-parser/`。
- **三服务镜像不含 `tests/` 且 chat-api/document-api 镜像未装 pytest**：`Dockerfile` 只 `COPY entrypoint.sh` + 应用代码，未 COPY `tests`；pytest 仅 admin-api 依赖树携带。故「三服务全量测试」必须**挂载 `services/<svc>/tests` 进容器 + 装 pytest**，或重建带测试依赖的镜像——不能直接裸跑容器（Round 1/2 的判断路径需据此修正）。

---

## 六、本轮已闭环项（Done）

- Tier A 重跑零回归（滚动重建安全）。
- ARM 原生 arm64 全绿（ADR-5 点名项验收通过）。
- 三处历史判断修正记录（R8 误称 / document-api 镜像归属 / 测试挂载必要性）。

---

## 七、遗留待办（Open → 移交 Round 4+）

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 三服务源码级全量测试 | 暂缓（用户拍板） | 等到并行会话把 `services/*/main.py` 等未提交改动提交后再开 Round 4；届时用「挂载 `services/<svc>/tests` 进容器 + 装 pytest（只读挂载，不碰镜像/构建）」方式跑，避免撞车 |
| TLS 启用 | 维持 `MOGO_TLS=0` | 仍拍板不动 |
| `.env` 口令与 `panweidb_up.sh` 默认分叉 | 配置卫生 | 脚本硬编码 `APP_PW='1qaz!QAZ'` 已连不上，不阻断，后续同步 |
| 故障转移 / 压测 | 未排 | Tier C 重项，依赖环境稳定与在途改动落定 |

Open objectives: 以 OrbStack 为准生产环境执行多轮回归（ADR-5，m00002）。
