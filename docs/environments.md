# 运行环境 profile（dev / test / prod）

MOGO 用 Compose profile 固化三个运行环境，启动时用 `--profile` 指定。profile 决定
**用哪个数据库、数据库在栈内还是栈外、容器跑在什么架构上**，其余服务（网关、应用、
redis、weaviate）三个环境都一样。

```bash
./mogo --profile dev up --build     # 开发：arm64 + 栈内 mongo
./mogo --profile test up --build    # 测试：arm64 + 栈内 panweidb
./mogo --profile prod up            # 生产：amd64 + 外部 panweidb
```

`--profile` 可以放在任意位置（`./mogo up --profile dev` 等价），也可以写成
`--profile=dev`，或用环境变量 `MOGO_PROFILE=dev ./mogo up`。

## 1. 三个环境

| profile | 目标架构 | 数据库 | 栈内数据库容器 | 典型用途 |
|---------|----------|--------|----------------|----------|
| `dev` | linux/arm64 | MongoDB | `mongo`（`profiles: [dev]`） | 本机开发、快速改代码、造数 |
| `test` | linux/arm64 | PanWeiDB | `panweidb`（`profiles: [panweidb, test]`） | 迁移验证、PanWeiDB 兼容性回归 |
| `prod` | linux/amd64 | 外部 PanWeiDB | 无（`PANWEIDB_HOST` 指外部实例） | x86 生产交付 |

`prod` 只要求**数据库在外部**：`redis` 与 `weaviate` 仍在栈内，与
`deploy/production/docker-compose.portainer-external-panweidb.yml.tpl` 这份 x86 交付
模板保持一致。要让 redis 也走外部实例，再叠加旧的
`MOGO_USE_EXTERNAL_DB=1`（`docker-compose.external.yml` 会把 mongo / redis /
panweidb 三个容器一起排除出拓扑）。

## 2. 不指定 `--profile` 时的推断

为了让既有部署升级后行为不变，未显式指定时按 `.env` 推断：

| `.env` 状态 | 推断结果 |
|-------------|----------|
| `MOGO_USE_EXTERNAL_DB=1` | `prod` |
| `MOGO_DATA_BACKEND=panweidb`（未开外部模式） | `test` |
| 其余（默认 `MOGO_DATA_BACKEND=mongo`） | `dev` |

推断结果会打印一行 `环境 profile：<名称>（数据库：…）`，不含猜的成分：命令行
`--profile` 与环境变量 `MOGO_PROFILE` 始终优先。

## 3. 冲突与错误

环境与配置互相矛盾时直接中止，不会带着半截配置启动容器：

| 情形 | 提示 | 处理 |
|------|------|------|
| `--profile dev` 且 `MOGO_DATA_BACKEND=panweidb` | `dev profile 固定使用栈内 mongo…` | 改用 `--profile test`，或把后端改回 mongo |
| `--profile dev` 或 `--profile test` 且 `MOGO_USE_EXTERNAL_DB=1` | `…与 MOGO_USE_EXTERNAL_DB=1 冲突` | 外部数据库模式用 `--profile prod` |
| `--profile prod` 但 `PANWEIDB_HOST` 为空 | `prod profile 要求外部 PanWeiDB…` | 在 `.env` 填外部实例地址 |
| `--profile prod` 但 `PANWEIDB_HOST` 仍是 `panweidb`/`mongo`/`redis` | `…仍是栈内服务名` | 改成外部实例地址 |
| profile 名不认识 | `未知环境 profile「…」` | 只能是 `dev` / `test` / `prod` |

## 4. 架构（platform）

架构随 profile 走：`dev`/`test` 目标是 `linux/arm64`，`prod` 目标是 `linux/amd64`。
**架构在启动前就必须是明确的**，CLI 不做静默降级：

| 情形 | 行为 |
|------|------|
| 显式给了 `MOGO_PLATFORM`（环境变量或 `.env`） | 原样使用，CLI 不改写 |
| 没给，且宿主架构 == profile 目标 | 导出 `MOGO_PLATFORM=<目标>` |
| 没给，且宿主架构 != profile 目标 | **中止启动**（退出码 2），并给出两种写法 |

例如在 arm64 开发机上跑 `./mogo --profile prod up` 会被拦下，提示二选一：

