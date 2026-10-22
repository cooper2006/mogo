#!/usr/bin/env bash
# panweidb_entrypoint.sh — PanWeiDB 3.2.0 容器入口（compose 化专用）
#
# 为什么需要这个脚本
# ------------------
# 上游镜像 `panweidb:3.2.0` 的自带 entrypoint 只做「导出环境变量 + 起 systemd」，
# 真正的数据库进程**不会随容器启动**：镜像里 `/database/panweidb/{soft,data}` 是
# 空目录，二进制要靠 `/root/run.sh` 里的 ansible playbook 解包安装。之前的用法是
# `docker run --privileged -d --entrypoint bash -c 'tail -f /dev/null'` 让容器空转，
# 再由 `scripts/pg/panweidb_up.sh` 在外部 `gs_ctl start`。那种方式无法纳入 compose
# 的生命周期（`docker compose up/down/restart` 都不会带起数据库，`depends_on:
# service_healthy` 也无从判定），所以这里把它改成一个真正的 PID 1 supervisor：
#
#   1. 首次启动：从镜像内置安装包解包二进制到 $PGHOME（落在卷上，之后跳过）；
#   2. 首次启动：gs_initdb 初始化 $PGDATA + 写 license / gaussdb.version / pg_hba；
#   3. gs_ctl start，并以 10s 周期守活；
#   4. 收到 SIGTERM/SIGINT → gs_ctl stop -m fast 后再退出，保证下次开机是干净关闭
#      （不然卷里会留下 postmaster.pid，只能走崩溃恢复）。
#
# 设计约束（都是实测踩过的点，改动前请先读）
# ------------------------------------------
# * 二进制不在镜像 PATH 里，且 gsql/gs_ctl 依赖 `$PGHOME/lib`（libcjson.so.1 等），
#   所以每条命令都要带上 PGHOME/LD_LIBRARY_PATH，不能指望 login shell。
# * 数据库进程必须以 `omm` 运行（gs_initdb 拒绝 root）。这里用 `su omm -c`（非 login
#   shell），保留本脚本注入的环境；`su - omm`（login）会重置 PATH 导致找不到二进制。
# * pg_hba：本地 `trust` + 远程 `sha256`。PanWeiDB 安全插件禁止「远程 + trust」，
#   写错会在启动时直接 `Forbid remote connection with trust method!`。
# * `sql_compatibility` 由 gs_initdb 的 `--dbcompatibility` 决定，实例级固定为 `A`
#   （Oracle 模式，`pg_settings.context = internal` 不可改）。A 模式禁用了部分
#   JSONB 函数，兼容层的规避手法见 services/*/app/core/pg_compat.py 与
#   docs/mongo-to-panweidb-migration-plan.md 第 5 节。
# * 数据落在命名卷 `panweidb-storage`（挂 `/database/panweidb`）而不是容器可写层——
#   旧用法的数据在可写层里，`docker rm` 一次就全丢，这是本次 compose 化最主要的修复。

set -Eeuo pipefail

PGHOME="${PGHOME:-/database/panweidb/soft}"
PGDATA="${PGDATA:-/database/panweidb/data}"
PGROOT="${PGROOT:-/database/panweidb}"
PANWEIDB_PORT="${PANWEIDB_PORT:-5432}"
PANWEIDB_NODE_NAME="${PANWEIDB_NODE_NAME:-pdb}"
# initdb 的 locale / 编码沿用 2026-10-15 验证过的配方：卷一旦被别的 locale 初始化过，
# 后续 initdb 不会重跑（幂等靠 PG_VERSION 判定），所以这里的默认值只影响全新部署。
PANWEIDB_DBCOMPATIBILITY="${PANWEIDB_DBCOMPATIBILITY:-A}"
PANWEIDB_ENCODING="${PANWEIDB_ENCODING:-UTF8}"
PANWEIDB_LOCALE="${PANWEIDB_LOCALE:-en_US.UTF8}"
# 应用账号（首次初始化时创建；已有数据卷不改动，避免覆盖运维手工重置过的账号）。
PANWEIDB_ADMIN_PASSWORD="${PANWEIDB_ADMIN_PASSWORD:-}"
PANWEIDB_USER="${PANWEIDB_USER:-}"
PANWEIDB_PASSWORD="${PANWEIDB_PASSWORD:-}"
PANWEIDB_DB="${PANWEIDB_DB:-mogo_dev}"
PANWEIDB_SCHEMA="${PANWEIDB_SCHEMA:-mogo_dev}"

