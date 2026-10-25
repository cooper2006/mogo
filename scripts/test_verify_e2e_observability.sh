#!/usr/bin/env bash
#
# test_verify_e2e_observability.sh — 证明 verify_e2e_observability.sh 的断言真的会失败
#
# 只验证「没有环境时返回 2」是不够的：一个永远返回 2 的脚本也能通过那种检查。
# 这里用假后端（scripts/testlib/fake_observability_backends.py）搭出已知答案的
# 环境，分别验证：全绿环境 → exit 0；Loki/Tempo/规则缺失 → exit 1 且报告点名；
# 工具/端点缺失 → exit 2。
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VERIFY="${ROOT_DIR}/scripts/verify_e2e_observability.sh"
FAKE="${ROOT_DIR}/scripts/testlib/fake_observability_backends.py"
WORK="$(mktemp -d)"
PIDS=""

fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "ok  $*"; }
assert_eq() { # assert_eq <期望> <实际> <说明>
  [ "$1" = "$2" ] || fail "$3（期望 '$1'，实际 '$2'）"
  ok "$3"
}
assert_contains() { # assert_contains <文件> <文本> <说明>
  grep -qF -- "$2" "$1" || fail "$3（在 $1 中找不到 '$2'）"
  ok "$3"
}
assert_file_lacks() {
  if grep -qF -- "$2" "$1"; then fail "$3（$1 里不应出现 '$2'）"; fi
  ok "$3"
}

cleanup() {
  for pid in ${PIDS}; do
    kill "${pid}" 2>/dev/null || true
    wait "${pid}" 2>/dev/null || true   # 回收子进程，避免 shell 打印 "Terminated"
  done
  rm -rf "${WORK}"
}
trap cleanup EXIT

command -v curl >/dev/null 2>&1 || fail "缺少 curl"
command -v python3 >/dev/null 2>&1 || fail "缺少 python3"
[ -f "${VERIFY}" ] || fail "找不到 ${VERIFY}"
[ -f "${FAKE}" ] || fail "找不到 ${FAKE}"
bash -n "${VERIFY}" || fail "verify_e2e_observability.sh 语法错误"

start_backends() { # start_backends <mode> —— 启动假后端并把 URL 前缀写到 WORK/urls
  local mode="$1"
  local port_file="${WORK}/ports-${mode}"
  rm -f "${port_file}"
  FAKE_MODE="${mode}" python3 "${FAKE}" "${port_file}" &
  PIDS="${PIDS} $!"

  local waited=0
  while [ ! -s "${port_file}" ]; do
    waited=$((waited + 1))
    [ "${waited}" -gt 100 ] && fail "假后端在 5s 内没有就绪（mode=${mode}）"
    sleep 0.05
  done

  GATEWAY_URL="http://127.0.0.1:$(awk -F= '$1=="gateway"{print $2}' "${port_file}")"
  LOKI_URL="http://127.0.0.1:$(awk -F= '$1=="loki"{print $2}' "${port_file}")"
  TEMPO_URL="http://127.0.0.1:$(awk -F= '$1=="tempo"{print $2}' "${port_file}")"
  PROM_URL="http://127.0.0.1:$(awk -F= '$1=="prometheus"{print $2}' "${port_file}")"
  AM_URL="http://127.0.0.1:$(awk -F= '$1=="alertmanager"{print $2}' "${port_file}")"
}

run_verify() { # run_verify <报告目录> —— 用当前 URL 变量跑验证脚本，输出到 WORK/out
  bash "${VERIFY}" \
    --gateway-url "${GATEWAY_URL}" \
    --loki-url "${LOKI_URL}" \
    --tempo-url "${TEMPO_URL}" \
    --prometheus-url "${PROM_URL}" \
    --alertmanager-url "${AM_URL}" \
    --trace-id "0123456789abcdef0123456789abcdef" \
    --report-dir "$1" >"${WORK}/out" 2>&1
}

# ─────────────────────── 1. 全绿环境 → exit 0 ───────────────────────

start_backends pass
set +e
run_verify "${WORK}/report-pass"
status=$?
set -e
assert_eq 0 "${status}" "全绿环境退出码为 0"
assert_contains "${WORK}/out" "全链路追踪验证通过" "输出结论为通过"

