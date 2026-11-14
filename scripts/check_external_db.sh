#!/usr/bin/env bash
# 外部数据库模式体检：MOGO_USE_EXTERNAL_DB=1 时，在 ./mogo up 起栈前调用一次。
#
# 外部模式下栈内 mongo / panweidb 容器都不会启动，应用直接连 .env 里配的
# 外部实例。最坑的情况是连接信息没配（或仍指向栈内服务名）——那要等到整栈起来、
# 应用反复连不上才知道。本脚本把这些硬伤提前拦住。
#
# 退出码：0 = 通过（可能带警告）；1 = 配置有硬伤。
set -uo pipefail

ROOT_DIR="${1:-$(pwd)}"

# ── .env 读取 ───────────────────────────────────────────────────────
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

# uri_host: 连接串 -> 主机名
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

# check_host <标签> <主机值> <缺失时的说明>
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

# 根据后端类型检查不同的连接信息
backend="$(env_value MOGO_DATA_BACKEND | tr '[:upper:]' '[:lower:]')"
if [[ "${backend}" == "panweidb" ]]; then
  # PanWeiDB 后端：检查 PanWeiDB 连接，跳过 MongoDB
  PWDB_HOST="$(env_value PANWEIDB_HOST)"
  check_host "PanWeiDB(PANWEIDB_HOST)" "${PWDB_HOST}" \
    "PanWeiDB 后端时把 PANWEIDB_HOST 指到外部实例"
  echo "  [SKIP] MongoDB (using PanWeiDB backend)" >&2
else
  # MongoDB 后端：检查 MongoDB 连接
  MONGO_URI="$(env_value MOGO_MONGODB_URI)"
  check_host "MongoDB(MOGO_MONGODB_URI)" "$(uri_host "${MONGO_URI}")" \
    "默认指向栈内 mongo；外部 MongoDB 在 .env 里给 MOGO_MONGODB_URI"
fi

if [[ "${FATAL}" != "0" ]]; then
  echo "[check-external-db] 连接信息有硬伤，请先修 .env 再 ./mogo up" >&2
  exit 1
fi

echo "[check-external-db] 体检通过" >&2
exit 0
