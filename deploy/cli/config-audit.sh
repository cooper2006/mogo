#!/usr/bin/env bash
# 024 T023 (FR-009)：配置变更审计。
#
# 每次 deploy/config/ 变更（含回滚）调用本脚本记录：
#   操作者 / 原因 / 影响服务 / 回滚方案 / commit / lint 结果。
# 双写落点：
#   1) 本地 `deploy/config/.config-audit.jsonl`（git 版本控制，可追溯、离线可用）；
#   2) 若 admin-api 可导入且 MongoDB 可达，同时写入 001 gatekeeper-governance 的
#      `system_audit`（单一审计落点），失败仅告警不阻断。
#
# 用法：
#   deploy/cli/config-audit.sh --action <change|rollback> --reason "<原因>" \
#     [--affected <服务列表>] [--rollback-ref <ref>] [--skip-lint]
# 退出码：0 = 记录成功（含落本地文件）；1 = 记录失败。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_DIR="${ROOT_DIR}/deploy/config"
AUDIT_LOG="${CONFIG_DIR}/.config-audit.jsonl"
LINT_SCRIPT="${ROOT_DIR}/deploy/cli/config-lint.sh"

ACTION=""
REASON=""
AFFECTED=""
ROLLBACK_REF=""
SKIP_LINT=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --action) ACTION="$2"; shift 2 ;;
    --reason) REASON="$2"; shift 2 ;;
    --affected) AFFECTED="$2"; shift 2 ;;
    --rollback-ref) ROLLBACK_REF="$2"; shift 2 ;;
    --skip-lint) SKIP_LINT=true; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "${ACTION}" || -z "${REASON}" ]]; then
  echo "config-audit: 需要 --action 与 --reason" >&2
  exit 2
fi

mkdir -p "${CONFIG_DIR}"

operator="$(git -C "${ROOT_DIR}" config user.name 2>/dev/null || echo "unknown")"
commit="$(git -C "${ROOT_DIR}" rev-parse --short HEAD 2>/dev/null || echo "dirty")"
timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# 跑一遍 config-lint 作为审计快照
lint_result="skipped"
if [[ "${SKIP_LINT}" != "true" && -x "${LINT_SCRIPT}" ]]; then
  if bash "${LINT_SCRIPT}" --env all >/dev/null 2>&1; then
    lint_result="pass"
  else
    lint_result="fail"
  fi
fi

rollback_plan="git log --oneline -- deploy/config; git checkout <ref> -- deploy/config/; ./mogo up -d"
if [[ "${ACTION}" == "rollback" && -n "${ROLLBACK_REF}" ]]; then
  rollback_plan="rollback-to:${ROLLBACK_REF}; 回滚方案: 再执行 ./mogo config rollback <上一个 ref>"
fi

record="$(
  python3 -c '
import json, sys
doc = {
    "module": "deploy.config",
    "action": sys.argv[1],
    "operator": sys.argv[2],
    "occurred_at": sys.argv[3],
    "commit": sys.argv[4],
    "reason": sys.argv[5],
    "affected_services": (sys.argv[6].split(",") if sys.argv[6] else []),
    "rollback_ref": sys.argv[7] or None,
    "rollback_plan": sys.argv[8],
    "lint_result": sys.argv[9],
}
print(json.dumps(doc, ensure_ascii=False))
' "${ACTION}" "${operator}" "${timestamp}" "${commit}" \
  "${REASON}" "${AFFECTED}" "${ROLLBACK_REF}" "${rollback_plan}" "${lint_result}"
)"

echo "${record}" >> "${AUDIT_LOG}"
echo "config-audit: 已写入 ${AUDIT_LOG}"

# 尝试接入 001 gatekeeper-governance 的 system_audit（单一审计落点）
if [[ -d "${ROOT_DIR}/services/admin-api/app/system_audit" ]]; then
  set +e
  AUDIT_RECORD="${record}" PYTHONPATH="${ROOT_DIR}/services/admin-api" \
    python3 - <<'PY' >/dev/null 2>&1
import asyncio, json, os
from system_audit.repository import SystemAuditRepository

async def main():
    doc = json.loads(os.environ["AUDIT_RECORD"])
    repo = SystemAuditRepository()
    doc["tenant_id"] = doc.get("tenant_id", "platform")
    doc["result"] = "ok" if doc.get("lint_result") == "pass" else "attention"
    await repo.record_management_operation(doc)

asyncio.run(main())
PY
  rc=$?
  set -e
  if [[ ${rc} -eq 0 ]]; then
    echo "config-audit: 审计事件已写入 system_audit"
  else
    echo "config-audit: 警告 — admin-api/MongoDB 不可达，审计仅落本地 ${AUDIT_LOG}" >&2
  fi
fi