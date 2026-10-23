#!/usr/bin/env bash
# 外部数据库模式体检：MOGO_USE_EXTERNAL_DB=1 时，在 ./mogo up 起栈前调用一次。
#
# 外部模式下栈内 mongo / redis / panweidb 容器都不会启动，应用直接连 .env 里配的
# 外部实例。最坑的情况是连接信息没配（或仍指向栈内服务名）——那要等到整栈起来、
# 应用反复连不上才知道。本脚本把这些硬伤提前拦住，并顺手探测外部 MongoDB 的版本。
#
# 用法：check_external_db.sh <ROOT_DIR> [探测网络名]
#   探测网络默认 mogo_public：应用就是走这个网络连外部数据库的（backend 是 internal，
#   出不去），探测容器必须挂同一个网络才能复现应用的连通性。
#
# 退出码：0 = 通过（可能带警告）；1 = 配置有硬伤（外部模式开着但 URI 缺失或仍指向
# 栈内主机名）。版本/连通性探测失败只警告，不拦部署——探测环境可能拉不到镜像。
set -uo pipefail

ROOT_DIR="${1:-$(pwd)}"
PROBE_NETWORK="${2:-mogo_public}"

# ── .env 读取（shell 环境优先，与 compose 的插值顺序一致）─────────────────
env_value() {
  local key="$1" v=""
  v="${!key-}"
  if [[ -z "$v" && -f "${ROOT_DIR}/.env" ]]; then
    v="$(grep -E "^[[:space:]]*${key}=" "${ROOT_DIR}/.env" | tail -n 1 || true)"
    v="${v#*=}"
    v="${v%$'\r'}"
    v="${v#\"}"
    v="${v%\"}"
    v="${v#\'}"
    v="${v%\'}"
  fi
  printf '%s' "${v}"
}

# uri_host "mongodb://user:pass@db.example.com:27017/mogo?x=1" -> db.example.com
uri_host() {
  local u="${1#*://}"
  u="${u#*@}"
  u="${u%%\?*}"
  u="${u%%/*}"
  if [[ "${u}" == \[*\]* ]]; then
    u="${u#\[}"
    printf '%s' "${u%%\]*}"
  else
    printf '%s' "${u%%:*}"
  fi
}

# uri_port ... -> 27017（缺省时按数据源默认给）
uri_port() {
  local u="${1#*://}" p="${2:-27017}"
  u="${u#*@}"
  u="${u%%\?*}"
  u="${u%%/*}"
  if [[ "${u}" == \[*\]* ]]; then
    local rest="${u#*\]}"
    rest="${rest#:}"
    [[ -n "${rest}" ]] && p="${rest}"
  else
    case "${u}" in
      *:*) p="${u##*:}" ;;
    esac
  fi
  printf '%s' "${p}"
}

# check_host <标签> <主机值> <缺失时的说明> —— 主机缺失/仍指向栈内服务名 => 硬伤
FATAL=0
check_host() {
  local label="$1" host="$2" hint="$3" internal=" mongo redis panweidb "
  if [[ -z "${host}" ]]; then
    echo "  [FAIL] ${label}: 连接信息未配置（${hint}）。外部模式下必须显式给出外部地址" >&2
    FATAL=1
    return
  fi
  case "${internal}" in
    *" ${host} "*) echo "  [FAIL] ${label}: ${host} 仍是栈内服务名，外部模式下它没有容器" >&2 ; FATAL=1 ;;
  esac
}

# ── 只对外部模式生效 ──────────────────────────────────────────────────────
if [[ "$(env_value MOGO_USE_EXTERNAL_DB)" != "1" ]]; then
  exit 0
fi

echo "[check-external-db] MOGO_USE_EXTERNAL_DB=1，体检外部数据库连接信息" >&2

MONGO_URI="$(env_value MOGO_MONGODB_URI)"
REDIS_URL="$(env_value MOGO_REDIS_URL)"
KERNEL_URL="$(env_value MOGO_KERNEL_REDIS_URL)"
PWDB_HOST="$(env_value PANWEIDB_HOST)"