export PGHOME GAUSSHOME="$PGHOME" PGDATA
export LD_LIBRARY_PATH="$PGHOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="$PGHOME/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export LANG="$PANWEIDB_LOCALE"

log() { echo "[panweidb-entrypoint] $*" >&2; }

# 以 omm 身份执行（非 login shell，保留上面导出的环境）。
as_omm() { su omm -c "$1"; }

initialized() { [ -f "$PGDATA/PG_VERSION" ]; }

binaries_ready() { [ -x "$PGHOME/bin/gs_initdb" ] && [ -x "$PGHOME/bin/gs_ctl" ]; }

db_running() { as_omm "gs_ctl status -D '$PGDATA'" >/dev/null 2>&1; }

# ---------- 1. 二进制 ----------
unpack_binaries() {
  if binaries_ready; then
    log "二进制已就绪（$PGHOME/bin），跳过解包。"
    return 0
  fi
  local tarball
  # 实测文件名是 `PanWeiDB_V2.0-S3.2.0_B01-install-openeuler_20.03.tar.gz`
  # （`B01-install` 是**连字符**）。scripts/pg/panweidb_up.sh 里那条
  # `PanWeiDB_*_install-openeuler_20.03.tar.gz` 的下划线 glob 从来没匹配上过——
  # 它服务的容器一直是 ansible 装好的，这条分支从未执行，所以这个错没被发现过。
  # 这里用宽松 glob，不再依赖大小写与分隔符。
  tarball="$(ls /root/PanWeiDB*install*.tar.gz 2>/dev/null | head -1 || true)"
  if [ -z "$tarball" ]; then
    log "FATAL: 镜像内未找到 /root/PanWeiDB*install*.tar.gz，无法解包二进制。"
    exit 1
  fi
  log "首次启动：解包 $tarball 到 $PGHOME ..."
  # 外层 tarball 里是若干个子包：`-64bit.tar.bz2` 是主包（bin/lib），`-om.tar.gz`
  # 是运维/监控库。缺 om 包时 gsql/gs_ctl 会报
  # `libcjson.so.1: cannot open shared object file`，所以两个都要解。
  # 属主必须是 omm:dbgrp，否则 initdb 直接拒绝。
  tar -xzf "$tarball" -C "$PGHOME"
  local main_pkg om_pkg
  main_pkg="$(ls "$PGHOME"/PanWeiDB*-64bit.tar.bz2 2>/dev/null | head -1 || true)"
  om_pkg="$(ls "$PGHOME"/PanWeiDB*-64bit-om.tar.gz 2>/dev/null | head -1 || true)"
  [ -n "$main_pkg" ] || { log "FATAL: 解包后找不到主包 *-64bit.tar.bz2。"; exit 1; }
  [ -n "$om_pkg" ] || { log "FATAL: 解包后找不到 om 包 *-64bit-om.tar.gz。"; exit 1; }
  tar -xjf "$main_pkg" -C "$PGHOME"
  tar -xzf "$om_pkg" -C "$PGHOME"
  chown -R omm:dbgrp "$PGROOT"
  if ! binaries_ready; then
    log "FATAL: 解包后仍缺 gs_initdb / gs_ctl，安装包结构与预期不符。"
    exit 1
  fi
  log "解包完成。"
}

