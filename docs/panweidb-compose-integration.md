# PanWeiDB 容器化（compose 一体化管理）

PanWeiDB 3.2.0（openGauss 内核）从「手工 `docker run` 的独立容器」搬进本项目的
docker compose，与其余服务一起由 `./mogo up` / `docker compose up -d` 管理。

- 落地时间：2026-10-22
- 涉及文件：`docker-compose.yml`、`deploy/panweidb/entrypoint.sh`、`deploy/cli/images.sh`、
  `deploy/cli/backup.sh`、`deploy/cli/i18n.sh`、`mogo`、`scripts/check_open_source_hygiene.py`

---

## 1. 改造前：手工容器，数据在可写层

原来的跑法（`scripts/pg/panweidb_up.sh` 复刻自 2026-10-15 的会话）：

```bash
docker run --privileged -d --name panweidb -p 5432:5432 \
  --entrypoint bash panweidb:3.2.0 -c 'tail -f /dev/null'
```

问题：

| 问题 | 后果 |
|---|---|
| PID 1 是 `tail -f /dev/null`，数据库不随容器启动 | 容器起来 ≠ 库在跑；每次都要人再执行一次 `gs_ctl start` |
| 数据在容器**可写层**，没有卷 | `docker rm` 一次，1.1G 数据 + 1.6G 软件全丢；无备份/恢复路径 |
| 容器不在 compose 项目内 | `./mogo up/down/restart/status` 看不到它；`depends_on` 无法等它就绪 |
| 库自己监听的 5432 与栈内服务网段无关 | 应用只能走 `host.docker.internal` 绕宿主回环 |

实测确认（改造前）：`docker inspect panweidb` 显示 `HostConfig.Binds = null`、
`docker run --rm ... panweidb:3.2.0` 里 `/database/panweidb/{soft,data}` 都是**空目录**
（镜像只带 `/root/PanWeiDB_V2.0-S3.2.0_B01-install-openeuler_20.03.tar.gz` 安装包，
二进制和数据都是 ansible playbook 在容器里装出来的）。

## 2. 改造后

```
docker-compose.yml
  panweidb:                       # profile: panweidb（默认不启动）
    image: panweidb:3.2.0         # pull_policy: never（本地镜像，不发布 registry）
    privileged: true              # openGauss 需要，见 §4
    entrypoint: bash /usr/local/bin/mogo-panweidb-entrypoint.sh
    volumes:
      - panweidb-storage:/database/panweidb     # 命名卷：soft/ + data/ 都在这里
      - ./deploy/panweidb/entrypoint.sh:...:ro
    networks: [public, backend]
    ports: ["${MOGO_PANWEIDB_BIND:-127.0.0.1}:${MOGO_PANWEIDB_PORT:-5432}:5432"]
    healthcheck: TCP 5432 探针
```

### 2.1 entrypoint（PID 1 supervisor）

`deploy/panweidb/entrypoint.sh` 承担原来「人肉执行」的整套流程：

1. 首次启动：从 `/root/PanWeiDB*install*.tar.gz` 解包二进制到 `$PGHOME`（卷上，之后跳过）；
2. 首次启动：`gs_initdb` 初始化 `$PGDATA`（`--dbcompatibility=A`、`--nodename=pdb`）；
3. 写 `pg_hba.conf`（本地 `trust` / 远程 `sha256`）、`license.lic`、`gaussdb.version`；
4. `gs_ctl start`，探活端口；
5. 守活循环：库意外退出则容器退出，交给 `restart: unless-stopped`；
6. 收到 `SIGTERM` → `gs_ctl stop -m fast`，**等 `postmaster.pid` 消失**再退出。

第 6 点是关键：容器必须自己干净关库，否则下次启动要回放 WAL。

### 2.2 开关：profile + 环境变量

`panweidb` 挂在 `panweidb` profile 上，**默认不启动**。原因：镜像只在本地
（`base-images/images/arm64/panweidb_3.2.0.tar`，openEuler/arm64），不发布到任何
registry；而默认数据后端仍是 mongo。

启用方式 —— **一个开关同时管两件事**（`.env` 里 `MOGO_DATA_BACKEND=PanWeiDB`）：

