#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# scripts/test_full_recovery_drill.sh — 端到端恢复演练行为测试（T118）
# ═══════════════════════════════════════════════════════════════════════
#
# 覆盖：
#   1. 正常链路：全量备份 → 取最新归档 → 恢复演练 → 一致性 → RTO/RPO 报告
#   2. 服务切换检查（给了 --api-url 就真的探活）
#   3. 备份失败 → 阶段 2 被跳过，而不是「在坏归档上继续」
#   4. 恢复被截断 → 一致性校验失败并点名
#   5. 演练库与源库同名 → 拒绝
#   6. --dry-run 不落盘、不产生归档
#
# 依赖假 mongodump/mongorestore/mongosh（scripts/testlib/fake_mongo.sh）。
# 运行：bash scripts/test_full_recovery_drill.sh
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=./testlib/fake_mongo.sh
source "${ROOT_DIR}/scripts/testlib/fake_mongo.sh"

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}
ok() { printf 'ok  %s\n' "$*"; }

assert_contains() {
  local haystack="$1" needle="$2" label="$3"
  case "${haystack}" in
    *"${needle}"*) : ;;
    *) fail "${label}：在输出里找不到 '${needle}'" ;;
  esac
  ok "${label}"
}

assert_not_contains() {
  local haystack="$1" needle="$2" label="$3"
  case "${haystack}" in
    *"${needle}"*) fail "${label}：输出里不应出现 '${needle}'" ;;
  esac
  ok "${label}"
}

WORK="$(mktemp -d "${TMPDIR:-/tmp}/mogo-full-drill.XXXXXX")"
export MOGO_BACKUP_DIR="${WORK}/backups"
export MOGO_BACKUP_PASSPHRASE="test-passphrase-do-not-use-in-prod"
export MOGO_MONGODB_URI="mongodb://mongo:27017"
REPORT_DIR="${WORK}/reports"
API_LOG="${WORK}/api.log"
API_PID=""

fake_mongo_init
PATH="${FAKE_MONGO_BIN}:${PATH}"
export PATH

cleanup() {
  if [[ -n "${API_PID}" ]]; then kill "${API_PID}" 2>/dev/null || true; wait "${API_PID}" 2>/dev/null || true; fi
  fake_mongo_cleanup
  rm -rf "${WORK}"
}
trap cleanup EXIT

# 一个极小假 API：/ready 永远 200，用来验证「服务切换检查」真的发请求
start_fake_api() {
  python3 - "${API_LOG}" <<'PY' &
import http.server, sys, threading

LOG = sys.argv[1]
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b'{"status":"ok"}'
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(self.path + "\n")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass

http.server.ThreadingHTTPServer(("127.0.0.1", 18081), H).serve_forever()
PY
  API_PID=$!
  local waited=0
  while ! curl -fsS -m 2 -o /dev/null "http://127.0.0.1:18081/ready" 2>/dev/null; do
    waited=$((waited + 1))
    [[ "${waited}" -gt 100 ]] && fail "假 API 没起来"
    sleep 0.05
  done
}

run_drill() {  # run_drill <报告目录> [额外参数...]
  local report_dir="$1"; shift
  bash "${ROOT_DIR}/scripts/drill/full_recovery_drill.sh" \
    --report-dir "${report_dir}" "$@"
}

report_of() { find "$1" -name '*-full-recovery.md' | head -1; }

# ── 1. 正常链路 ─────────────────────────────────────────
printf '== 正常链路 ==\n'
fake_mongo_seed '{"mogo": {"users": ["u1", "u2", "u3"], "posts": ["p1", "p2"]}}'
out="$(run_drill "${REPORT_DIR}/ok" 2>&1)" || fail "正常演练失败：${out}"
REPORT="$(report_of "${REPORT_DIR}/ok")"
[[ -n "${REPORT}" ]] || fail "没有生成报告：${out}"
assert_contains "${out}" "端到端恢复演练通过" "演练结论为通过"
assert_contains "$(cat "${REPORT}")" "| pass | 阶段 1 全量备份" "报告记录阶段 1 备份"
assert_contains "$(cat "${REPORT}")" "| pass | 取到最新归档" "报告记录取到归档"
assert_contains "$(cat "${REPORT}")" "| pass | 阶段 2 恢复演练" "报告记录阶段 2 恢复"
assert_contains "$(cat "${REPORT}")" "| pass | 记录 RTO/RPO" "报告记录 RTO/RPO"
assert_contains "$(cat "${REPORT}")" "| pass | 数据一致性" "报告记录一致性通过"
assert_contains "$(cat "${REPORT}")" "| skip | 阶段 3 服务切换检查" "未给 --api-url 时切换检查标 skip"
assert_not_contains "$(cat "${REPORT}")" "**fail**" "正常链路报告里没有 fail"

