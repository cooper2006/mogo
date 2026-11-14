#!/usr/bin/env bash
# 024 T041 (FR-020/FR-022)：灰度发布 CLI。
#
# 动作：
#   start   [--version <tag|sha>] [--weight <1|10|50|100>]
#           拉起 canary 副本（compose profile=canary），设置灰度档位
#   promote [--weight <1|10|50|100>] [--yes]
#           把灰度比例推进到指定档位（覆写 nginx-canary.conf 并重载网关）
#   rollback [--reason <id>] [--yes]
#           关闭灰度（档位归 0），停止 canary 副本，写回滚记录
#   status  [--json]
#           当前档位 / 运行副本 / nginx 分流比例 / 状态文件
#
# 依赖：docker compose、python3。档位定义见 deploy/canary/canary-plan.yml，
#       自动回滚条件见 deploy/canary/rollback-conditions.yml。
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLAN_FILE="${ROOT_DIR}/deploy/canary/canary-plan.yml"
NGINX_CANARY_CONF="${MOGO_CANARY_NGINX_CONF:-${ROOT_DIR}/deploy/canary/nginx-canary.conf}"
STATE_FILE="${ROOT_DIR}/deploy/canary/.canary-state.json"
ROLLBACK_DIR="${ROOT_DIR}/deploy/runbook/rollbacks"
GATEWAY_SERVICE="${MOGO_CANARY_GATEWAY_SERVICE:-gateway}"
CANARY_SERVICES=(chat-api-canary admin-api-canary document-api-canary)

usage() {
  cat <<'EOF'
用法: deploy/cli/canary.sh <action> [选项]
  start    --version <tag|sha> [--weight N]   拉起灰度副本并设档位
  promote  --weight N [--yes]                  推进到指定档位（1/10/50/100）
  rollback [--reason <id>] [--yes]             关闭灰度并停止副本
  status   [--json]                            查看当前灰度状态
EOF
}

log() { printf 'canary: %s\n' "$*"; }
die() { printf 'canary: 错误: %s\n' "$*" >&2; exit 1; }

require_docker() { command -v docker >/dev/null 2>&1 || die "docker 不可用"; }

# 读 plan.yml 的档位 weight 列表
plan_weights() {
  python3 -c 'import sys,yaml;d=yaml.safe_load(open(sys.argv[1]));print(" ".join(str(s["weight"]) for s in d["canary"]["steps"]))' "$PLAN_FILE"
}

# 写 nginx 分流片段：weight=0 → 全 stable map；weight>0 → split_clients
write_nginx_weight() {
  local weight="$1"
  local out
  out=$(mktemp)
  if [[ "${weight}" == "0" ]]; then
    cat >"${out}" <<'EOF'
# 灰度已关闭（canary.sh rollback / weight=0）：全部走 stable，
# 仅显式携带 X-MOGO-CANARY:1 的请求进入 canary 副本。
map $http_x_mogo_canary $mogo_canary_force {
    default 0;
    "1"     1;
}
map "x" $mogo_canary_route {
    default "stable";
}
EOF
  else
    {
      cat <<'EOF'
# 024 T039 (FR-020)：灰度分流片段，由 canary.sh 按档位覆写。
# X-MOGO-CANARY:1 强制走 canary；无头时按来源 IP hash 落到灰度档位。
map $http_x_mogo_canary $mogo_canary_force {
    default 0;
    "1"     1;
}
split_clients "${remote_addr}:${http_x_mogo_canary}" $mogo_canary_route {
EOF
      printf '    %s%%        "canary";\n' "${weight}"
      printf '    *         "stable";\n'
      printf '}\n'
    } >"${out}"
  fi
  cp "${out}" "${NGINX_CANARY_CONF}"
  rm -f "${out}"
}

reload_gateway() {
  # 网关容器内重载 nginx（配置已通过 bind mount 同步到容器）
  if docker compose -f "${ROOT_DIR}/docker-compose.yml" ps --status running "${GATEWAY_SERVICE}" >/dev/null 2>&1; then
    # 容器若在新增 mogo-canary.conf 挂载之前启动，文件不存在 → 重载失败属预期
    #（需重建 gateway 后才生效），不阻塞 canary.sh 的状态流转。
    if ! docker compose -f "${ROOT_DIR}/docker-compose.yml" exec -T "${GATEWAY_SERVICE}" nginx -t 2>/dev/null \
      || ! docker compose -f "${ROOT_DIR}/docker-compose.yml" exec -T "${GATEWAY_SERVICE}" nginx -s reload 2>/dev/null; then
      log "警告: 网关 nginx 重载未生效（${NGINX_CANARY_CONF} 已更新；容器需重建以挂载 mogo-canary.conf）"
    fi
  else
    log "网关未运行，跳过 nginx 重载（配置已写入 ${NGINX_CANARY_CONF}）"
  fi
}

save_state() {
  local json="$1"
  mkdir -p "$(dirname "${STATE_FILE}")"
  printf '%s\n' "${json}" > "${STATE_FILE}"
}

read_state() {
  if [[ -f "${STATE_FILE}" ]]; then
    cat "${STATE_FILE}"
  else
    echo '{}'
  fi
}

action_start() {
  local version="" weight="1"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --version) version="$2"; shift 2 ;;
      --weight) weight="$2"; shift 2 ;;
      *) die "未知参数: $1" ;;
    esac
  done
  require_docker
  [[ -z "${version}" ]] && die "start 需要 --version <tag|sha>"
  local started_at
  started_at=$(python3 -c 'import datetime;print(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))')

  log "拉起灰度副本（version=${version}, weight=${weight}%）..."
  docker compose -f "${ROOT_DIR}/docker-compose.yml" --profile canary up -d "${CANARY_SERVICES[@]}"

  write_nginx_weight "${weight}"
  reload_gateway

  save_state "$(python3 -c '