| 开关 | 作用 |
|---|---|
| `MOGO_DATA_BACKEND=panweidb` | 应用连 PanWeiDB（`app/core/config.py` 的 `effective_data_backend`） |
| compose profile `panweidb` | 把数据库容器带进拓扑 |

`deploy/cli/images.sh` 的 `mogo_compose()` 会在后端切到 panweidb 时自动追加
`--profile panweidb`，所以 `./mogo up` 一个命令就够了；`mogo` 还会先检查本地是否有
`panweidb:3.2.0` 镜像（缺镜像时提前失败，而不是让应用卡在 `depends_on` 上）。

> ⚠️ 两个开关必须同时给。只开 profile 不改后端 → 库空转；只改后端不开 profile →
> 应用连不上（`depends_on` 指向未启用的服务会让 compose 直接报
> `service "x" depends on undefined service "panweidb"`）。

`depends_on` 因此写成：

```yaml
panweidb:
  condition: service_healthy
  required: false        # profile 未启用时不阻塞启动
```

## 3. 数据迁移（2026-10-22 实测）

旧数据在容器可写层，迁移步骤：

1. 干净关库：`gs_ctl stop -D /database/panweidb/data -m fast`；
2. `docker commit panweidb panweidb:snapshot-20261022`（快照 = 数据源 + 回滚点）；
3. 从快照镜像 `tar -cpf - . | tar -xpf -` 到命名卷（`-p` 保留 `omm:dbgrp` 属主）；
4. 校验：`PG_VERSION` 存在、`soft/bin/gs_initdb` 可执行、134 张表可读。

`--volumes-from` **不行**：可写层不是卷，`docker run --volumes-from` 看不到它。

回滚点保留在 `panweidb:snapshot-20261022`（2.54GB 数据层）与已停止的旧容器
`panweidb` 里，确认不再需要后再删。

## 4. 已知取舍与坑

### 4.1 `privileged: true`

openGauss/PanWeiDB 需要写 `kernel.sched_*` 等 sysctl、且直接操作大块共享内存，上游
镜像文档即要求 `--privileged`（旧容器也是这么跑的）。这使它成为
`docker-compose.yml` 里**唯一**不做 `cap_drop: ALL` / `read_only` 加固的服务。

- `deploy/tests/test_container_hardening.py` 的 `HARDENED_SERVICES` 不含它，测试通过；
- 它只挂 `backend` + `public` 网络，端口默认只绑 `127.0.0.1`（回环）；
- 需要局域网访问时显式设 `MOGO_PANWEIDB_BIND=0.0.0.0`（库的远程认证是 `sha256`
  口令，且口令在 `.env` 里，绑 `0.0.0.0` 等于把口令暴露在本机网段）。

### 4.2 `backend` 是 internal 网络，宿主不可达

`mogo_backend` 是 `internal: true`：**在它上面发布的端口，宿主侧连不上**（实测
`HOST-PORT-BLOCKED`）。而 `scripts/pg/*.py`、`deploy/tests` 里的宿主工具都按
`127.0.0.1:5432` 连库（见 `scripts/pg/dev-forward/README.md` 记录的同一限制）。

因此 `panweidb` 同时挂 `public` 与 `backend`：`public` 让端口发布生效（宿主可用），
`backend` 让栈内服务用服务名直连（不经宿主回环）。

### 4.3 `gs_ctl` 拒绝以 root 运行

```
[gs_ctl]:  cannot be run as root
```

PID 1（entrypoint）是 root，所以**所有 `gs_ctl` / `gsql` 调用都要 `su omm -c`**。
踩过的坑：最初用 `gs_ctl status` 判断「库是否在跑」，它在 root 下恒返回失败 →
`stop_db` 直接跳过关库 → 容器被 SIGKILL → 卷里留下 `postmaster.pid`。
现在改用 **`postmaster.pid` 是否存在**作为判据，并等它消失再让容器退出。

### 4.4 `sed -i` 必须以 omm 执行