check_host "MongoDB(MOGO_MONGODB_URI)"    "$(uri_host "${MONGO_URI}")" \
  "默认指向栈内 mongo；外部 MongoDB 在 .env 里给 MOGO_MONGODB_URI"
check_host "Redis(MOGO_REDIS_URL)"        "$(uri_host "${REDIS_URL}")" \
  "默认指向栈内 redis；外部 Redis 在 .env 里给 MOGO_REDIS_URL"
check_host "Kernel Redis(MOGO_KERNEL_REDIS_URL)" "$(uri_host "${KERNEL_URL}")" \
  "默认指向栈内 redis；DSH 锁/归属缓存请单独给 MOGO_KERNEL_REDIS_URL（独立 DB）"
check_host "PanWeiDB(PANWEIDB_HOST)"      "${PWDB_HOST}" \
  "PanWeiDB 后端时把 PANWEIDB_HOST 指到外部实例"

if [[ "${FATAL}" != "0" ]]; then
  echo "[check-external-db] 连接信息有硬伤，请先修 .env 再 ./mogo up" >&2
  exit 1
fi

# ── 外部 MongoDB 版本探测（警告级：版本过低会带 FCV 门禁，连不上也不拦部署）───
MONGO_IMG="${MOGO_MONGO_IMAGE:-mongo:8.3.13}"
case "${MONGO_URI}" in
  mongodb://*|mongodb+srv://*) ;;
  *)
    echo "  [warn] MongoDB URI 不是 mongodb:// 或 mongodb+srv:// 开头（当前: ${MONGO_URI}），跳过版本探测" >&2
    exit 0 ;;
esac

if ! docker image inspect "${MONGO_IMG}" >/dev/null 2>&1; then
  echo "  [info] 跳过 MongoDB 版本探测：本地没有 ${MONGO_IMG}（拉不到镜像）" >&2
  exit 0
fi

# 探测容器要和应用走同一个网络才复现连通性；网络不存在就先建（compose up 时也会建同名的）
if ! docker network inspect "${PROBE_NETWORK}" >/dev/null 2>&1; then
  docker network create "${PROBE_NETWORK}" >/dev/null 2>&1 || {
    echo "  [info] 跳过 MongoDB 版本探测：网络 ${PROBE_NETWORK} 创建失败" >&2
    exit 0
  }
fi

if command -v timeout >/dev/null 2>&1; then
  VER="$(timeout 25 docker run --rm --network "${PROBE_NETWORK}" "${MONGO_IMG}" \
    mongosh "${MONGO_URI}" --quiet --eval 'db.version()' 2>/dev/null | tail -n 1 | tr -d '\r')"
else
  VER="$(docker run --rm --network "${PROBE_NETWORK}" "${MONGO_IMG}" \
    mongosh "${MONGO_URI}" --quiet --eval 'db.version()' 2>/dev/null | tail -n 1 | tr -d '\r')"
fi

if [[ -z "${VER}" ]]; then
  echo "  [warn] 外部 MongoDB 不可达或探测失败（URI: ${MONGO_URI}）。应用连不上也会起不来" >&2
  exit 0
fi

echo "  [ok] 外部 MongoDB 版本: ${VER}" >&2
# 8.x 直接可用；6.0 及以下必须逐级升级（FCV 门禁），7.0 也能用但要提醒
case "${VER}" in
  8.*|9.*) ;;
  7.*)
    echo "  [warn] 外部 MongoDB 是 7.x，可用但低于项目镜像的 8.3.13；如无特殊原因建议升到 8.x" >&2 ;;
  *)
    echo "  [warn] 外部 MongoDB 是 ${VER}，低于 7.0。项目目标版本 8.3.13，需按 6.0 → 7.0 → 8.0 → 8.3 逐级升级（直接换版本起不来，见 docs/backup-recovery.md）" >&2 ;;
esac

exit 0