# ---------- 2. 静态文件（license / 版本 / 日志目录） ----------
write_static_files() {
  # license.lic 在 /etc（不在数据卷里），每次开机重写，内容固定；
  # DEVELOPMENT 授权到期日见 licenseExpireDate。
  mkdir -p /etc/panweidb/license
  cat > /etc/panweidb/license/license.lic <<'LIC'
licenseType: DEVELOPMENT
licenseVersion: "1.0"
licenseKey: DEMO_LICENSE_KEY
licenseOwner: PanWeiDB
licenseIssueDate: "2026-10-15"
licenseExpireDate: "2027-10-15"
licenseNodes: 1
licenseFeatures: "*"
expireTimeStrategy: HARD_LIMIT
LIC
  chmod 0644 /etc/panweidb/license/license.lic

  cat > "$PGDATA/gaussdb.version" <<'VER'
PanWeiDB_V2.0-S3.2.0_B01
92.999
86db355
VER
  chown omm:dbgrp "$PGDATA/gaussdb.version"
  # 0666 是 2026-10-22 在在用实例上实测到的模式（`stat` 显示 666 omm:dbgrp），
  # 这里照抄，避免把既有实例的模式改成更严的 644 后出现「新容器起不来、老容器能起」
  # 的差异。没有实测证据表明 644 会失败，所以这只是对齐现状，不是修复。
  chmod 0666 "$PGDATA/gaussdb.version"

  mkdir -p "$PGDATA/pg_log" "$PGROOT/log" "$PGROOT/corefile" "$PGROOT/cm" "$PGROOT/pg_audit"
  # 只 chown 顶层与日志目录：`chown -R $PGROOT` 会在每次开机遍历整个数据目录
  # （数 GB、数万 inode），而这些文件的属主本来就是 omm。全新卷由 Docker 按镜像
  # 里的属主（omm:dbgrp）初始化，同样不需要遍历。
  chown omm:dbgrp "$PGROOT" "$PGROOT/log" "$PGROOT/corefile" "$PGROOT/cm" "$PGROOT/pg_audit" "$PGDATA" "$PGDATA/pg_log"
  chmod 0700 "$PGDATA"
}

# ---------- 3. 初始化 ----------
# postgresql.conf / pg_hba.conf 由 omm 拥有且是 0600。root 直接 `sed -i` / `cat >`
# 会留下 root 属主、0644 的新文件（sed -i 是「新建+改名」，不继承原模式）：权限被
# 放宽，而且 openGauss 对配置文件属主有校验。**所有对这两个文件的写操作都以 omm
# 身份执行**，让它自己在 0700 的数据目录里做原地替换。
configure_postgresql_conf() {
  as_omm "sed -i \"s|^\#*listen_addresses = .*|listen_addresses = '*'|\" '$PGDATA/postgresql.conf'"
  # 把监听端口钉到 PANWEIDB_PORT，保证与 compose 的服务端口/健康检查一致。
  if as_omm "grep -qE '^#?port = ' '$PGDATA/postgresql.conf'"; then
    as_omm "sed -i \"s|^\#*port = .*|port = ${PANWEIDB_PORT}|\" '$PGDATA/postgresql.conf'"
  else
    as_omm "echo 'port = ${PANWEIDB_PORT}' >> '$PGDATA/postgresql.conf'"
  fi
}

write_pg_hba() {
  log "写入 pg_hba.conf（本地 trust、远程 sha256）..."
  # PanWeiDB 安全插件禁止「远程 + trust」，写成远程 trust 会在启动时报
  # `Forbid remote connection with trust method!`（SQLSTATE 28000/28P01）。
  as_omm "cat > '$PGDATA/pg_hba.conf'" <<'HBA'
# TYPE  DATABASE        USER            ADDRESS                 METHOD
local   all             all                                     trust
host    all             all             127.0.0.1/32            trust
host    all             all             ::1/128                 trust
host    all             all             0.0.0.0/0               sha256
host    all             all             ::0/0                   sha256
HBA
  as_omm "chmod 0600 '$PGDATA/pg_hba.conf'"
}

init_data() {
  log "gs_initdb 初始化 $PGDATA（nodename=$PANWEIDB_NODE_NAME, compatibility=$PANWEIDB_DBCOMPATIBILITY）..."
  # 全新卷上该路径可能还不存在；属主必须是 omm（gs_initdb 拒绝 root，也拒绝别人写的目录）。
  mkdir -p "$PGDATA"
  chown omm:dbgrp "$PGDATA"
  chmod 0700 "$PGDATA"
  as_omm "gs_initdb --nodename='$PANWEIDB_NODE_NAME' \
    --dbcompatibility='$PANWEIDB_DBCOMPATIBILITY' \
    --encoding='$PANWEIDB_ENCODING' \
    --lc-collate='$PANWEIDB_LOCALE' --lc-ctype='$PANWEIDB_LOCALE' \
    '$PGDATA'" 2>&1 | tail -20 >&2 || {
      log "FATAL: gs_initdb 失败（见上方输出）。"
      exit 1
    }
}