import json,sys
print(json.dumps({"version":sys.argv[1],"weight":int(sys.argv[2]),
 "started_at":sys.argv[3],"canary_containers":sys.argv[4].split()}))' \
  "${version}" "${weight}" "${started_at}" "${CANARY_SERVICES[*]}")"
  log "已启动灰度：version=${version}, weight=${weight}%（观察窗口见 deploy/canary/canary-plan.yml）"
}

action_promote() {
  local weight="" yes=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --weight) weight="$2"; shift 2 ;;
      --yes) yes=1; shift ;;
      *) die "未知参数: $1" ;;
    esac
  done
  require_docker
  [[ -z "${weight}" ]] && die "promote 需要 --weight <1|10|50|100>"
  local weights
  weights=$(plan_weights)
  case " ${weights} " in
    *" ${weight} "*) : ;;
    *) die "档位 ${weight} 不在 plan 中（允许: ${weights}）" ;;
  esac

  if [[ "${yes}" == "0" ]]; then
    read -r -p "确认把灰度推进到 ${weight}%？(yes/no) " answer
    [[ "${answer}" == "yes" ]] || die "已取消"
  fi

  # 若 canary 副本未运行，先拉起
  docker compose -f "${ROOT_DIR}/docker-compose.yml" --profile canary ps -q "${CANARY_SERVICES[0]}" >/dev/null 2>&1 \
    || docker compose -f "${ROOT_DIR}/docker-compose.yml" --profile canary up -d "${CANARY_SERVICES[@]}"

  write_nginx_weight "${weight}"
  reload_gateway

  local state
  state=$(read_state)
  local version
  version=$(printf '%s' "${state}" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("version",""))' 2>/dev/null || echo "")
  local updated
  updated=$(python3 -c '
import json,sys
try:
    d=json.loads(sys.argv[1])
except Exception:
    d={}
d["weight"]=int(sys.argv[2])
print(json.dumps(d))' "${state}" "${weight}")
  save_state "${updated}"
  log "灰度已推进到 ${weight}%（version=${version:-unknown}）"
  if [[ "${weight}" == "100" ]]; then
    log "已到 100% 档：确认稳定后可用 deploy/cli/canary.sh rollback --yes 关闭灰度通道"
  fi
}

