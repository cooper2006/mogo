# ARM 准生产回归 · 2026-11-02

> 本轮形态：**离线 bundle 加速构建 → `MOGO_VERSION` 取当前提交短哈希 → `./mogo up --build` 重建 7 个应用镜像 → 清理旧版本残留镜像 → 确认 healthy → 容器内/宿主回归测试 → 产出报告**。

## 一、结论

`MOGO_VERSION=a4486332` 离线 bundle 构建成功（exit 0），7 应用镜像全部 `linux/arm64`；上个版本残留镜像已自动清理（仅剩 `*:a4486332`，dangling 0）；11 服务 healthy；五套件回归 **admin-api 1518 / document-parser 72 / chat-api 3101 / deploy 守卫 316 / mongo 判权等价 2** 全绿，网关冒烟 **5/5**，**`a4486332` 未引入回归**。

## 二、构建与部署

| 项 | 值 |
| --- | --- |
| 命令 | `MOGO_VERSION=a4486332 ./mogo up --build`（离线 bundle 加速） |
| 构建退出码 | `0`（job `bash-b694c4eccb4f4782`） |
| 镜像 tag | `git rev-parse --short HEAD` = **`a4486332`**（7 个应用镜像统一） |
| 基础镜像架构校验 | `export_base_images.sh list` → python/node/nginx 全部 `linux/arm64` ✅ |
| 离线 bundle | apt / pip / playwright 三套命中本地 bundle（`APT_OFFLINE_INSTALL=true`、`PIP_OFFLINE_INSTALL=true`） |
| 旧镜像清理 | `prune_previous_release_images` 生效，现仅存 `*:a4486332` 7 张，无其他 tag |
| 悬空镜像 | `docker images -f dangling=true` → **0** |

镜像体积：chat-api 4.33GB、document-parser 5.25GB、dsh-runtime-host 1.31GB、admin-api 445MB、user-web 47.3MB、admin-web 45.7MB、gateway 30.9MB。

## 三、健康与运行态

| 项 | 结果 |
| --- | --- |
| 容器 | 11 个运行、**全部 healthy**（`document-worker` 无 healthcheck，设计如此） |
| 运行镜像 tag | 全部 `a4486332` |
| gateway | restart count **0**，健康 |
| 网关冒烟 | `/healthz` 200、`/admin/` 200、`/admin-api/api/setup/status` 301→200、`/askai-api/health` 200（`backend=mongo`、`dsh_host=healthy`）、`/api/auth/me` 301→401（正确拒绝未认证） |

## 四、回归测试（ARM 准生产运行态）

| 套件 | 跑法 | 结果 | 对照基线（round 14 `ee65305`） |
| --- | --- | --- | --- |
| admin-api 全量 pytest | 容器内，`--network mogo_backend`，`-m "not dsh_host_e2e"` | **1518 passed, 1 skipped, 0 failed**（51s） | 1484 → +34（新增用例） |
| document-parser 全量 | 容器内 | **72 passed, 6 skipped, 0 failed**（6s） | 28 → +44（新增用例） |
| chat-api 全量 | 容器内，`MOGO_TEST=1`，`-m "not dsh_host_e2e and not network"` | **3101 passed, 3 skipped, 27 deselected, 0 failed**（28s） | 3001 → +100（新增用例） |
| deploy/tests 守卫 | 宿主 Python 3.13，排除 mongo-only 文件 | **316 passed, 7 skipped, 0 failed**（17s） | 266 passed / 2 failed（既有断言漂移本轮已清） |
| mongo 判权等价 | admin-api 容器内，`MOGO_DATA_BACKEND=mongo`，`mogo_backend` 网络 | **2 passed, 0 failed**（0.2s） | 一致 |

**对照说明**：admin-api / document-parser / chat-api 较 round 14 的增长均来自 `a4486332` 相对 `ee65305` 新增的用例（含 `sandbox_script/test_prepare_skill.py` 等），非回归。deploy 守卫本轮 0 failed：round 14 记录的 2 条既有断言漂移（`test_sso_token_not_in_url.py` 前端路径迁移、`test_tls_gateway_config.py` nginx 配置漂移）在本轮已消除或未复现。

## 五、测试执行配方（供后续轮次复用）

容器内跑法（挂载仓库 + pytestlib）：

```bash
# 1) 构建 pytestlib（一次性）
pip3 install --target /tmp/pytestlib_extracted pytest pytest-asyncio pytest-timeout

# 2) 容器内跑服务全量测试
docker run --rm --network mogo_backend --entrypoint python -w /tmp \
  -v /Users/cooper/mogo:/mogo:ro -v /tmp/pytestlib_extracted:/tmp/pytestlib:ro \
  $(python3 .dsh-tmp/gen_env_args.py <svc>) \
  -e MOGO_TEST=1 \
  -e PYTHONPATH=/app:/tmp/pytestlib:/mogo/services/<svc>[:/mogo/services/<svc>/sandbox_script] \
  ghcr.io/mogoai/<svc>:a4486332 \
  -m pytest /mogo/services/<svc>/tests -q -p no:cacheprovider -o addopts= -m "not dsh_host_e2e[ and not network]"
```

踩坑（本轮新遇到）：
- **`sandbox_script/test_prepare_skill.py` 导入 `prepare_skill` 失败**：该测试来自 commit `9e58006f`（2026-10-31），`prepare_skill.py` 位于 `services/chat-api/sandbox_script/`，conftest 未自动加 sys.path。容器内跑法需把 `/mogo/services/chat-api/sandbox_script` 追加到 `PYTHONPATH`。
- **`PYTHONPATH` 必须放在 `gen_env_args.py` 复刻 env 之后**（复刻 env 含 `PYTHONPATH=/app`，后置赋值覆盖）。

## 六、结论

- 构建、打包、重启、旧镜像清理、healthy 确认均达成；
- 五套件 + 网关冒烟全绿（或与基线一致），**`a4486332` 未引入回归**；
- 本轮未修改任何 tracked 文件（`git status` 仅有的其他会话在途改动 `scripts/pg/dev-forward/Dockerfile` 及未跟踪文档，未触碰）。
