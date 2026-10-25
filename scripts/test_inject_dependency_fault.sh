#!/usr/bin/env bash
#
# test_inject_dependency_fault.sh — 证明故障注入剧本的断言真的会失败
#
# 用一个假 docker（改状态文件）+ 假 API/Prometheus/Alertmanager/Grafana（读同一个
# 状态文件）搭出「停容器 → 探针转红 → 熔断打开 → 告警触发 → 看板可读」的因果链，
# 再逐一破坏其中一环，确认脚本会点名失败而不是照报通过。
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DRILL="${ROOT_DIR}/scripts/drill/inject_dependency_fault.sh"
FAKE_ENV="${ROOT_DIR}/scripts/testlib/fake_fault_env.py"
FAKE_DOCKER="${ROOT_DIR}/scripts/testlib/fake_docker.py"
WORK="$(mktemp -d)"
PIDS=""

fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "ok  $*"; }
assert_eq() { [ "$1" = "$2" ] || fail "$3（期望 '$1'，实际 '$2'）"; ok "$3"; }
assert_contains() { grep -qF -- "$2" "$1" || fail "$3（在 $1 中找不到 '$2'）"; ok "$3"; }
assert_not_contains() { if grep -qF -- "$2" "$1"; then fail "$3（$1 里不应出现 '$2'）"; fi; ok "$3"; }

cleanup() {
  for pid in ${PIDS}; do
    kill "${pid}" 2>/dev/null || true
    wait "${pid}" 2>/dev/null || true
  done
  rm -rf "${WORK}"
}
trap cleanup EXIT

command -v curl >/dev/null 2>&1 || fail "缺少 curl"
command -v python3 >/dev/null 2>&1 || fail "缺少 python3"
[ -f "${DRILL}" ] || fail "找不到 ${DRILL}"
bash -n "${DRILL}" || fail "inject_dependency_fault.sh 语法错误"

# PATH 前置一个假 docker
mkdir -p "${WORK}/bin"
export FAKE_DOCKER_STATE="${WORK}/docker-state.json"
export FAKE_DOCKER_CALLS="${WORK}/docker-calls.log"
cat >"${WORK}/bin/docker" <<EOF
#!/usr/bin/env bash
exec env FAKE_DOCKER_STATE="${FAKE_DOCKER_STATE}" FAKE_DOCKER_CALLS="${FAKE_DOCKER_CALLS}" python3 "${FAKE_DOCKER}" "\$@"
EOF
chmod 0755 "${WORK}/bin/docker"
export PATH="${WORK}/bin:${PATH}"

seed_state() {  # seed_state <服务...>
  python3 - "$FAKE_DOCKER_STATE" "$@" <<'PY'
import json, sys
path = sys.argv[1]
services = sys.argv[2:]
with open(path, "w", encoding="utf-8") as handle:
    json.dump({"running": list(services)}, handle)
PY
  rm -f "${FAKE_DOCKER_CALLS}"
}

start_env() {  # start_env <mode> —— 起假故障环境并导出 URL 变量
  local mode="$1"
  local port_file="${WORK}/ports-fault-${mode}"
  rm -f "${port_file}"
  FAKE_MODE="${mode}" FAKE_DOCKER_STATE="${FAKE_DOCKER_STATE}" \
    python3 "${FAKE_ENV}" "${port_file}" &
  PIDS="${PIDS} $!"

  local waited=0
  while [ ! -s "${port_file}" ]; do
    waited=$((waited + 1))
    [ "${waited}" -gt 100 ] && fail "假故障环境在 5s 内没有就绪（mode=${mode}）"
    sleep 0.05
  done

  API_URL="http://127.0.0.1:$(awk -F= '$1=="api"{print $2}' "${port_file}")"
  PROM_URL="http://127.0.0.1:$(awk -F= '$1=="prometheus"{print $2}' "${port_file}")"
  AM_URL="http://127.0.0.1:$(awk -F= '$1=="alertmanager"{print $2}' "${port_file}")"
  GRAFANA_URL="http://127.0.0.1:$(awk -F= '$1=="grafana"{print $2}' "${port_file}")"
}

run_drill() {  # run_drill <报告目录> [额外参数...]
  local report_dir="$1"; shift
  bash "${DRILL}" \
    --api-url "${API_URL}" \
    --prometheus-url "${PROM_URL}" \
    --alertmanager-url "${AM_URL}" \
    --grafana-url "${GRAFANA_URL}" \
    --compose-file "${ROOT_DIR}/docker-compose.yml" \
    --timeout 20 \
    --report-dir "${report_dir}" \
    "$@" >"${WORK}/out" 2>&1
}

report_of() { find "$1" -name '*-dependency-fault.md' | head -1; }

# ─────────────── 1. 正常因果链 → exit 0，且真的停/起了容器 ───────────────

