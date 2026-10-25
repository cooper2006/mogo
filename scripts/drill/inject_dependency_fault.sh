#!/usr/bin/env bash
#
# inject_dependency_fault.sh — 023 T117 端到端韧性验证（真实环境剧本）
#
# 验证链路：注入 MongoDB 故障 → 依赖熔断 → 请求快速失败 → 告警触发 → 排障看板可下钻
#
# 为什么必须真停容器
# ------------------
# 单测已经证明「熔断器打开后不再打依赖」（services/chat-api/tests/resilience/）。
# 但那是假 client。这里要证明的是**真实链路**：容器真的没了 → 探针真的红了 →
# 中间件真的走了熔断分支 → 返回码与耗时真的符合「快速失败」→ 指标真的被
# Prometheus 抓到 → 告警规则真的能烧起来。
#
# 安全边界
#   * 只 stop/start 一个数据容器，不动卷（数据不丢）。
#   * 默认在结束时恢复（--no-restore 可保留故障现场用于排查）。
#   * 没有 docker / 服务不在跑 → 退出码 2，**不产生通过结论**。
#
# 退出码: 0 通过 / 1 断言失败 / 2 环境不具备
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

TARGET="mongo"
API_URL="${MOGO_CHAT_API_URL:-http://127.0.0.1:8000}"
PROMETHEUS_URL="${MOGO_PROMETHEUS_URL:-}"
ALERTMANAGER_URL="${MOGO_ALERTMANAGER_URL:-}"
GRAFANA_URL="${MOGO_GRAFANA_URL:-}"
COMPOSE_FILE="${MOGO_COMPOSE_FILE:-${REPO_ROOT}/docker-compose.yml}"
COMPOSE_PROJECT="${MOGO_COMPOSE_PROJECT:-mogo}"
DEPENDENCY_LABEL=""
QUICK_FAIL_BUDGET="${MOGO_QUICK_FAIL_BUDGET_SECONDS:-1.0}"
TIMEOUT="${MOGO_FAULT_TIMEOUT_SECONDS:-120}"
REPORT_DIR="${MOGO_FAULT_REPORT_DIR:-${REPO_ROOT}/artifacts/observability}"
RESTORE=1
DRY_RUN=0
HTTP_TIMEOUT=10
PROBES=5
FAILURES=0
declare -a RESULTS=()

usage() {
  cat <<'USAGE'
用法: inject_dependency_fault.sh [选项]

选项:
  --target mongo|redis   要注入故障的依赖（默认 mongo）
  --api-url URL          被测服务（默认 $MOGO_CHAT_API_URL 或 http://127.0.0.1:8000）
  --prometheus-url URL   用于验证熔断指标（缺省则跳过该项）
  --alertmanager-url URL 用于验证告警触发（缺省则跳过该项）
  --grafana-url URL      用于验证排障看板（缺省则跳过该项）
  --compose-file FILE    compose 文件（默认仓库根 docker-compose.yml）
  --compose-project NAME compose 项目名（默认 mogo）
  --quick-fail-budget S  快速失败耗时上限秒（默认 1.0）
  --timeout S            等待故障生效/恢复的超时秒（默认 120）
  --report-dir DIR       报告目录（默认 artifacts/observability）
  --no-restore           故障注入后不自动恢复（保持现场）
  --dry-run              只打印将执行的命令
  -h, --help             显示帮助

退出码: 0 通过 / 1 断言失败 / 2 环境不具备
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) TARGET="$2"; shift 2 ;;
    --api-url) API_URL="$2"; shift 2 ;;
    --prometheus-url) PROMETHEUS_URL="$2"; shift 2 ;;
    --alertmanager-url) ALERTMANAGER_URL="$2"; shift 2 ;;
    --grafana-url) GRAFANA_URL="$2"; shift 2 ;;
    --compose-file) COMPOSE_FILE="$2"; shift 2 ;;
    --compose-project) COMPOSE_PROJECT="$2"; shift 2 ;;
    --quick-fail-budget) QUICK_FAIL_BUDGET="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --report-dir) REPORT_DIR="$2"; shift 2 ;;
    --no-restore) RESTORE=0; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "${TARGET}" in
  mongo) DEPENDENCY_LABEL="mongodb" ;;
  redis) DEPENDENCY_LABEL="redis" ;;
  *) echo "--target 只支持 mongo|redis，实际 '${TARGET}'" >&2; exit 2 ;;