```bash
# 真实 x86 交付（arm64 机器上会走模拟，慢但架构对）
MOGO_PLATFORM=linux/amd64 ./mogo --profile prod up

# 在 arm64 上演练 prod 拓扑（外部 PanWeiDB），架构按宿主
MOGO_PLATFORM=linux/arm64 ./mogo --profile prod up
```

之所以不"默认退回宿主架构"，是因为那样得到的是「prod 拓扑 + arm64 镜像」的混合体：
既不是真正的 x86 交付，也不像演练，而且换一台机器结果就变。要哪一种，启动前写清楚。

「架构先写明」只对**会创建或拉取容器**的命令生效（`up` / `build` / `update` /
`restart` / `deploy` / `canary` / `failover` / `restore`）。`down`、`status`、`logs`
这类命令不校验架构 —— 收拾现场、看状态恰恰是架构不符时最需要它们能跑的时候。

stack 服务用 `platform: ${MOGO_PLATFORM:-}` 承接这个值；变量为空时该键整体消失，
所以不用 CLI 直接 `docker compose --profile dev up -d` 时仍是宿主原生架构（与引入
profile 之前一致），此时架构由 compose 自己决定，不经过本文的校验。

跨架构构建（如 arm64 上 `MOGO_PLATFORM=linux/amd64 ./mogo up --build`）会走
binfmt 模拟，速度明显下降，但产物架构与声明一致。

## 5. 实现方式

### 5.1 profile 挂在数据库服务上

```yaml
# docker-compose.yml
mongo:
  profiles: [dev]
panweidb:
  profiles: [panweidb, test]
```

应用服务**不带** profile。原因是 Compose 只能「按 profile 启用服务」，不能「按
profile 禁用服务」；只给数据库服务打 profile，就能做到 `--profile dev` 只多拉起
mongo、`--profile test` 只多拉起 panweidb、`--profile prod` 一个数据库都不拉起，
而应用服务在三个环境下都照常启动。

代价是应用服务对未启用服务的依赖必须写 `required: false`，否则 compose 会直接报
`service ... depends on undefined service ...`，整个文件解析失败：

```yaml
depends_on:
  mongo:
    condition: service_healthy
    required: false   # mongo 只在 dev 环境下存在
```

`panweidb` 的 `required: false` 早就有了（它本来就挂在 profile 上），本轮给
chat-api / admin-api / document-api / document-worker / mongo-backup 对 `mongo`
的依赖、以及 document-api / document-worker 对 `redis` 的依赖补齐了同样的写法。

### 5.2 CLI 侧

- `deploy/cli/env-profiles.sh`：profile 归一化、推断、冲突校验、平台导出
  （`mogo_apply_profile`）。
- `mogo`：任意位置解析 `--profile`，分发命令前调用 `mogo_apply_profile`；
  `help` 这类不碰 compose 的命令只导出不校验，避免环境不全时连帮助都看不到。
- profile 名会并进 `COMPOSE_PROFILES`（去重、保留用户已有的 `ha` / `pool` /
  `observability` / `canary` 等 profile），因此可以与池化、HA、可观测性组合使用：

  ```bash
  ./mogo --profile test up    # 等价于 COMPOSE_PROFILES=test docker compose up -d
  COMPOSE_PROFILES=test,pool ./mogo up
  ```

### 5.3 切换环境与 `down`

`docker compose down` 只收拾**当前启用 profile** 的服务：实测 v5.5.0 下不带
`--profile dev` 的 `down` 会留下 dev 环境起的 `mongo` 容器，还会让
`Network ... Resource is still in use` 跟着报一串。所以 `./mogo down` 会先把
`dev` / `test` / `prod` 三个 profile 一起并进 `COMPOSE_PROFILES`，一次把任何
环境下起的数据库容器都停干净：

```bash
./mogo --profile dev up -d      # 起 mongo
./mogo --profile test up -d     # 切到 panweidb 拓扑
./mogo down                     # 两个数据库容器都会停掉，不留孤儿
```

`up` / `restart` 不做这个放大：它们仍只按当前 profile 生效，避免在 test 环境里
顺手把 dev 的 mongo 拉起来。`down -v` 会连同这些容器对应的卷一起删除（仍要输入
`MOGO` 确认），跨环境切换后执行等同于「清空本项目所有数据卷」。

### 5.4 `dev.sh`（宿主原生开发流程）

