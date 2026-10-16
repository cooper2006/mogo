#!/usr/bin/env bash
# panweidb_up.sh — PanWeiDB (orbstack 容器) 一键拉起脚本
#
# 用途：
#   - 容器不存在         → 按原会话方式创建容器（--privileged，tail -f /dev/null 常驻）
#   - 容器已停 (Exited)  → docker start
#   - 数据未初始化       → 解包镜像内置安装包 → gs_initdb → 配置 → 建 bonc/boncuser/ihr_hrd
#   - 数据已初始化       → 只确保 gs_ctl start（已运行则直接判定就绪）
#   - 全程幂等：重复执行不会破坏既有数据；除非 --reinit。
#
# 设计要点（复刻 2026-10-15 会话验证过的配方）：
#   - 二进制不在镜像 PATH 里，需从 /root/PanWeiDB_*_install-openeuler_20.03.tar.gz
#     解包到 /database/panweidb/soft，主包 + om 包都要解。
#   - 连接走 0.0.0.0:5432。pg_hba 本地（local + 127）用 trust 方便维护；
#     远程 TCP 必须用 sha256（PanWeiDB 安全插件禁止“远程 + trust”，否则报
#     "Forbid remote connection with trust method!" / SQLSTATE 28000，客户端会收到 28P01）。
#     应用账户 boncuser 的口令已用 sha256 存储（password_encryption_type=1），远程走密码认证即可。
#   - 超级用户 omm 必须在 gs_initdb 后 ALTER ROLE 设口令，否则其后再做操作会被拒。
#   - gsql 不读 PGPASSWORD，脚本用 python 子进程把口令喂到 stdin。
#   - 用 `docker exec -e` 注入环境 + `su omm`（非 login）切换身份，避免 login shell
#     清空 PGHOME/PATH 导致 gsql/gs_ctl 找不到。
#
# 用法：
#   bash scripts/pg/panweidb_up.sh            # 拉起（创建/启动/初始化，按需）
#   bash scripts/pg/panweidb_up.sh --reinit   # 清空 data 目录，从头初始化（数据全丢！）
#   bash scripts/pg/panweidb_up.sh --status   # 只打印状态，不改动
#
# 注意：本脚本操作 orbstack 里的 panweidb 容器，属运维操作；--reinit 会清空数据。

set -euo pipefail

CONTAINER=panweidb
IMAGE=panweidb:3.2.0
HOST_PORT=5432
PGHOME=/database/panweidb/soft
PGDATA=/database/panweidb/data
NODE_NAME=pdb
CLUSTER_NAME=panweidb
OMM_PW='Pw@123456'
APP_DB=bonc
APP_USER=boncuser
APP_PW='1qaz!QAZ'
APP_SCHEMA=ihr_hrd

LICENSE_YAML='licenseType: DEVELOPMENT
licenseVersion: "1.0"
licenseKey: DEMO_LICENSE_KEY
licenseOwner: PanWeiDB
licenseIssueDate: "2026-10-15"
licenseExpireDate: "2027-10-15"
licenseNodes: 1
licenseFeatures: "*"
expireTimeStrategy: HARD_LIMIT'

GAUSSDB_VERSION='PanWeiDB_V2.0-S3.2.0_B01
92.999
86db355'

MODE=up
if [[ "${1:-}" == "--reinit" ]]; then MODE=reinit; fi
if [[ "${1:-}" == "--status" ]]; then MODE=status; fi

# ---------- 工具函数 ----------
need_docker() { command -v docker >/dev/null 2>&1 || { echo "ERROR: 未找到 docker 命令"; exit 1; }; }

docker_exec() { docker exec "$CONTAINER" "$@"; }

# 以 omm 身份在容器内跑命令（非 login shell，保留 docker exec 注入的环境）
omm_exec() {
  docker exec -e PGHOME="$PGHOME" -e GAUSSHOME="$PGHOME" \
    -e PATH="$PGHOME/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    -e LD_LIBRARY_PATH="$PGHOME/lib" \
    -e PGDATA="$PGDATA" -e LANG=en_US.UTF8 \
    "$CONTAINER" su omm -c "$1"
}

# 安全地用 python 把口令喂给 gsql（通过环境变量传参，避免引号地狱；绝对路径避免 PATH 问题）
sql_as() {
  # $1=host $2=user $3=db $4=password $5=sql
  docker exec -e PWHOST="$1" -e PWUSER="$2" -e PWDB="$3" -e PWPW="$4" -e PWSQL="$5" \
    -e PATH="$PGHOME/bin:/usr/local/bin:/usr/bin:/bin" \
    -e LD_LIBRARY_PATH="$PGHOME/lib" \
    "$CONTAINER" python3 -c '
import subprocess, os
p = subprocess.run(
    ["/database/panweidb/soft/bin/gsql", "-h", os.environ["PWHOST"], "-p", "5432",
     "-U", os.environ["PWUSER"], "-d", os.environ["PWDB"], "-c", os.environ["PWSQL"]],
    input=os.environ["PWPW"] + "\n", capture_output=True, text=True)
out = (p.stdout or "").strip()
err = (p.stderr or "").strip()
if out: print(out)
if err and "Password for user" not in err: print("[stderr]", err)
' || true
}