esac

log() { printf '[fault] %s\n' "$*"; }

record() {
  RESULTS+=("$1|$2|$3")
  case "$1" in
    pass) log "PASS  $2 — $3" ;;
    fail) log "FAIL  $2 — $3"; FAILURES=$((FAILURES + 1)) ;;
    skip) log "SKIP  $2 — $3" ;;
  esac
}

env_missing() {
  log "环境不具备：$*"
  log "本脚本不做「没有环境也报通过」的处理——请在 compose 环境里运行，"
  log "或把 CI 中的这一步标成 skipped 而不是 passed。"
  exit 2
}

json_get() {
  python3 -c 'import json,sys
d=json.load(sys.stdin)
env={"__builtins__":{}, "len":len, "sum":sum, "float":float, "int":int, "str":str, "min":min, "max":max, "all":all, "any":any}
print(eval(sys.argv[1], env, {"d": d}))' "$1" <<<"$2"
}

urlenc() { python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"; }

ready_state() {  # ready_state —— 打印 "<http_code> <time_total>"
  curl -sS -m "${HTTP_TIMEOUT}" -o /dev/null -w '%{http_code} %{time_total}' "${API_URL%/}/ready" 2>/dev/null || echo "000 0"
}

is_ready() {
  local code
  code="$(ready_state | awk '{print $1}')"
  [[ "${code}" == "200" ]]
}

wait_for() {  # wait_for <描述> <超时秒> <命令...>
  local label="$1" limit="$2"; shift 2
  local waited=0
  until "$@" >/dev/null 2>&1; do
    waited=$((waited + 1))
    if [[ "${waited}" -ge "${limit}" ]]; then
      log "等待超时（${limit}s）：${label}"
      return 1
    fi
    sleep 1
  done
  return 0
}

DOCKER_TIMEOUT="${MOGO_DOCKER_TIMEOUT:-30}"

# docker 调用必须带超时：daemon 卡死时裸 `docker ps` 会永久挂住，
# 让整个演练「看起来在跑」却永不结束——这比直接失败更糟。
docker_guarded() {
  if command -v timeout >/dev/null 2>&1; then
    timeout "${DOCKER_TIMEOUT}" docker "$@"
  else
    docker "$@"
  fi
}

compose() { docker_guarded compose -p "${COMPOSE_PROJECT}" -f "${COMPOSE_FILE}" "$@"; }

# ────────────────────────────── 前置检查 ──────────────────────────────

command -v curl >/dev/null 2>&1 || env_missing "缺少 curl"
command -v python3 >/dev/null 2>&1 || env_missing "缺少 python3"
command -v docker >/dev/null 2>&1 || env_missing "缺少 docker（本脚本要真的停/起容器）"
[[ -f "${COMPOSE_FILE}" ]] || env_missing "找不到 compose 文件：${COMPOSE_FILE}"

if ! docker_guarded compose version >/dev/null 2>&1; then
  env_missing "docker compose v2 不可用"
fi

if ! docker_guarded info --format '{{.ServerVersion}}' >/dev/null 2>&1; then
  env_missing "docker daemon 无响应（${DOCKER_TIMEOUT}s 内没有返回）"
fi

TARGET_STATE="$(compose ps --services --status running 2>/dev/null | tr -d '\r' || true)"
if ! printf '%s\n' "${TARGET_STATE}" | grep -qx "${TARGET}"; then
  env_missing "compose 项目 ${COMPOSE_PROJECT} 里服务 ${TARGET} 没有在运行（先 up -d）"
fi

if ! is_ready; then
  env_missing "${API_URL%/}/ready 当前不是 200 —— 请先确认服务健康，再注入故障"
fi

log "目标：${TARGET}（依赖标签 ${DEPENDENCY_LABEL}）"

# ───────────────────────── 1. 基线 ─────────────────────────

BASELINE="$(ready_state)"
record pass "基线就绪" "GET /ready → ${BASELINE}"

# ───────────────────────── 2. 注入故障 ─────────────────────────

if [[ "${DRY_RUN}" -eq 1 ]]; then
  log "dry-run: 将执行 compose stop ${TARGET}"
  record skip "注入故障" "dry-run 未执行"
else
  compose stop "${TARGET}" >/dev/null 2>&1 || env_missing "compose stop ${TARGET} 失败"
  if wait_for "就绪探针转红" "${TIMEOUT}" bash -c '! curl -fsS -m 5 -o /dev/null '"${API_URL%/}/ready"; then
    record pass "故障已生效" "/ready 在 ${TIMEOUT}s 内转为非 200（${TARGET} 已停）"
  else
    record fail "故障已生效" "${TARGET} 已停但 /ready 仍返回 200（探针没查依赖？）"
  fi
fi

# ───────────────────────── 3. 快速失败 ─────────────────────────

if [[ "${DRY_RUN}" -eq 1 ]]; then
  record skip "快速失败" "dry-run 未执行"
else
  SLOWEST=0
  ALL_5XX=1
  ELAPSED_LOG=""
  attempt=1
  while [[ "${attempt}" -le "${PROBES}" ]]; do
    read -r code elapsed <<<"$(ready_state)"
    ELAPSED_LOG="${ELAPSED_LOG}${code}@${elapsed}s "
    case "${code}" in
      5*) : ;;
      *) ALL_5XX=0 ;;
    esac
    if python3 -c "import sys; sys.exit(0 if float('${elapsed}') <= float('${QUICK_FAIL_BUDGET}') else 1)"; then
      :
    else
      SLOWEST=1
    fi
    attempt=$((attempt + 1))
  done

  if [[ "${ALL_5XX}" -eq 1 ]]; then
    record pass "快速失败返回 5xx" "${ELAPSED_LOG}"
  else
    record fail "快速失败返回 5xx" "出现非 5xx：${ELAPSED_LOG}"
  fi

  if [[ "${SLOWEST}" -eq 0 ]]; then
    record pass "快速失败未等待超时" "全部 ≤ ${QUICK_FAIL_BUDGET}s"
  else
    record fail "快速失败未等待超时" "有请求超过 ${QUICK_FAIL_BUDGET}s：${ELAPSED_LOG}"
  fi