# ---------- 4. 起停 ----------
start_db() {
  if db_running; then
    log "数据库已在运行。"
    return 0
  fi
  log "gs_ctl start ..."
  # 上一次容器被 SIGKILL（或宿主机断电）时卷里会残留 postmaster.pid。本容器的
  # supervisor 保证单实例，且 PID 1 退出时内核会回收所有后端进程，所以「容器内没有
  # panweidb 进程」就等于「这个 pid 属于上一个已经死掉的容器」。
  # 不能只用 `kill -0 $pid` 判断：pid 是宿主/别的 namespace 的数字，容器内可能恰好
  # 有个无关进程占着同号，导致误判为「还在跑」而拒绝清理，gs_ctl 随即拒启。
  if [ -f "$PGDATA/postmaster.pid" ]; then
    local pid
    pid="$(head -1 "$PGDATA/postmaster.pid" 2>/dev/null || true)"
    if [ -n "$pid" ] && ! pgrep -f "panweidb.*-D *$PGDATA" >/dev/null 2>&1; then
      log "清理残留 postmaster.pid（pid=$pid，本容器内无对应进程）。"
      rm -f "$PGDATA/postmaster.pid"
    fi
  fi
  # `-w` 等 postmaster 就绪再返回；日志固定写 pg_log/logfile（compose 排障与
  # start_db 超时时 tail 的就是它）。是否已在运行由上面的 db_running() 判定，
  # 不用 `gs_ctl query`——那是备库 LSN 查询，在单机拓扑下恒失败，拿它当守卫等于
  # 靠「失败」凑出正确分支，语义是反的。
  as_omm "gs_ctl start -D '$PGDATA' -l '$PGDATA/pg_log/logfile' -w" \
    || log "gs_ctl start 返回非零，继续等待端口就绪（崩溃恢复时属正常）。"
  local i
  for i in $(seq 1 60); do
    if tcp_ready; then
      log "数据库已就绪（监听 $PANWEIDB_PORT）。"
      return 0
    fi
    sleep 2
  done
  log "FATAL: 60x2s 内端口未就绪，最后 50 行日志："
  tail -50 "$PGDATA/pg_log/logfile" >&2 2>/dev/null || true
  exit 1
}

tcp_ready() {
  python3 -c '
import os, socket, sys
port = int(os.environ.get("PANWEIDB_PORT", "5432"))
try:
    s = socket.create_connection(("127.0.0.1", port), 2)
    s.close()
except Exception:
    sys.exit(1)
' 2>/dev/null
}

stop_db() {
  # 以 postmaster.pid 是否存在作为「库还开着」的判据，而不是依赖 `gs_ctl status`：
  # status 需要 omm 身份 + 一整套 PGHOME 环境（gs_ctl 明确拒绝 root），任何一环出问题
  # 都会让它返回「没在跑」，于是跳过关库、容器直接退出，卷里留下 crash 状态。
  # pid 文件由 postmaster 自己维护，是更可靠的信号。
  if [ ! -f "$PGDATA/postmaster.pid" ]; then
    log "未发现 postmaster.pid，数据库已关闭，无需处理。"
    return 0
  fi
  log "收到停止信号，gs_ctl stop -m fast ..."
  as_omm "gs_ctl stop -D '$PGDATA' -m fast" 2>&1 || log "WARN: gs_ctl stop 返回非零。"
  # 必须等 pid 文件真的消失再让容器退出：否则 docker 会在关库中途发 SIGKILL，
  # 下次启动就要回放 WAL（fast 关闭通常 1~5s，长事务时更久，由 stop_grace_period 兜底）。
  local i
  for i in $(seq 1 80); do
    [ -f "$PGDATA/postmaster.pid" ] || { log "数据库已干净关闭。"; return 0; }
    sleep 1
  done
  log "WARN: 80s 内未确认关闭完成，交由 docker 收尾。"
}

