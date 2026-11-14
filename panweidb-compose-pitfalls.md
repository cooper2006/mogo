# PanWeiDB 容器化踩坑清单（2026-10-22）

把 PanWeiDB 3.2.0（openGauss 内核）从手工容器搬进 docker compose 时实测踩到的坑。
每条都给出**症状 → 根因 → 修复 → 验证**，可直接复用。
完整方案见 [panweidb-compose-integration.md](panweidb-compose-integration.md)。

---

## 1. compose 报 `depends on undefined service`

**症状**：`docker compose up` 直接失败，连 `config` 都解析不了：

```
service "chat-api" depends on undefined service "panweidb": invalid compose project
```

**根因**：`depends_on` 指向了挂在**未启用 profile** 上的服务。compose 的服务定义
与 profile 过滤是两回事，但 `depends_on` 的解析要求目标服务在当前 profile 集合里存在。

**修复**：加 `required: false`（compose ≥ 2.20）：

```yaml
depends_on:
  panweidb:
    condition: service_healthy
    required: false
```

**验证**：`docker compose config -q`（不带 profile）与 `docker compose --profile X config -q`
都通过；带 profile 启动时应用确实等到 `panweidb` healthy 才起（启动日志里能看到
`Container mogo-panweidb-1 Healthy` 出现在 `chat-api` 启动之前）。

---

## 2. compose 不会自动加载 `docker-compose.<profile>.yml`

**症状**：仓库注释写着"profile 激活时会自动加载 `docker-compose.pool.yml`"，但
`docker compose --profile pool config` 显示覆盖**没有生效**。

**根因**：该 include-by-profile 行为在 **compose v5.5.0**（本机实测版本）不成立。
实测：`--profile pool config` 里 `chat-api.DSH_RUNTIME_HOST_URL` 仍是主文件的
`http://dsh-runtime-host:8101`（pool 覆盖文件给的是 `...-lb:8101`），`depends_on`
也没有 `dsh-runtime-host-lb`。

**修复**：不要依赖自动包含，**由调用方显式传多个 `-f`**：

```bash
docker compose -f docker-compose.yml -f docker-compose.pool.yml --profile pool up -d
```

**验证**：`docker compose --profile pool config --format json | jq .services['chat-api'].environment.DSH_RUNTIME_HOST_URL`
应返回 `http://dsh-runtime-host-lb:8101`。

> 备注：这是本轮**顺带发现的既有问题**，不在本轮改动范围内。`mogo` CLI 目前也没有
> `--profile pool` 的用法（`deploy/cli/images.sh` 的 `mogo_compose()` 只拼一个 `-f`）。

---

## 3. `internal` 网络上发布的端口，宿主侧连不上

**症状**：容器在 `mogo_backend`（`internal: true`）上，`ports: - "5432:5432"` 生效了
（`docker ps` 显示 `0.0.0.0:5432->5432/tcp`），但宿主 `nc -z 127.0.0.1 5432` 失败。

**根因**：internal 网络没有对外网关，Docker 的端口转发（userland proxy / iptables）
把流量交给网桥，而 internal 网络的路由表把它丢掉。

**修复**：要同时满足「栈内用服务名」和「宿主用 127.0.0.1」，容器得挂**两个**网络：
`public`（让端口发布生效）+ `backend`（让栈内服务用服务名直连）。

**验证**：

```bash
docker network inspect mogo_backend --format '{{.Internal}}'   # true
docker run --rm --network mogo_backend -p 15432:80 alpine sleep 5 &
nc -z -w2 127.0.0.1 15432   # → 失败（internal 上发布端口宿主不可达）
docker run --rm --network mogo_public -p 15433:80 nginx & 
nc -z -w2 127.0.0.1 15433   # → 成功
```

仓库里 `scripts/pg/dev-forward/` 就是为 internal 网络准备的转发容器方案。

---

## 4. `gs_ctl` 拒绝以 root 运行

**症状**：

```
[gs_ctl]:  cannot be run as root
Please log in (using, e.g., "su") as the (unprivileged) user that will own the server process.
```

**根因**：PID 1（容器 entrypoint）是 root，但数据库必须以 `omm` 运行（`gs_initdb`
也拒绝 root）。

**衍生坑（本轮真实踩到）**：用 `gs_ctl status` 判断"库是否在跑"，在 root 下**恒返回
失败** → `stop_db` 认为库没开、直接跳过关库 → 容器被 docker SIGKILL → 卷里留下
`postmaster.pid`，下次启动要回放 WAL。

**修复**：
- 所有 `gs_ctl` / `gsql` 调用用 `su omm -c`（**非 login shell**，login shell 会重置
  PATH 导致找不到二进制）；
- 判断"库是否在跑"改用 **`postmaster.pid` 是否存在**，而不是 `gs_ctl status`；
- 停止时 `gs_ctl stop -m fast` 后**等 pid 文件消失**再让容器退出。

**验证**：