seed_state mongo gateway chat-api
start_env pass
set +e
run_drill "${WORK}/rep-pass"
status=$?
set -e
assert_eq 0 "${status}" "正常场景退出码为 0"
PASS_REPORT="$(report_of "${WORK}/rep-pass")"
[ -n "${PASS_REPORT}" ] || fail "没有生成报告"
assert_contains "${PASS_REPORT}" "| pass | 故障已生效" "报告记录故障已生效"
assert_contains "${PASS_REPORT}" "| pass | 快速失败返回 5xx" "报告记录快速失败"
assert_contains "${PASS_REPORT}" "| pass | 快速失败未等待超时" "报告记录未等待超时"
assert_contains "${PASS_REPORT}" "| pass | 熔断器已打开" "报告记录熔断打开"
assert_contains "${PASS_REPORT}" "| pass | 告警已触发" "报告记录告警触发"
assert_contains "${PASS_REPORT}" "| pass | 排障看板可下钻" "报告记录看板可读"
assert_contains "${PASS_REPORT}" "| pass | 恢复依赖" "报告记录依赖已恢复"
assert_contains "${PASS_REPORT}" "| pass | 熔断器已复位" "报告记录熔断复位"
assert_contains "${FAKE_DOCKER_CALLS}" "stop mongo" "真的执行了 stop mongo"
assert_contains "${FAKE_DOCKER_CALLS}" "start mongo" "真的执行了 start mongo"

# ─────────────── 2. 告警没发 → exit 1 且只点名告警 ───────────────

seed_state mongo gateway chat-api
start_env no-alert
set +e
run_drill "${WORK}/rep-noalert"
status=$?
set -e
assert_eq 1 "${status}" "告警缺失时退出码为 1"
AM_REPORT="$(report_of "${WORK}/rep-noalert")"
assert_contains "${AM_REPORT}" "**fail** | 告警已触发" "报告点名告警失败"
assert_contains "${AM_REPORT}" "| pass | 熔断器已打开" "告警失败不影响熔断判定"

# ─────────────── 3. 探针不红 → exit 1 ───────────────

seed_state mongo gateway chat-api
start_env stuck-ready
set +e
run_drill "${WORK}/rep-stuck"
status=$?
set -e
assert_eq 1 "${status}" "探针不转红时退出码为 1"
STUCK_REPORT="$(report_of "${WORK}/rep-stuck")"
assert_contains "${STUCK_REPORT}" "**fail** | 故障已生效" "报告点名故障未生效"

# ─────────────── 4. 熔断指标没打开 → exit 1 ───────────────

seed_state mongo gateway chat-api
start_env no-circuit
set +e
run_drill "${WORK}/rep-nocircuit"
status=$?
set -e
assert_eq 1 "${status}" "熔断未打开时退出码为 1"
CIRCUIT_REPORT="$(report_of "${WORK}/rep-nocircuit")"
assert_contains "${CIRCUIT_REPORT}" "**fail** | 熔断器已打开" "报告点名熔断失败"

# ─────────────── 5. --no-restore 保留现场 ───────────────

seed_state mongo gateway chat-api
start_env pass
set +e
run_drill "${WORK}/rep-keep" --no-restore
status=$?
set -e
assert_eq 0 "${status}" "--no-restore 场景退出码为 0"
KEEP_REPORT="$(report_of "${WORK}/rep-keep")"
assert_contains "${KEEP_REPORT}" "| skip | 恢复依赖" "报告标记恢复被跳过"
assert_not_contains "${FAKE_DOCKER_CALLS}" "start mongo" "--no-restore 时没有 start"

# ─────────────── 6. 只给 API 地址（其余后端缺省）→ 跳过而非假通过 ───────────────

seed_state mongo gateway chat-api
start_env pass
set +e
bash "${DRILL}" --api-url "${API_URL}" \
  --compose-file "${ROOT_DIR}/docker-compose.yml" \
  --timeout 20 --report-dir "${WORK}/rep-min" >"${WORK}/out-min" 2>&1
status=$?
set -e
assert_eq 0 "${status}" "后端缺省时仍可通过（跳过项不算失败）"
MIN_REPORT="$(report_of "${WORK}/rep-min")"
assert_contains "${MIN_REPORT}" "| skip | 熔断器已打开" "缺 Prometheus 时跳过熔断检查"
assert_contains "${MIN_REPORT}" "| skip | 告警已触发" "缺 Alertmanager 时跳过告警检查"
assert_contains "${MIN_REPORT}" "| skip | 排障看板可下钻" "缺 Grafana 时跳过看板检查"

# ─────────────── 7. 环境不具备：没有 docker → exit 2 ───────────────
#
# 注意：不能用 `PATH=<只有一个目录>` 覆盖——那样连 bash 自己都找不到（127）。
# 保留系统目录、只把假 docker 目录从 PATH 里摘掉。

set +e
PATH="/usr/bin:/bin:/usr/sbin:/sbin" bash "${DRILL}" --api-url "${API_URL}" \
  --compose-file "${ROOT_DIR}/docker-compose.yml" --report-dir "${WORK}/rep-nodocker" \
  >"${WORK}/out-nodocker" 2>&1
status=$?
set -e
assert_eq 2 "${status}" "缺少 docker 时退出码为 2"
assert_contains "${WORK}/out-nodocker" "环境不具备" "输出说明环境不具备"

# ─────────────── 8. 服务不在运行 → exit 2 ───────────────

seed_state gateway chat-api
start_env pass
set +e
run_drill "${WORK}/rep-nosvc"
status=$?
set -e
assert_eq 2 "${status}" "目标服务不在运行时退出码为 2"
assert_contains "${WORK}/out" "没有在运行" "输出指出服务不在运行"

# ─────────────── 9. 未知 target → exit 2 ───────────────

set +e
bash "${DRILL}" --target postgres --api-url "${API_URL}" >"${WORK}/out-target" 2>&1
status=$?
set -e
assert_eq 2 "${status}" "非法 target 退出码为 2"
assert_contains "${WORK}/out-target" "只支持 mongo|redis" "输出指出 target 取值"

echo "Dependency fault injection behaviour is valid."