# ── 2. 服务切换检查：给了 --api-url 就真的探活 ─────────────
printf '== 服务切换检查 ==\n'
start_fake_api
fake_mongo_seed '{"mogo": {"users": ["u1", "u2", "u3"], "posts": ["p1", "p2"]}}'
: >"${API_LOG}"
out2="$(run_drill "${REPORT_DIR}/switch" --api-url "http://127.0.0.1:18081" 2>&1)" || fail "带 --api-url 的演练失败：${out2}"
REPORT2="$(report_of "${REPORT_DIR}/switch")"
assert_contains "$(cat "${REPORT2}")" "| pass | 阶段 3 服务切换检查" "报告记录切换检查通过"
assert_contains "$(cat "${API_LOG}")" "/ready" "真的向服务发起了 /ready 探测"

# ── 3. 备份失败 → 阶段 2 被跳过 ─────────────────────────
printf '== 备份失败 ==\n'
fake_mongo_seed '{"mogo": {"users": ["u1"]}}'
set +e
FAKE_DUMP_FAIL=1 bash "${ROOT_DIR}/scripts/drill/full_recovery_drill.sh" \
  --report-dir "${REPORT_DIR}/dumpfail" >"${WORK}/dumpfail.log" 2>&1
status=$?
set -e
[[ "${status}" -eq 1 ]] || fail "备份失败时应 exit 1，实际 ${status}"
assert_contains "$(cat "$(report_of "${REPORT_DIR}/dumpfail")")" "**fail** | 阶段 1 全量备份" "报告点名备份失败"
assert_contains "$(cat "$(report_of "${REPORT_DIR}/dumpfail")")" "| skip | 阶段 2 恢复演练" "备份失败时跳过阶段 2"

# ── 4. 恢复被截断 → 一致性失败 ──────────────────────────
printf '== 恢复截断 ==\n'
fake_mongo_seed '{"mogo": {"users": ["u1", "u2", "u3"], "posts": ["p1", "p2"]}}'
set +e
FAKE_RESTORE_TRUNCATE=1 bash "${ROOT_DIR}/scripts/drill/full_recovery_drill.sh" \
  --report-dir "${REPORT_DIR}/truncate" >"${WORK}/truncate.log" 2>&1
status=$?
set -e
[[ "${status}" -eq 1 ]] || fail "恢复截断时应 exit 1，实际 ${status}"
assert_contains "$(cat "$(report_of "${REPORT_DIR}/truncate")")" "**fail** | 数据一致性" "报告点名一致性失败"

# ── 5. 演练库与源库同名 → 拒绝 ──────────────────────────
printf '== 同名库拒绝 ==\n'
fake_mongo_seed '{"mogo": {"users": ["u1"]}}'
set +e
bash "${ROOT_DIR}/scripts/drill/full_recovery_drill.sh" \
  --db mogo --drill-db mogo --report-dir "${REPORT_DIR}/same" >"${WORK}/same.log" 2>&1
status=$?
set -e
[[ "${status}" -eq 2 ]] || fail "同名库应 exit 2，实际 ${status}"
assert_contains "$(cat "${WORK}/same.log")" "不能与源库同名" "输出说明拒绝原因"

# ── 6. --dry-run 不落盘 ─────────────────────────────────
printf '== dry-run ==\n'
fake_mongo_seed '{"mogo": {"users": ["u1"]}}'
files_before="$(find "${MOGO_BACKUP_DIR}" -type f | sort)"
out3="$(bash "${ROOT_DIR}/scripts/drill/full_recovery_drill.sh" \
  --report-dir "${REPORT_DIR}/dry" --dry-run 2>&1)" || fail "dry-run 应成功"
assert_contains "${out3}" "dry-run: 将执行 1)" "dry-run 打印步骤 1"
assert_contains "${out3}" "dry-run: 将执行 3)" "dry-run 打印步骤 3"
[[ -z "$(find "${REPORT_DIR}/dry" -type f 2>/dev/null || true)" ]] || fail "dry-run 不应生成报告"
[[ "$(find "${MOGO_BACKUP_DIR}" -type f | sort)" == "${files_before}" ]] || fail "dry-run 不应产生归档"
ok "dry-run 不落盘"

printf 'Full recovery drill behaviour is valid.\n'