`postgresql.conf` / `pg_hba.conf` 是 `omm:dbgrp` 0600。root 直接 `sed -i` /
`cat >` 会留下 root 属主、0644 的新文件（`sed -i` 是「新建 + 改名」，不继承原模式）：
权限被放宽，且 openGauss 对配置文件属主有校验。entrypoint 里这两个文件的写操作
一律 `su omm` 执行。

### 4.5 安装包文件名

镜像里的包名是 `PanWeiDB_V2.0-S3.2.0_B01-install-openeuler_20.03.tar.gz`
（**连字符** `B01-install`）。`scripts/pg/panweidb_up.sh` 里的
`PanWeiDB_*_install-openeuler_20.03.tar.gz`（下划线）**从未匹配过** —— 它服务的
容器一直是 ansible 装好的，那条分支没被执行过，所以这个错一直没暴露。
entrypoint 用宽松 glob `PanWeiDB*install*.tar.gz`。

子包两个都要解：`-64bit.tar.bz2`（主包）+ `-64bit-om.tar.gz`（运维库），
缺 om 包时 `gsql`/`gs_ctl` 报 `libcjson.so.1: cannot open shared object file`。

### 4.6 首次启动很慢

解包 1.6G + `gs_initdb` 约需 2~4 分钟，故 healthcheck `start_period: 300s`。
实测全新空卷 → 库就绪约 100 秒。

### 4.7 口令策略

openGauss 的 `password_effect_time = 36500`（约 100 年），`rolvaliduntil` 为 NULL，
新建账号不会过期。日志里的 `NOTICE: 0 days left before password expired` 是
openGauss 的显示怪癖，不是真会过期。

另外 openGauss 拒绝「新口令 = 旧口令」（`New password should not equal to the old
ones`），所以 entrypoint 是「`CREATE ROLE` 失败才 `ALTER`」，不对新建账号再
无条件 ALTER 同一个口令。

## 5. 验证记录（2026-10-22 实测）

| 项 | 结果 |
|---|---|
| 旧数据迁移 | 7 个库、134 张表全部可读 |
| 栈内服务名解析 | `panweidb` → 192.168.97.10，TCP 5432 可达 |
| 宿主回环 | `127.0.0.1:5432` 可达（宿主工具照常工作） |
| 应用真实驱动连接 | `psycopg` + `boncuser` + sha256 口令，`current_schema = mogo_dev` |
| 兼容层门面 | 134 集合、`admin_accounts` 3 行、`find_one` 正常 |
| 干净停止 | `gs_ctl stop -m fast` → pid 文件消失 → 无 crash 状态 |
| 幂等重启 | 跳过解包/initdb/provision，数据在 |
| 全新空卷初始化 | 解包 → initdb → 建库建账号 → TCP 登录成功，约 100s |
| 整栈 | 12 个服务全绿，`./mogo up` 一条命令带起数据库 |

## 6. 运维

```bash
# 启停（CLI 会自动带 --profile panweidb，因为 .env 里 MOGO_DATA_BACKEND=PanWeiDB）
./mogo up
./mogo status
./mogo down

# 直接用 compose
docker compose --profile panweidb up -d panweidb
docker compose --profile panweidb logs -f panweidb
docker compose --profile panweidb stop panweidb      # 干净关库
```

备份 / 恢复：`deploy/cli/backup.sh` 把 `panweidb-storage` 列为**可选卷** ——
存在才备份/恢复。这样纯 mongo 部署的 `./mogo backup` 不受影响，而带 panweidb 的
备份会连库一起带走（tar 保留 `omm:dbgrp` 属主，恢复后能直接启动）。

## 7. 相关文件

- `docs/panweidb-compose-pitfalls.md` —— 本次踩坑清单（症状 → 根因 → 修复 → 验证）
- `docs/mongo-to-panweidb-migration-plan.md` —— 迁移方案与 A 模式 JSONB 能力约束
- `specs/027-mongo-to-panweidb-migration/` —— 027 spec
- `scripts/pg/panweidb_up.sh` —— **旧的**宿主机脚本（仍可用于纯手工场景；
  与 compose 二选一，不要同时跑，两者抢宿主 5432）
- `scripts/pg/dev-forward/` —— internal 网络端口不可达时的转发方案
- `deploy/panweidb/entrypoint.sh` —— 本次新增的容器入口