PASS_REPORT="$(find "${WORK}/report-pass" -name '*-e2e-observability.md' | head -1)"
[ -n "${PASS_REPORT}" ] || fail "没有生成报告文件"
assert_contains "${PASS_REPORT}" "0123456789abcdef0123456789abcdef" "报告记录了 trace_id"
assert_contains "${PASS_REPORT}" "| pass | Loki 查到该 trace 的日志" "报告记录 Loki 通过"
assert_contains "${PASS_REPORT}" "| pass | Tempo 查到该 trace" "报告记录 Tempo 通过"
assert_contains "${PASS_REPORT}" "| pass | 告警规则已加载" "报告记录规则通过"
assert_contains "${PASS_REPORT}" "| pass | Alertmanager 就绪" "报告记录 Alertmanager 通过"
assert_file_lacks "${PASS_REPORT}" "**fail**" "全绿报告里没有 fail 行"

# ─────────────────── 2. Loki 查不到日志 → exit 1 且点名 ───────────────────

start_backends empty-loki
set +e
run_verify "${WORK}/report-loki"
status=$?
set -e
assert_eq 1 "${status}" "Loki 空结果时退出码为 1"
LOKI_REPORT="$(find "${WORK}/report-loki" -name '*-e2e-observability.md' | head -1)"
assert_contains "${LOKI_REPORT}" "**fail** | Loki 查到该 trace 的日志" "报告点名 Loki 失败"
assert_contains "${LOKI_REPORT}" "1 项失败" "报告统计失败数为 1"
# 其它信号仍然通过——证明这不是「一挂全挂」的假断言
assert_contains "${LOKI_REPORT}" "| pass | Tempo 查到该 trace" "Loki 失败不影响 Tempo 判定"

# ─────────────────── 3. Tempo 查不到 trace → exit 1 ───────────────────

start_backends empty-tempo
set +e
run_verify "${WORK}/report-tempo"
status=$?
set -e
assert_eq 1 "${status}" "Tempo 空结果时退出码为 1"
TEMPO_REPORT="$(find "${WORK}/report-tempo" -name '*-e2e-observability.md' | head -1)"
assert_contains "${TEMPO_REPORT}" "**fail** | Tempo 查到该 trace" "报告点名 Tempo 失败"

# ─────────────────── 4. 告警规则没加载 → exit 1 ───────────────────

start_backends no-rules
set +e
run_verify "${WORK}/report-rules"
status=$?
set -e
assert_eq 1 "${status}" "规则数不足时退出码为 1"
RULES_REPORT="$(find "${WORK}/report-rules" -name '*-e2e-observability.md' | head -1)"
assert_contains "${RULES_REPORT}" "**fail** | 告警规则已加载" "报告点名规则失败"

# ─────────────── 5. 环境不具备（端点不可达）→ exit 2，不是 1 ───────────────

set +e
bash "${VERIFY}" --gateway-url "http://127.0.0.1:1" --skip-alertmanager >"${WORK}/out-env" 2>&1
status=$?
set -e
assert_eq 2 "${status}" "端点不可达时退出码为 2（环境不具备）"
assert_contains "${WORK}/out-env" "环境不具备" "输出说明环境不具备"

# ─────────────── 6. 非法 trace_id → exit 2 ───────────────

set +e
bash "${VERIFY}" --trace-id "not-hex" --skip-alertmanager >"${WORK}/out-trace" 2>&1
status=$?
set -e
assert_eq 2 "${status}" "非法 trace_id 退出码为 2"
assert_contains "${WORK}/out-trace" "32 位小写十六进制" "输出指出格式要求"

# ─────────────── 7. --skip-alertmanager 时该行标 skip ───────────────

start_backends pass
set +e
bash "${VERIFY}" \
  --gateway-url "${GATEWAY_URL}" --loki-url "${LOKI_URL}" --tempo-url "${TEMPO_URL}" \
  --prometheus-url "${PROM_URL}" --skip-alertmanager \
  --trace-id "0123456789abcdef0123456789abcdef" \
  --report-dir "${WORK}/report-skip" >"${WORK}/out-skip" 2>&1
status=$?
set -e
assert_eq 0 "${status}" "跳过 Alertmanager 时仍可全绿"
SKIP_REPORT="$(find "${WORK}/report-skip" -name '*-e2e-observability.md' | head -1)"
assert_contains "${SKIP_REPORT}" "| skip | Alertmanager 就绪" "报告把跳过项标为 skip"

echo "E2E observability verification behaviour is valid."