fi

# ───────────────────────── 4. 熔断指标 ─────────────────────────

if [[ -z "${PROMETHEUS_URL}" ]]; then
  record skip "熔断器已打开" "未提供 --prometheus-url"
else
  QUERY="mogo_circuit_breaker_state{dependency=\"${DEPENDENCY_LABEL}\",state=\"open\"}"
  PROM_RESP="$(curl -sS -m "${HTTP_TIMEOUT}" \
    "${PROMETHEUS_URL%/}/api/v1/query?query=$(urlenc "${QUERY}")" || true)"
  STATE_VALUE="$(json_get 'd["data"]["result"][0]["value"][1] if d.get("data",{}).get("result") else "0"' "${PROM_RESP}")"
  if [[ "${STATE_VALUE:-0}" == "1" ]]; then
    record pass "熔断器已打开" "mogo_circuit_breaker_state{dependency=${DEPENDENCY_LABEL},state=open}=1"
  else
    record fail "熔断器已打开" "指标值 ${STATE_VALUE:-未采集到}（指标未接线或未达阈值）"
  fi
fi

# ───────────────────────── 5. 告警触发 ─────────────────────────

if [[ -z "${ALERTMANAGER_URL}" ]]; then
  record skip "告警已触发" "未提供 --alertmanager-url"
else
  AM_RESP="$(curl -sS -m "${HTTP_TIMEOUT}" "${ALERTMANAGER_URL%/}/api/v2/alerts" || true)"
  MOGO_ALERTS="$(json_get 'sum(1 for a in d if a.get("labels",{}).get("alertname","").startswith("Mogo"))' "${AM_RESP}")"
  if [[ "${MOGO_ALERTS:-0}" =~ ^[0-9]+$ ]] && [[ "${MOGO_ALERTS:-0}" -gt 0 ]]; then
    record pass "告警已触发" "Alertmanager 中 ${MOGO_ALERTS} 条 Mogo 告警"
  else
    record fail "告警已触发" "没有 Mogo 告警（规则未加载、for 未到、或通知链未通）"
  fi
fi

# ───────────────────────── 6. 排障看板 ─────────────────────────

if [[ -z "${GRAFANA_URL}" ]]; then
  record skip "排障看板可下钻" "未提供 --grafana-url"