```bash
docker compose stop panweidb
docker run --rm -v mogo_panweidb-storage:/v --entrypoint bash panweidb:3.2.0 \
  -c 'ls /v/data/postmaster.pid 2>/dev/null && echo REMAINS || echo CLEAN'
# → CLEAN
```

---

## 5. root 身份 `sed -i` 会改掉配置文件属主

**症状**：`postgresql.conf` 原本是 `omm:dbgrp` 0600，entrypoint 以 root 跑了一次
`sed -i` 之后变成 root 属主（模式 0644）。

**根因**：`sed -i` 是「写新文件 + rename」，**不继承原文件的属主与模式**。

**修复**：对 `postgresql.conf` / `pg_hba.conf` 的写操作一律以 omm 身份执行
（`su omm -c "sed -i ..."`），让它自己在 0700 的数据目录里做原地替换。

**验证**：

```bash
docker exec mogo-panweidb-1 stat -c '%a %U:%G %n' \
  /database/panweidb/data/postgresql.conf /database/panweidb/data/pg_hba.conf
# → 600 omm:dbgrp（两个文件都是）
```

---

## 6. 安装包 glob 从未匹配过

**症状**：全新空卷首次启动，entrypoint 报
`FATAL: 镜像内未找到 /root/PanWeiDB_*_install-openeuler_20.03.tar.gz`。

**根因**：实际包名是
`PanWeiDB_V2.0-S3.2.0_B01-install-openeuler_20.03.tar.gz` —— `B01` 与 `install` 之间
是**连字符**，而 glob 写的是 `B01_install`（下划线）。

`scripts/pg/panweidb_up.sh` 里同款 glob 也有这个错，但它**从未暴露**：那个容器的
`soft/` 一直是 ansible playbook 装好的，"解包"分支从来没被执行过。

**修复**：用宽松 glob `PanWeiDB*install*.tar.gz`，不依赖分隔符与大小写。

**衍生**：外层 tarball 里有两个子包都要解 —— `-64bit.tar.bz2`（主包）和
`-64bit-om.tar.gz`（运维库）。缺 om 包时 `gsql`/`gs_ctl` 报
`libcjson.so.1: cannot open shared object file`。

**验证**：全新空卷启动后 `gsql` 能连、端口监听、账号可登录。

---

## 7. bash 3.2 + `set -u` 下空数组展开报错

**症状**：`./mogo down` 直接失败：

```
./mogo: line 736: compose_down_args[@]: unbound variable
```

**根因**：macOS 自带 bash 3.2 在 `set -u` 下把 `"${empty_array[@]}"` 当作未绑定变量
（bash 4.4+ 才修）。`./mogo down` 不带任何参数时该数组为空。

**修复**：按长度分支展开：

```bash
if [[ "${#compose_down_args[@]}" -gt 0 ]]; then
  mogo_compose down "${compose_down_args[@]}"
else
  mogo_compose down
fi
```

**验证**：`./mogo down` 正常停栈并打印 `MOGO has stopped. Data volumes are preserved.`

---

## 8. 单文件 bind mount 在宿主文件被替换后失效

**症状**：改完 entrypoint 脚本后，容器里 `/usr/local/bin/mogo-panweidb-entrypoint.sh`
变成 `No such file or directory`。

**根因**：bind mount 绑定的是**inode**。编辑器/工具用「写新文件 + rename」替换宿主
文件后，inode 变了，容器仍指着旧 inode（已删除）→ 路径看起来消失。

**修复**：改脚本后重建容器（`docker compose up -d --force-recreate`），或用会原地
写入的编辑方式。排查时先 `docker exec <c> ls -l <挂载路径>` 对比。

---

## 9. `docker commit` 是把可写层数据搬进卷的可行手段

**症状**：`--volumes-from` 拿不到旧容器的数据 —— 旧容器根本没挂卷，数据在可写层。

**根因**：`--volumes-from` 只复制**卷**的挂载，不含容器可写层。

**修复**：

```bash
docker commit panweidb panweidb:snapshot-20261022      # 快照 = 数据源 + 回滚点
docker run --rm -v mogo_panweidb-storage:/newvol \
  --entrypoint bash panweidb:snapshot-20261022 \
  -c 'tar -C /database/panweidb -cpf - . | tar -C /newvol -xpf -'
```

`-p` 保留 `omm:dbgrp` 属主（数据目录 0700，属主错了数据库起不来）。

**验证**：迁移后 `PG_VERSION` 存在、`gs_initdb` 可执行、业务表数量与迁移前一致。

---

## 10. openGauss 拒绝"新口令 = 旧口令"

**症状**：`ALTER ROLE x PASSWORD 'same'` 报
`ERROR: New password should not equal to the old ones.`

**修复**：建账号时「`CREATE ROLE` 失败才 `ALTER`」，不要建完再无条件 ALTER 一遍。

**附带**：`NOTICE: 0 days left before password expired` 是 openGauss 的显示怪癖，
不是真会过期 —— 实测 `password_effect_time = 36500`（约 100 年）、
`rolvaliduntil` 为 NULL。