provision_app() {
  # 只在全新初始化时执行；已有数据卷一律不动账号（2026-10-15 那次手工重置以卷内状态为准）。
  if [ -z "$PANWEIDB_USER" ] || [ -z "$PANWEIDB_PASSWORD" ]; then
    log "未设 PANWEIDB_USER/PANWEIDB_PASSWORD，跳过建库建账号。"
    return 0
  fi
  log "创建应用账号 $PANWEIDB_USER / 库 $PANWEIDB_DB / schema $PANWEIDB_SCHEMA ..."
  # CREATE 失败才补 ALTER：openGauss 的口令策略会拒绝「新口令 = 旧口令」
  # （`New password should not equal to the old ones`），所以不能对新建账号再
  # 无条件 ALTER 一遍同一个口令，否则每次全新部署都会刷一条 ERROR。
  if ! gsql_admin "CREATE ROLE $PANWEIDB_USER LOGIN PASSWORD '$PANWEIDB_PASSWORD';"; then
    gsql_admin "ALTER ROLE $PANWEIDB_USER PASSWORD '$PANWEIDB_PASSWORD';" || true
  fi
  gsql_admin "CREATE DATABASE $PANWEIDB_DB;" || true
  gsql_admin "GRANT ALL PRIVILEGES ON DATABASE $PANWEIDB_DB TO $PANWEIDB_USER;" || true
  gsql_admin "ALTER ROLE $PANWEIDB_USER SET search_path = $PANWEIDB_SCHEMA;" || true
  as_omm "gsql -p '$PANWEIDB_PORT' -d '$PANWEIDB_DB' -t -A -c \"CREATE SCHEMA IF NOT EXISTS $PANWEIDB_SCHEMA AUTHORIZATION $PANWEIDB_USER;\"" || true
}

gsql_admin() {
  # 本地 socket 走 pg_hba 的 `local ... trust`，不需要口令；显式带 -p 是为了
  # PANWEIDB_PORT 改成非 5432 时仍能连对（gsql 默认端口取自编译期，不读 PGPORT 之外）。
  as_omm "gsql -p '$PANWEIDB_PORT' -d postgres -t -A -c \"$1\"" 2>&1 | tail -3 >&2 || return 1
}

set_admin_password() {
  # gs_initdb 后 omm 必须有口令，否则后续 ALTER ROLE 会被安全插件拒绝（实测）。
  # 口令只在全新初始化时写入；日常运行靠 local trust 维护，compose 不需要知道它。
  [ -n "$PANWEIDB_ADMIN_PASSWORD" ] || { log "未设 PANWEIDB_ADMIN_PASSWORD，跳过 omm 口令设置（本地 trust 仍可维护）。"; return 0; }
  log "设置 omm 超级用户口令 ..."
  gsql_admin "ALTER ROLE omm PASSWORD '$PANWEIDB_ADMIN_PASSWORD';" || log "WARN: omm 口令设置失败。"
}

shutdown_handler() {
  trap - TERM INT
  stop_db
  exit 0
}

main() {
  # 提前注册：解包/initdb 是最慢的阶段，若这期间收到 docker 的停止信号而 trap 还没装，
  # 默认行为是直接杀掉 PID 1，把卷留在半途状态。
  trap shutdown_handler TERM INT

  unpack_binaries

  local fresh=false
  if initialized; then
    log "数据卷已初始化（$PGDATA/PG_VERSION 存在）。"
  else
    fresh=true
    log "数据卷为空，执行完整初始化流程。"
    init_data
  fi

  # listen_addresses / port 每次都钉：它们必须和 compose 发布端口、健康检查探针
  # 对齐，且只改这两行，不动调优参数。
  configure_postgresql_conf
  if [ "$fresh" = true ]; then
    # 已有数据卷**不重写** pg_hba：卷里带的就是运维在用的那份（本地 trust / 远程
    # sha256），手工加过的白名单不该被启动流程抹掉。
    write_pg_hba
  fi
  write_static_files
  start_db

  if [ "$fresh" = true ]; then
    set_admin_password
    provision_app
  fi

  # 守活循环：`sleep & wait` 的写法让信号能立刻打断等待（bash 在 wait 中收到 trap
  # 会中断该 wait）。trap 已在 main 开头注册，这里不重复。
  # 数据库进程意外退出时让容器一起退出，交给 restart 策略处理，
  # 避免 compose 显示「容器健康但库已经死了」。
  while true; do
    if ! tcp_ready; then
      log "FATAL: 数据库端口不可达，容器退出以触发 restart。"
      exit 1
    fi
    sleep 10 &
    wait $! || true
  done
}

main "$@"