action_rollback() {
  local reason="manual" yes=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --reason) reason="$2"; shift 2 ;;
      --yes) yes=1; shift ;;
      *) die "未知参数: $1" ;;
    esac
  done
  require_docker
  if [[ "${yes}" == "0" ]]; then
    read -r -p "确认回滚并关闭灰度？(yes/no) " answer
    [[ "${answer}" == "yes" ]] || die "已取消"
  fi

  local state started_at end_at
  state=$(read_state)
  started_at=$(printf '%s' "${state}" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("started_at",""))' 2>/dev/null || echo "")
  end_at=$(python3 -c 'import datetime;print(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))')

  local t0 t1 elapsed
  t0=$(python3 -c 'import time;print(time.time())')
  write_nginx_weight 0
  reload_gateway
  # 等待流量切回稳定版
  sleep 2
  docker compose -f "${ROOT_DIR}/docker-compose.yml" --profile canary stop "${CANARY_SERVICES[@]}" >/dev/null 2>&1 || true
  t1=$(python3 -c 'import time;print(time.time())')
  elapsed=$(python3 -c "print(round(float('${t1}')-float('${t0}'),1))")

  local version
  version=$(printf '%s' "${state}" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("version","unknown"))' 2>/dev/null || echo "unknown")

  # T047：写回滚实测记录
  local date version_slug
  date=$(python3 -c 'import datetime;print(datetime.datetime.now().strftime("%Y-%m-%d"))')
  version_slug=$(printf '%s' "${version}" | tr '/:' '-')
  local record="${ROLLBACK_DIR}/${date}-${version_slug}.md"
  mkdir -p "${ROLLBACK_DIR}"
  {
    echo "# 回滚记录 ${date}（${version}）"
    echo
    echo "- 开始时间: ${started_at:-未知}"
    echo "- 结束时间: ${end_at}"
    echo "- 实测耗时: ${elapsed}s（T1 级目标 ≤300s）"
    echo "- 触发原因: ${reason}"
    echo "- 触发指标: 见 deploy/canary/rollback-conditions.yml 中 condition id=${reason}"
    echo "- 动作: canary.sh rollback --reason ${reason} --yes"
  } > "${record}"

  save_state "$(python3 -c '
import json,sys
try:
    d=json.loads(sys.argv[1])
except Exception:
    d={}
d["weight"]=0
d["last_rollback"]={"reason":sys.argv[2],"ended_at":sys.argv[3],"elapsed_seconds":float(sys.argv[4])}
print(json.dumps(d))' "${state}" "${reason}" "${end_at}" "${elapsed}")"

  log "已回滚：灰度关闭，canary 副本已停止，耗时 ${elapsed}s；记录 ${record}"
}

action_status() {
  local json=0
  [[ "${1:-}" == "--json" ]] && json=1
  local state
  state=$(read_state)
  local running=""
  if command -v docker >/dev/null 2>&1; then
    running=$(docker compose -f "${ROOT_DIR}/docker-compose.yml" --profile canary ps -q "${CANARY_SERVICES[@]}" 2>/dev/null | tr '\n' ' ')
  fi
  local weight
  weight=$(grep -oE '^[[:space:]]*[0-9]+%' "${NGINX_CANARY_CONF}" 2>/dev/null | head -1 | tr -d ' %') || weight=0
  local payload
  payload=$(python3 -c '
import json,sys
try: d=json.loads(sys.argv[1])
except Exception: d={}
print(json.dumps({"weight":d.get("weight",int(sys.argv[2])),"version":d.get("version",""),
 "started_at":d.get("started_at",""),"canary_containers_running":len(sys.argv[3].split()),
 "nginx_route_weight":int(sys.argv[2]),
 "last_rollback":d.get("last_rollback",None)}))' "${state}" "${weight:-0}" "${running}")
  if [[ "${json}" == "1" ]]; then
    echo "${payload}"
  else
    python3 -c '
import json,sys
d=json.loads(sys.argv[1])
print(f"当前档位: {d[\"nginx_route_weight\"]}%（状态文件 weight={d[\"weight\"]}）")
print(f"版本: {d[\"version\"] or \"(未记录)\"}")
print(f"开始时间: {d[\"started_at\"] or \"-\"}")
print(f"canary 副本运行中: {d[\"canary_containers_running\"]} 个")
if d.get("last_rollback"):
    print(f"上次回滚: {d[\"last_rollback\"]}")' "${payload}"
  fi
}

action="${1:-}"; [[ -n "${action}" ]] && shift
case "${action}" in
  start) action_start "$@" ;;
  promote) action_promote "$@" ;;
  rollback) action_rollback "$@" ;;
  status) action_status "$@" ;;
  *) usage; exit 2 ;;
esac