# 容器内：数据目录是否已初始化（存在 PG_VERSION）
is_initialized() { docker_exec test -f "$PGDATA/PG_VERSION" 2>/dev/null; }

# 容器内：二进制是否已解包（gs_initdb 存在）
is_unpacked() { docker_exec test -x "$PGHOME/bin/gs_initdb" 2>/dev/null; }

# 探活：TCP 5432 端口可达即认为数据库在监听（与 omm 口令无关，避免 inituser 口令未设时误判）
db_ready() {
  docker exec "$CONTAINER" python3 -c '
import socket, sys
try:
    s = socket.create_connection(("127.0.0.1", 5432), 2)
    s.close()
except Exception:
    sys.exit(1)
' 2>/dev/null
}

# 容器当前状态
container_state() {
  docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo missing
}

# ---------- 步骤 ----------
ensure_container() {
  local st
  st="$(container_state)"
  case "$st" in
    missing)
      echo ">> 容器不存在，创建 $CONTAINER (image=$IMAGE) ..."
      docker run --privileged -d --name "$CONTAINER" -p "$HOST_PORT:5432" \
        --entrypoint bash "$IMAGE" -c 'tail -f /dev/null'
      ;;
    exited|paused)
      echo ">> 容器状态=$st，docker start ..."
      docker start "$CONTAINER" >/dev/null
      ;;
    running)
      echo ">> 容器已在运行。"
      ;;
    *)
      echo ">> 容器状态=$st（异常），请手动处理。"
      exit 1
      ;;
  esac
  for _ in $(seq 1 20); do
    if docker_exec true 2>/dev/null; then return 0; fi
    sleep 1
  done
  echo "ERROR: 容器启动后 exec 不可用"; exit 1
}