else
  GF_CODE="$(curl -sS -m "${HTTP_TIMEOUT}" -o /dev/null -w '%{http_code}' \
    "${GRAFANA_URL%/}/api/dashboards/uid/mogo-troubleshooting" || echo 000)"
  if [[ "${GF_CODE}" == "200" ]]; then
    record pass "排障看板可下钻" "uid=mogo-troubleshooting 可读"
  else
    record fail "排障看板可下钻" "GET /api/dashboards/uid/mogo-troubleshooting → ${GF_CODE}"
  fi
fi

# ───────────────────────── 7. 恢复 ─────────────────────────

if [[ "${RESTORE}" -eq 0 ]]; then
  record skip "恢复依赖" "--no-restore：保留故障现场"
elif [[ "${DRY_RUN}" -eq 1 ]]; then
  record skip "恢复依赖" "dry-run 未执行"
else
  compose start "${TARGET}" >/dev/null 2>&1 || record fail "恢复依赖" "compose start ${TARGET} 失败"
  if wait_for "就绪探针转绿" "${TIMEOUT}" bash -c 'curl -fsS -m 5 -o /dev/null '"${API_URL%/}/ready"; then
    record pass "恢复依赖" "/ready 在 ${TIMEOUT}s 内回到 200"
  else
    record fail "恢复依赖" "${TARGET} 已启动但 /ready 未在 ${TIMEOUT}s 内恢复"
  fi

  if [[ -n "${PROMETHEUS_URL}" ]]; then
    CLOSED_QUERY="mogo_circuit_breaker_state{dependency=\"${DEPENDENCY_LABEL}\",state=\"closed\"}"
    # 半开状态需要一次成功调用才会回到 closed
    curl -sS -m "${HTTP_TIMEOUT}" -o /dev/null "${API_URL%/}/ready" || true
    sleep 2
    CLOSED_RESP="$(curl -sS -m "${HTTP_TIMEOUT}" \
      "${PROMETHEUS_URL%/}/api/v1/query?query=$(urlenc "${CLOSED_QUERY}")" || true)"
    CLOSED_VALUE="$(json_get 'd["data"]["result"][0]["value"][1] if d.get("data",{}).get("result") else "0"' "${CLOSED_RESP}")"
    if [[ "${CLOSED_VALUE:-0}" == "1" ]]; then
      record pass "熔断器已复位" "state=closed"
    else
      record fail "熔断器已复位" "指标值 ${CLOSED_VALUE:-未采集到}（可能仍在冷却期，属可接受但需确认）"
    fi
  fi
fi

# ─────────────────────────────── 报告 ───────────────────────────────

mkdir -p "${REPORT_DIR}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT="${REPORT_DIR}/${STAMP}-dependency-fault.md"

{
  echo "# 依赖故障注入验证报告"
  echo
  echo "- 时间：$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "- 故障目标：\`${TARGET}\`（依赖标签 \`${DEPENDENCY_LABEL}\`）"
  echo "- 被测服务：${API_URL}"
  echo "- 结果：$([[ "${FAILURES}" -eq 0 ]] && echo "全部通过" || echo "${FAILURES} 项失败")"
  echo
  echo "| 结果 | 检查项 | 说明 |"
  echo "| --- | --- | --- |"
  for row in "${RESULTS[@]}"; do
    IFS='|' read -r verdict name detail <<<"${row}"
    case "${verdict}" in
      pass) mark="pass" ;;
      fail) mark="**fail**" ;;
      *) mark="skip" ;;
    esac
    echo "| ${mark} | ${name} | ${detail//|/\\|} |"
  done
  echo
  echo "## 排障入口"
  echo
  echo "- 看板：Grafana → Troubleshooting（uid \`mogo-troubleshooting\`）→ 依赖健康层"
  echo "- 指标：\`mogo_circuit_breaker_state{dependency=\"${DEPENDENCY_LABEL}\"}\`"
  echo "- 日志查询：\`{service_name=\"chat-api\"} |= \"circuit\"\`"
} >"${REPORT}"

log "报告：${REPORT}"

if [[ "${FAILURES}" -gt 0 ]]; then
  log "${FAILURES} 项断言失败"
  exit 1
fi
log "依赖故障注入验证通过"
exit 0