`./dev.sh` 不再独立于 profile：它 source 同一份 `deploy/cli/env-profiles.sh`，用同一套
推断、校验和提示，只是**不推导容器架构**（它起的是宿主进程：uvicorn / vite / celery）。

```bash
./dev.sh                    # 与 ./mogo 相同规则推断
./dev.sh --profile dev      # 显式指定（也支持 --profile=test、MOGO_PROFILE=test）
```

- 冲突照旧中止（例如 `--profile dev` 但 `.env` 里 `MOGO_DATA_BACKEND=panweidb`）。
- `dev` / `test` 下若栈内对应的数据库容器没起，只打印一行提示和确切命令
  （`docker compose --profile dev up -d mongo`），不会替用户动现成的栈。
- 宿主进程连哪个库仍由 `.env` 决定（`MOGO_MONGODB_URI` / `PANWEIDB_*`），profile 只负责
  「意图与校验」，不改写连接串 —— 避免出现「profile 说 mongo、进程连 panweidb」的假象。

## 6. 与旧开关的关系

| 开关 | 现状 |
|------|------|
| `MOGO_DATA_BACKEND` | 仍有效，用来表达「意图」；带 `--profile dev/test/prod` 时由 profile 统一改写（dev→mongo，test/prod→panweidb） |
| `--profile panweidb` | 仍有效（`deploy/cli/images.sh` 会按后端自动附加），`panweidb` 与 `test` 是同一组 |
| `MOGO_USE_EXTERNAL_DB=1` | 仍有效，语义是「三个数据库容器都不在栈内」；推断为 `prod` |
| `deploy/production/` x86 模板 | 不变：显式 `platform: linux/amd64` + 外部 panweidb，与 `--profile prod` 语义一致 |

### 6.1 profile 只有一个投递通道：`COMPOSE_PROFILES`

compose 命令行上的 `--profile` **覆盖** `COMPOSE_PROFILES`，而不是与之取并集（docker
compose 5.5.0 实测）：

```bash
# A：只靠环境变量 → mongo 被正常删除
COMPOSE_PROFILES=dev,test,prod docker compose -p probe -f docker-compose.yml down
# B：环境变量 + 命令行 --profile panweidb → mongo 留在原地，网络报 Resource is still in use
COMPOSE_PROFILES=dev,test,prod docker compose -p probe -f docker-compose.yml --profile panweidb down
# C：两个都走命令行 → mongo 被正常删除
docker compose -p probe -f docker-compose.yml --profile dev --profile panweidb down
```

因此 `deploy/cli/images.sh` 里原本的 `compose_args+=(--profile panweidb)` 会让
env-profiles.sh 导出的 `dev/test/prod` 全部失效，`./mogo down` 便漏掉切环境前那个
环境的数据库容器。现在统一走 `mogo_enable_compose_profile panweidb`（并入
`COMPOSE_PROFILES`），B 那种混合投递不再出现。

## 7. 验证

```bash
# 三个环境各自会启动哪些服务（dev 应有 mongo、test 应有 panweidb、prod 两个都没有）
docker compose --profile dev  config --services
docker compose --profile test config --services
docker compose --profile prod config --services

# 架构是否按 profile 落下去
MOGO_PLATFORM=linux/amd64 docker compose --profile prod config | grep -c 'platform: linux/amd64'

# 架构必须显式：arm64 上不给 MOGO_PLATFORM 跑 prod 应当被拒绝（退出码 2）
./mogo --profile prod status >/dev/null; echo "expected 2, got $?"
MOGO_PLATFORM=linux/arm64 ./mogo --profile prod status   # 演练：通过

# CLI 侧冲突与语言
./mogo --lang zh-CN --profile bogus status     # 未知 profile：退出码 2
./mogo --lang zh-CN --profile dev status       # 与 MOGO_DATA_BACKEND 冲突：退出码 2

# 部署侧静态测试（会解析 docker-compose.yml）
python3 -m pytest deploy/tests -q
```

## 8. 参考

- [docker-compose.yml](../docker-compose.yml)：profile 与 `required: false` 的权威定义
- [PanWeiDB 接入](panweidb-compose-integration.md)
- [Docker 部署](docker-deployment.md)
- [环境差异与影响评估](environment-differences.md)：跨环境配置项差异（本文只讲拓扑与数据库选择）
