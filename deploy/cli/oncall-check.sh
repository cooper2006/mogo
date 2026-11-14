#!/usr/bin/env bash
# 024 T098 (FR-050)：值班表可读性 / 必填字段校验。
#
# 校验 deploy/runbook/oncall-roster.yml：
#   - 每个角色 MUST 填 name 与 contact（contact 不得为 `<...>` 占位）；
#   - 升级链 MUST 存在：oncall → backup → platform-lead → incident-commander；
#   - 至少一个角色 active=true（否则值班表形同虚设）；
#   - 响应时限与演练内拨测开关已声明。
#
# 用法：
#   deploy/cli/oncall-check.sh [--roster <file>] [--json] [--warn-empty]
#     --warn-empty  把"占位未填"降级为 WARN（CI 首次启用时可暂缓 FAIL）
#
# 退出码：0 全部 PASS（含 WARN）；1 存在 FAIL。
# 本脚本可被 mogo source 提供 mogo_oncall_check（供 ./mogo check 或 CI 复用）。

if [[ -z "${ROOT_DIR:-}" ]]; then
  ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi

mogo_oncall_check() {
  local roster="${MOGO_ONCALL_ROSTER:-${ROOT_DIR}/deploy/runbook/oncall-roster.yml}"
  local json_out=false warn_empty=false
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --roster) roster="$2"; shift 2 ;;
      --json) json_out=true; shift ;;
      --warn-empty) warn_empty=true; shift ;;
      -h|--help) echo "用法: ./mogo oncall check [--roster <file>] [--json] [--warn-empty]"; return 0 ;;
      *) printf 'FAIL 未知参数 %s\n' "$1" >&2; return 2 ;;
    esac
  done
  if [[ ! -f "${roster}" ]]; then
    printf 'FAIL 值班表 %s 不存在\n' "${roster}" >&2
    return 1
  fi
  python3 - "${roster}" "${warn_empty}" "${json_out}" <<'PY'
import json, re, sys, yaml

path, warn_empty = sys.argv[1], sys.argv[2] == "true"
json_out = sys.argv[3] == "true"
cfg = yaml.safe_load(open(path, encoding="utf-8"))
roles = cfg.get("roles", []) or []
checks = []
CHAIN = ["oncall", "backup", "platform-lead", "incident-commander"]

by_role = {r.get("role"): r for r in roles}

for role in CHAIN:
    r = by_role.get(role)
    if not r:
        checks.append({"check": f"升级链角色 {role}", "status": "FAIL",
                       "detail": "角色未登记"})
        continue
    name, contact = r.get("name", ""), r.get("contact", "")
    issues = []
    if not name or "<" in name:
        issues.append("name 未填写/占位")
    if not contact or "<" in contact:
        issues.append("contact 未填写/占位")
    if not r.get("active"):
        issues.append("active 非 true（未在岗）")
    status = "FAIL" if issues else "PASS"
    if status == "FAIL" and warn_empty:
        # 占位未填在 --warn-empty 下降级为 WARN，便于 CI 首次启用
        status = "WARN"
    checks.append({"check": f"角色 {role}", "status": status,
                   "detail": "; ".join(issues) if issues else "ok"})

# 升级链完整性
chain_ok = all(r in by_role for r in CHAIN)
checks.append({"check": "升级链 oncall→backup→lead→commander", "status": "PASS" if chain_ok else "FAIL",
               "detail": "链完整" if chain_ok else "链不完整"})

# 至少一个角色在岗
any_active = any(r.get("active") for r in roles)
checks.append({"check": "至少一个角色 active=true", "status": "PASS" if any_active else "FAIL",
               "detail": "有在岗角色" if any_active else "无人值班"})

# 响应时限
timeout = (cfg.get("reachability") or {}).get("responseTimeoutMinutes")
checks.append({"check": "响应时限 responseTimeoutMinutes", "status": "PASS" if isinstance(timeout, int) and timeout > 0 else "FAIL",
               "detail": f"{timeout} 分钟" if isinstance(timeout, int) else "未设置"})

# 演练内拨测开关
probe = (cfg.get("reachability") or {}).get("probeDuringDrill")
checks.append({"check": "演练内联系方式拨测 probeDuringDrill", "status": "PASS" if probe else "FAIL",
               "detail": "已开启" if probe else "未开启"})

failed = any(c["status"] == "FAIL" for c in checks)
if json_out:
    print(json.dumps({"roster": path, "exit": 1 if failed else 0, "results": checks},
                     ensure_ascii=False, indent=2))
else:
    print(f"值班表校验（{path}）")
    for c in checks:
        print(f"  [{c['status']}] {c['check']}  {c['detail']}")
    print("值班表校验全部 PASS" if not failed else "FAIL 值班表存在必填缺失" )
sys.exit(1 if failed else 0)
PY
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  mogo_oncall_check "$@"
fi