unpack_binaries() {
  if is_unpacked; then echo ">> 二进制已解包，跳过。"; return 0; fi
  echo ">> 解包安装包到 $PGHOME ..."
  docker_exec bash -c "
    set -e
    mkdir -p $PGHOME
    TARBALL=\$(ls /root/PanWeiDB_*_install-openeuler_20.03.tar.gz 2>/dev/null | head -1)
    if [ -z \"\$TARBALL\" ]; then echo 'ERROR: 容器内未找到安装包 /root/PanWeiDB_*_install-openeuler_20.03.tar.gz'; exit 1; fi
    tar -xzf \"\$TARBALL\" -C $PGHOME
    tar -xjf $PGHOME/PanWeiDB_V2.0-S3.2.0_B01-openEuler-64bit.tar.bz2 -C $PGHOME
    tar -xzf $PGHOME/PanWeiDB_V2.0-S3.2.0_B01-openEuler-64bit-om.tar.gz -C $PGHOME
    chown -R omm:dbgrp $PGHOME
    ls $PGHOME/bin/gs_initdb >/dev/null && echo unpack-ok
  "
}

write_static_files() {
  echo ">> 写 license / gaussdb.version / 日志目录 ..."
  docker_exec bash -c "
    set -e
    mkdir -p /etc/panweidb/license
    cat > /etc/panweidb/license/license.lic <<'LIC'
$LICENSE_YAML
LIC
    chmod 777 /etc/panweidb/license/license.lic

    cat > $PGDATA/gaussdb.version <<'VER'
$GAUSSDB_VERSION
VER
    chown omm:dbgrp $PGDATA/gaussdb.version

    mkdir -p $PGDATA/pg_log /database/panweidb/log
    chown -R omm:dbgrp $PGDATA/pg_log /database/panweidb/log
  "
}

init_data() {
  echo ">> gs_initdb 初始化 $PGDATA (nodename=$NODE_NAME) ..."
  omm_exec "
    mkdir -p $PGDATA
    rm -rf $PGDATA/* $PGDATA/.[!.]* 2>/dev/null || true
    gs_initdb --encoding=UTF8 --lc-collate=en_US.UTF8 --lc-ctype=en_US.UTF8 --nodename=$NODE_NAME $PGDATA
  "
}

configure_db() {
  echo ">> 配置 listen_addresses='*' 与 pg_hba.conf（本地 trust / 远程 sha256）..."
  docker_exec bash -c "
    set -e
    sed -i \"s/^#*listen_addresses = .*/listen_addresses = '*'/\" $PGDATA/postgresql.conf
    cat > $PGDATA/pg_hba.conf <<'HBA'
# TYPE  DATABASE        USER            ADDRESS                 METHOD
local   all             all                                     trust
host    all             all             127.0.0.1/32            trust
host    all             all             ::1/128                 trust
host    all             all             0.0.0.0/0               sha256
host    all             all             ::0/0                   sha256
HBA
    chown omm:dbgrp $PGDATA/pg_hba.conf
    chmod 600 $PGDATA/pg_hba.conf
  "
}

start_db() {
  if db_ready; then echo ">> 数据库已在运行。"; return 0; fi
  echo ">> gs_ctl start ..."
  omm_exec "gs_ctl start -D $PGDATA -l $PGDATA/pg_log/logfile" 2>&1 || true
  for _ in $(seq 1 30); do
    if db_ready; then echo ">> 数据库已就绪（端口监听）。"; sleep 3; return 0; fi
    sleep 1
  done
  echo "ERROR: 数据库未就绪，请查看 $PGDATA/pg_log/logfile"; exit 1
}

set_omm_password() {
  echo ">> 设置 omm 超级用户口令 ..."
  omm_exec "gsql -d postgres -U omm -c \"ALTER ROLE omm PASSWORD '$OMM_PW';\"" 2>&1 || true
}

provision_app() {
  echo ">> 创建 $APP_DB / $APP_USER / schema $APP_SCHEMA ..."
  sql_as 127.0.0.1 omm postgres "$OMM_PW" "CREATE USER $APP_USER WITH PASSWORD '$APP_PW';" 2>/dev/null || true
  sql_as 127.0.0.1 omm postgres "$OMM_PW" "ALTER ROLE $APP_USER PASSWORD '$APP_PW';" 2>/dev/null || true
  sql_as 127.0.0.1 omm postgres "$OMM_PW" "CREATE DATABASE $APP_DB OWNER $APP_USER;" 2>/dev/null || true
  sql_as 127.0.0.1 omm bonc "$OMM_PW" "CREATE SCHEMA IF NOT EXISTS $APP_SCHEMA AUTHORIZATION $APP_USER;" 2>/dev/null || true
  sql_as 127.0.0.1 omm postgres "$OMM_PW" "GRANT ALL PRIVILEGES ON DATABASE $APP_DB TO $APP_USER;" 2>/dev/null || true
  sql_as 127.0.0.1 omm bonc "$OMM_PW" "GRANT ALL ON SCHEMA $APP_SCHEMA TO $APP_USER;" 2>/dev/null || true
  sql_as 127.0.0.1 omm bonc "$OMM_PW" "ALTER ROLE $APP_USER SET search_path = $APP_SCHEMA;" 2>/dev/null || true
}

verify() {
  echo ">> 验证连接 (boncuser over TCP) ..."
  echo "  current context:"; sql_as 127.0.0.1 "$APP_USER" "$APP_DB" "$APP_PW" "SELECT current_database(), current_user, current_schema();"
  echo "  search_path:";     sql_as 127.0.0.1 "$APP_USER" "$APP_DB" "$APP_PW" "SHOW search_path;"
  echo "  port on host:";    docker port "$CONTAINER" 2>/dev/null || true
}

reinit() {
  echo ">> [--reinit] 清空数据目录（数据将全部丢失）..."
  omm_exec "gs_ctl stop -D $PGDATA -m immediate" 2>/dev/null || true
  docker_exec bash -c "rm -rf $PGDATA/* $PGDATA/.[!.]*" 2>/dev/null || true
}

show_status() {
  echo "== 容器状态 =="; docker ps -a --filter name="$CONTAINER" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || true
  if docker_exec true 2>/dev/null; then
    echo "== 初始化状态 =="; is_initialized && echo "data: initialized" || echo "data: NOT initialized"
    echo "== 二进制状态 =="; is_unpacked && echo "bin: unpacked" || echo "bin: NOT unpacked"
    if db_ready; then echo "== 就绪 =="; echo "db: READY"; else echo "== 就绪 =="; echo "db: NOT ready"; fi
  fi
}

# ---------- 主流程 ----------
need_docker
case "$MODE" in
  status)
    show_status
    exit 0
    ;;
  reinit)
    ensure_container
    reinit
    ;;
  up)
    ensure_container
    ;;
esac

unpack_binaries

if is_initialized && [[ "$MODE" != "reinit" ]]; then
  echo ">> 数据目录已初始化，仅确保数据库启动。"
  write_static_files
  start_db
else
  echo ">> 数据目录未初始化，执行完整初始化流程。"
  init_data
  configure_db
  write_static_files
  start_db
  set_omm_password
  provision_app
fi

verify
echo ""
echo "完成。连接方式（按客户端所在位置选择）："
echo "  宿主机（裸进程 / 本机脚本）："
echo "    postgresql://$APP_USER:$APP_PW@127.0.0.1:$HOST_PORT/$APP_DB"
echo "  另一个 Docker 容器（在 orbstack 网络内）："
echo "    postgresql://$APP_USER:$APP_PW@host.docker.internal:$HOST_PORT/$APP_DB"
echo "  备用（容器真实 IP，重启容器后可能变化）："
echo "    postgresql://$APP_USER:$APP_PW@$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$CONTAINER" 2>/dev/null || echo '<容器IP>'):$HOST_PORT/$APP_DB"
echo ""
echo "说明：panweidb 的安全插件禁止“远程 + trust”，pg_hba 已设为本地 trust / 远程 sha256；"
echo "      上面连接串均走密码认证。客户端在宿主机时不要用 host.docker.internal（宿主机不解析该名）。"
