#!/usr/bin/env bash
#
# verify_e2e_observability.sh — 023 T116 全链路追踪验证（真实环境剧本）
#
# 验证链路：一次真实请求 → 日志带 trace_id → 追踪后端可查 → 指标可见 → 告警规则已加载
#
# 为什么单独做成脚本而不是只写单测
# --------------------------------
# 单测只能证明「同一进程里 span/日志/指标共享 trace_id」。它证明不了日志真的进了
# Loki、trace 真的进了 Tempo、规则真的被 Prometheus 加载——这些都需要跑起来的
# compose 环境。所以这里的每个断言都是打真实 HTTP 查询。
#
# 关键技巧：不依赖响应体返回 trace_id
# -----------------------------------
# 请求头注入 `traceparent: 00-<32hex>-<16hex>-01`，这个 trace_id 由本脚本自己
# 生成。随后拿它去查 Loki 和 Tempo。这样即使端点不返回追踪上下文，也能验证
# 「注入的 context 被服务接受并贯穿三信号」。
#
# 退出码
#  0  全部断言通过
#  1  环境在、但有断言失败（真实缺陷或配置错误）
#  2  环境不具备（缺后端/缺工具）——**明确失败，不产生通过结论**
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

GATEWAY_URL="${MOGO_GATEWAY_URL:-http://127.0.0.1:8080}"
TEMPO_URL="${MOGO_TEMPO_URL:-http://127.0.0.1:3200}"
LOKI_URL="${MOGO_LOKI_URL:-http://127.0.0.1:3100}"
PROMETHEUS_URL="${MOGO_PROMETHEUS_URL:-http://127.0.0.1:9090}"
ALERTMANAGER_URL="${MOGO_ALERTMANAGER_URL:-http://127.0.0.1:9093}"
HTTP_TIMEOUT="${MOGO_E2E_HTTP_TIMEOUT:-10}"
SETTLE_SECONDS="${MOGO_E2E_SETTLE_SECONDS:-8}"
REPORT_DIR="${MOGO_E2E_REPORT_DIR:-${REPO_ROOT}/artifacts/observability}"
TRACE_ID="${MOGO_E2E_TRACE_ID:-}"
SKIP_ALERTMANAGER=0

FAILURES=0
declare -a RESULTS=()  # 注意：bash 3.2 支持数组但不支持关联数组，这里用普通数组

usage() {
  cat <<'USAGE'
用法: verify_e2e_observability.sh [选项]

选项:
  --gateway-url URL     网关入口（默认 $MOGO_GATEWAY_URL 或 http://127.0.0.1:8080）
  --tempo-url URL       Tempo（默认 $MOGO_TEMPO_URL 或 http://127.0.0.1:3200）
  --loki-url URL        Loki（默认 $MOGO_LOKI_URL 或 http://127.0.0.1:3100）
  --prometheus-url URL  Prometheus（默认 $MOGO_PROMETHEUS_URL 或 http://127.0.0.1:9090）
  --alertmanager-url URL Alertmanager（默认 $MOGO_ALERTMANAGER_URL 或 http://127.0.0.1:9093）
  --trace-id HEX32      指定 trace_id（默认随机生成）
  --report-dir DIR      报告目录（默认 artifacts/observability）
  --skip-alertmanager   跳过告警检查（未部署 Alertmanager 时）
  -h, --help            显示帮助

退出码: 0 通过 / 1 断言失败 / 2 环境不具备
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gateway-url) GATEWAY_URL="$2"; shift 2 ;;
    --tempo-url) TEMPO_URL="$2"; shift 2 ;;
    --loki-url) LOKI_URL="$2"; shift 2 ;;
    --prometheus-url) PROMETHEUS_URL="$2"; shift 2 ;;
    --alertmanager-url) ALERTMANAGER_URL="$2"; shift 2 ;;
    --trace-id) TRACE_ID="$2"; shift 2 ;;
    --report-dir) REPORT_DIR="$2"; shift 2 ;;
    --skip-alertmanager) SKIP_ALERTMANAGER=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage >&2; exit 2 ;;
  esac
done

log() { printf '[e2e] %s\n' "$*"; }

record() {  # record <pass|fail|skip> <名称> <说明>
  RESULTS+=("$1|$2|$3")
  case "$1" in
    pass) log "PASS  $2 — $3" ;;
    fail) log "FAIL  $2 — $3"; FAILURES=$((FAILURES + 1)) ;;
    skip) log "SKIP  $2 — $3" ;;
  esac
}

env_missing() {
  log "环境不具备：$*"
  log "本脚本不做「没有后端也报通过」的处理——请先起 compose 的监控 profile，"
  log "或在 CI 中把它标成 skipped 而不是 passed。"
  exit 2
}

need_tool() {
  command -v "$1" >/dev/null 2>&1 || env_missing "缺少命令 $1"
}

http_ok() {  # http_ok <url> —— 2xx/3xx 视为可达
  curl -fsS -m "${HTTP_TIMEOUT}" -o /dev/null "$1" >/dev/null 2>&1
}

json_get() {  # json_get <表达式，用 d 表示解析后的对象> <json 文本>
  # 表达式在受限环境里求值：只放行几个纯函数，避免误用 builtins 造成注入面。
  python3 -c 'import json,sys
d=json.load(sys.stdin)
env={"__builtins__":{}, "len":len, "sum":sum, "float":float, "int":int, "str":str, "min":min, "max":max}
print(eval(sys.argv[1], env, {"d": d}))' "$1" <<<"$2"
}

urlenc() { python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"; }

# ────────────────────────────── 前置检查 ──────────────────────────────

need_tool curl
need_tool python3

if [[ -z "${TRACE_ID}" ]]; then
  command -v openssl >/dev/null 2>&1 || env_missing "缺少 openssl（用于生成 trace_id）"
  TRACE_ID="$(openssl rand -hex 16)"
fi
if [[ ! "${TRACE_ID}" =~ ^[0-9a-f]{32}$ ]]; then
  env_missing "trace_id 必须是 32 位小写十六进制，实际是 '${TRACE_ID}'"
fi
SPAN_ID="$(openssl rand -hex 8)"

http_ok "${GATEWAY_URL%/}/ready" || env_missing "网关 /ready 不可达：${GATEWAY_URL}"
http_ok "${LOKI_URL%/}/ready" || env_missing "Loki /ready 不可达：${LOKI_URL}"
http_ok "${TEMPO_URL%/}/ready" || http_ok "${TEMPO_URL%/}/api/echo" || env_missing "Tempo 不可达：${TEMPO_URL}"
http_ok "${PROMETHEUS_URL%/}/-/ready" || env_missing "Prometheus /-/ready 不可达：${PROMETHEUS_URL}"
if [[ "${SKIP_ALERTMANAGER}" -eq 0 ]]; then
  http_ok "${ALERTMANAGER_URL%/}/-/ready" || env_missing "Alertmanager /-/ready 不可达：${ALERTMANAGER_URL}"
fi

log "trace_id=${TRACE_ID} span_id=${SPAN_ID}"

# ─────────────────────── 1. 发一次带 traceparent 的请求 ───────────────────────

STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RESP_FILE="$(mktemp)"
trap 'rm -f "${RESP_FILE}"' EXIT

STATUS_CODE="$(curl -sS -m "${HTTP_TIMEOUT}" -o "${RESP_FILE}" -w '%{http_code}' \
  -H "traceparent: 00-${TRACE_ID}-${SPAN_ID}-01" \
  -H 'accept: application/json' \
  "${GATEWAY_URL%/}/ready" || echo 000)"

if [[ "${STATUS_CODE}" =~ ^2 ]]; then
  record pass "请求带 traceparent" "GET /ready → HTTP ${STATUS_CODE}"
else
  record fail "请求带 traceparent" "GET /ready → HTTP ${STATUS_CODE}（期望 2xx）"
fi

log "等待 ${SETTLE_SECONDS}s 让日志/trace 批量导出…"
sleep "${SETTLE_SECONDS}"

# ─────────────────────── 2. 日志：Loki 里能按 trace_id 查到 ───────────────────────

LOKI_QUERY="{service_name=~\".+\"} |= \`${TRACE_ID}\`"
LOKI_RESP="$(curl -sS -m "${HTTP_TIMEOUT}" \
  "${LOKI_URL%/}/loki/api/v1/query_range?query=$(urlenc "${LOKI_QUERY}")&limit=20" || true)"
LOKI_COUNT="$(json_get 'sum(len(s.get("values", [])) for s in d.get("data",{}).get("result",[]))' "${LOKI_RESP}")"

if [[ "${LOKI_COUNT:-0}" =~ ^[0-9]+$ ]] && [[ "${LOKI_COUNT:-0}" -gt 0 ]]; then
  record pass "Loki 查到该 trace 的日志" "命中 ${LOKI_COUNT} 行"
else
  record fail "Loki 查到该 trace 的日志" "命中 0 行（日志未带 trace_id，或未进 Loki）"
fi

# ─────────────────────── 3. 追踪：Tempo 里能查到该 trace ───────────────────────

TEMPO_RESP="$(curl -sS -m "${HTTP_TIMEOUT}" "${TEMPO_URL%/}/api/traces/${TRACE_ID}" || true)"
TEMPO_SUMMARY="$(json_get 'len(d.get("batches", []))' "${TEMPO_RESP}")"

if [[ "${TEMPO_SUMMARY:-0}" =~ ^[0-9]+$ ]] && [[ "${TEMPO_SUMMARY:-0}" -gt 0 ]]; then
  record pass "Tempo 查到该 trace" "包含 ${TEMPO_SUMMARY} 个 batch"
else
  record fail "Tempo 查到该 trace" "未返回 trace（采样率过低，或 OTLP 端点未接）"
fi

# ─────────────────────── 4. 指标：Prometheus 可见且已增长 ───────────────────────

PROM_HTTP="$(curl -sS -m "${HTTP_TIMEOUT}" \
  "${PROMETHEUS_URL%/}/api/v1/query?query=$(urlenc 'sum(mogo_http_requests_total)')" || true)"
HTTP_TOTAL="$(json_get 'd["data"]["result"][0]["value"][1]' "${PROM_HTTP}")"
if python3 -c "import sys; sys.exit(0 if float('${HTTP_TOTAL:-0}') > 0 else 1)" 2>/dev/null; then
  record pass "Prometheus 抓到 HTTP 请求指标" "sum(mogo_http_requests_total)=${HTTP_TOTAL}"
else
  record fail "Prometheus 抓到 HTTP 请求指标" "值为 ${HTTP_TOTAL:-空}（抓取未生效？）"
fi

PROM_SLO="$(curl -sS -m "${HTTP_TIMEOUT}" \
  "${PROMETHEUS_URL%/}/api/v1/query?query=$(urlenc 'mogo:slo:availability:error_rate')" || true)"
SLO_VALUE="$(json_get 'd["data"]["result"][0]["value"][1]' "${PROM_SLO}")"
if [[ -n "${SLO_VALUE:-}" ]]; then
  record pass "SLO 记录规则已生效" "mogo:slo:availability:error_rate=${SLO_VALUE}"
else
  record fail "SLO 记录规则已生效" "查询无结果（规则文件未加载？）"
fi

# ─────────────────────── 5. 告警：规则已加载 ───────────────────────

RULES_RESP="$(curl -sS -m "${HTTP_TIMEOUT}" "${PROMETHEUS_URL%/}/api/v1/rules?type=alert" || true)"
MOGO_RULE_COUNT="$(json_get 'sum(len(g.get("rules", [])) for g in d["data"]["groups"] if g.get("name","").startswith("mogo"))' "${RULES_RESP}")"
if [[ "${MOGO_RULE_COUNT:-0}" =~ ^[0-9]+$ ]] && [[ "${MOGO_RULE_COUNT:-0}" -ge 10 ]]; then
  record pass "告警规则已加载" "mogo 分组下 ${MOGO_RULE_COUNT} 条告警规则（期望 ≥10）"
else
  record fail "告警规则已加载" "只有 ${MOGO_RULE_COUNT:-0} 条（期望 ≥10）"
fi

if [[ "${SKIP_ALERTMANAGER}" -eq 0 ]]; then
  AM_RESP="$(curl -sS -m "${HTTP_TIMEOUT}" "${ALERTMANAGER_URL%/}/api/v2/status" || true)"
  AM_CLUSTER="$(json_get 'd.get("cluster",{}).get("status","")' "${AM_RESP}")"
  if [[ "${AM_CLUSTER}" == "ready" ]]; then
    record pass "Alertmanager 就绪" "cluster.status=ready"
  else
    record fail "Alertmanager 就绪" "cluster.status='${AM_CLUSTER}'"
  fi
else
  record skip "Alertmanager 就绪" "已按 --skip-alertmanager 跳过"
fi

# ─────────────────────────────── 报告 ───────────────────────────────

mkdir -p "${REPORT_DIR}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT="${REPORT_DIR}/${STAMP}-e2e-observability.md"

{
  echo "# 全链路追踪验证报告"
  echo
  echo "- 时间：${STARTED_AT}"
  echo "- 入口：${GATEWAY_URL}"
  echo "- trace_id：\`${TRACE_ID}\`"
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
  echo "## 复查命令"
  echo
  echo '```bash'
  echo "curl -sS '${LOKI_URL%/}/loki/api/v1/query_range?query=$(urlenc "${LOKI_QUERY}")'"
  echo "open  '${TEMPO_URL%/}/trace/${TRACE_ID}'"
  echo "open  '${GATEWAY_URL%/}'  # Grafana → Troubleshooting 看板 → trace_id 变量填 ${TRACE_ID}"
  echo '```'
} >"${REPORT}"

log "报告：${REPORT}"

if [[ "${FAILURES}" -gt 0 ]]; then
  log "${FAILURES} 项断言失败"
  exit 1
fi
log "全链路追踪验证通过"
exit 0
