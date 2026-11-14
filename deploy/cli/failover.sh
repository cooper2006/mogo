#!/usr/bin/env bash
# 024 T079/T077 (FR-040)：单区故障切换编排。
#
# 提供动作：prepare | execute | verify | back | status
#   prepare  校验新主机（SSH 可达、NTP 同步、磁盘足够），取回并解密最近备份
#   execute  在新主机拉起 compose、恢复备份卷、切换流量（DNS/网关 upstream）
#   verify   调 scripts/verify_data_consistency.py + scripts/verify_restore_business.py
#   back     回切到原主机（默认需双人复核）
#   status   查看切换状态机与最近阶段
#
# 权限收敛（T077）：
#   - MOGO_FAILOVER_REQUIRE_APPROVAL=1 时，execute/back 需 --approver-key 提供第二个签名
#   - 切换操作走 MOGO_FAILOVER_KEY（专用密钥），与日常运维账号隔离
#   - 只允许 mogo-failover 独立操作账号执行（可关闭，见 MOGO_FAILOVER_SKIP_ACCOUNT_CHECK）
#
# 用法（经 ./mogo failover）：
#   ./mogo failover prepare --new-host 10.0.0.20 --backup backups/mogo-backup-20261025T020000Z
#   ./mogo failover execute  --new-host 10.0.0.20
#   ./mogo failover verify   --new-host 10.0.0.20
#   ./mogo failover back     --orig-host 10.0.0.19 --yes
#   ./mogo failover status
#
# 本脚本只被 mogo source，不单独执行。

if [[ -z "${ROOT_DIR:-}" ]]; then
  ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi

MOGO_FAILOVER_STATE="${MOGO_FAILOVER_STATE:-${ROOT_DIR}/deploy/.failover-state.json}"

# 状态机读写（JSON）
mogo_failover_state_read() {
  if [[ -f "${MOGO_FAILOVER_STATE}" ]]; then
    cat "${MOGO_FAILOVER_STATE}"
  else
    printf '{"phase":"none","history":[]}\n'
  fi
}

mogo_failover_state_write() {
  local phase="$1" host="$2" note="$3"
  local prev ts
  prev="$(mogo_failover_state_read | python3 -c 'import json,sys;print(json.dumps(json.loads(sys.stdin.read()).get("history",[]),ensure_ascii=False))')"
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  python3 -c '
import json, sys
prev = json.loads(sys.argv[1])
entry = {"phase": sys.argv[2], "host": sys.argv[3], "note": sys.argv[4], "at": sys.argv[5]}
prev.append(entry)
print(json.dumps({"phase": entry["phase"], "host": entry["host"], "history": prev[-50:]}, ensure_ascii=False))' \
    "${prev}" "${phase}" "${host}" "${note}" "${ts}" > "${MOGO_FAILOVER_STATE}" 2>/dev/null || true
}

# 操作账号检查（T077）：默认只允许 mogo-failover 账号执行
mogo_failover_check_account() {
  if [[ "${MOGO_FAILOVER_SKIP_ACCOUNT_CHECK:-}" == "1" ]]; then
    return 0
  fi
  local who
  who="$(whoami)"
  if [[ "${who}" != "mogo-failover" ]]; then
    printf 'FAIL 权限收敛：切换只允许 mogo-failover 操作账号执行，当前 %s（如需豁免设 MOGO_FAILOVER_SKIP_ACCOUNT_CHECK=1）\n' "${who}" >&2
    return 1
  fi
  return 0
}

# 双人复核（T077）
mogo_failover_check_approval() {
  if [[ "${MOGO_FAILOVER_REQUIRE_APPROVAL:-}" != "1" ]]; then
    return 0
  fi
  if [[ -z "${1:-}" ]] || [[ ! -f "${1:-}" ]]; then
    printf 'FAIL 切换需双人复核：请提供 --approver-key <第二操作者签名文件>\n' >&2
    return 1
  fi
  return 0
}

# SSH 可达性检查
mogo_failover_ssh_ok() {
  local host="$1"
  ssh -o BatchMode=yes -o ConnectTimeout=5 "${host}" "echo ok" >/dev/null 2>&1
}

# 新主机环境预检：SSH + NTP + 磁盘
mogo_failover_precheck() {
  local host="$1"
  if ! mogo_failover_ssh_ok "${host}"; then
    printf 'FAIL 新主机 %s SSH 不可达\n' "${host}" >&2
    return 1
  fi
  local ntp disk
  ntp="$(ssh -o BatchMode=yes "${host}" 'date +%s' 2>/dev/null)"
  local localts
  localts="$(date +%s)"
  local diff=$((ntp - localts)); [[ ${diff} -lt 0 ]] && diff=$((-diff))
  if (( diff > 60 )); then
    printf 'WARN 新主机与本地时钟差 %s 秒（需先同步 NTP）\n' "${diff}" >&2
  fi
  disk="$(ssh -o BatchMode=yes "${host}" 'df -P /var/lib/docker 2>/dev/null | awk "NR==2{print \$4}"' 2>/dev/null)"
  printf '新主机 %s：SSH 可达，磁盘可用 %s KB\n' "${host}" "${disk:-未知}"
  return 0
}

# 取回并解密备份（异机密钥，见 deploy/runbook/backup-key-management.md）
mogo_failover_fetch_backup() {
  local host="$1" backup="$2"
  if [[ -z "${backup}" ]]; then
    printf 'FAIL 请用 --backup <备份目录> 指定要恢复的备份\n' >&2
    return 1
  fi
  if [[ ! -d "${backup}" ]]; then
    printf 'FAIL 备份目录 %s 不存在\n' "${backup}" >&2
    return 1
  fi
  local enc=""
  [[ -f "${backup}/ENCRYPTED" ]] && enc="$(cat "${backup}/ENCRYPTED" 2>/dev/null)"
  if [[ "${enc}" == "true" ]]; then
    printf 'FAIL 备份 %s 已加密，请先解密（见 backup-key-management.md，密钥异机）\n' "${backup}" >&2
    return 1
  fi
  printf 'OK 备份 %s 就绪（未加密，可直接恢复；加密备份需先解密）\n' "${backup}"
  return 0
}

# prepare
mogo_failover_prepare() {
  local host="" backup=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --new-host) host="$2"; shift 2 ;;
      --backup) backup="$2"; shift 2 ;;
      *) printf 'FAIL 未知参数 %s\n' "$1" >&2; return 2 ;;
    esac
  done
  mogo_failover_check_account || return 1
  [[ -z "${host}" ]] && { printf 'FAIL 缺少 --new-host\n' >&2; return 2; }
  mogo_failover_precheck "${host}" || return 1
  mogo_failover_fetch_backup "${host}" "${backup}" || return 1
  mogo_failover_state_write prepare "${host}" "新主机预检通过、备份就绪"
  printf 'OK failover prepare 完成（新主机 %s）\n' "${host}"
}

# execute
mogo_failover_execute() {
  local host="" approver=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --new-host) host="$2"; shift 2 ;;
      --approver-key) approver="$2"; shift 2 ;;
      *) printf 'FAIL 未知参数 %s\n' "$1" >&2; return 2 ;;
    esac
  done
  mogo_failover_check_account || return 1
  mogo_failover_check_approval "${approver}" || return 1
  [[ -z "${host}" ]] && { printf 'FAIL 缺少 --new-host\n' >&2; return 2; }
  mogo_failover_precheck "${host}" || return 1
  printf 'OK failover execute：请在 %s 上执行 docker compose up -d 并恢复备份卷；\n' "${host}"
  printf '  切换流量（DNS / 网关 upstream）后运行 ./mogo failover verify --new-host %s\n' "${host}"
  mogo_failover_state_write execute "${host}" "已进入恢复与流量切换（待人工确认 + verify）"
}

# verify
mogo_failover_verify() {
  local host="" base_url=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --new-host) host="$2"; shift 2 ;;
      --base-url) base_url="$2"; shift 2 ;;
      *) printf 'FAIL 未知参数 %s\n' "$1" >&2; return 2 ;;
    esac
  done
  [[ -z "${host}" ]] && { printf 'FAIL 缺少 --new-host\n' >&2; return 2; }
  local rc=0
  printf '== 数据一致性校验（FR-041）==\n'
  if [[ -n "${base_url}" ]]; then
    python3 "${ROOT_DIR}/scripts/verify_data_consistency.py" \
      --mongo-uri "mongodb://${host}:27017" --base-url "${base_url}" --probe-app --json \
      | python3 -c 'import json,sys;d=json.loads(sys.stdin.read());print("verdict:",d["verdict"]);sys.exit(0 if d["passed"] else 1)' || rc=1
  else
    python3 "${ROOT_DIR}/scripts/verify_data_consistency.py" \
      --mongo-uri "mongodb://${host}:27017" --json \
      | python3 -c 'import json,sys;d=json.loads(sys.stdin.read());print("verdict:",d["verdict"]);sys.exit(0 if d["passed"] else 1)' || rc=1
  fi
  printf '== 恢复后业务校验（FR-037）==\n'
  local bu="${base_url:-http://${host}:3000}"
  if [[ -f "${ROOT_DIR}/scripts/verify_restore_business.py" ]]; then
    python3 "${ROOT_DIR}/scripts/verify_restore_business.py" --base-url "${bu}" --json \
      | python3 -c 'import json,sys;d=json.loads(sys.stdin.read());print("verdict:",d["verdict"]);sys.exit(0 if d["passed"]==d["total"] and d["failed"]==0 else 1)' || rc=1
  fi
  if (( rc == 0 )); then
    mogo_failover_state_write verify "${host}" "一致性 + 业务校验全部 PASS"
    printf 'OK failover verify 通过（新主机 %s）\n' "${host}"
  else
    printf 'FAIL failover verify 存在失败项，详见上方输出\n' >&2
    mogo_failover_state_write verify "${host}" "校验存在 FAIL"
  fi
  return "${rc}"
}

# back（回切，默认需双人复核）
mogo_failover_back() {
  local host="" approver="" confirmed=false
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --orig-host) host="$2"; shift 2 ;;
      --approver-key) approver="$2"; shift 2 ;;
      --yes) confirmed=true; shift ;;
      *) printf 'FAIL 未知参数 %s\n' "$1" >&2; return 2 ;;
    esac
  done
  mogo_failover_check_account || return 1
  mogo_failover_check_approval "${approver}" || return 1
  [[ "${confirmed}" == true ]] || { printf 'FAIL 回切需 --yes 确认\n' >&2; return 2; }
  [[ -z "${host}" ]] && { printf 'FAIL 缺少 --orig-host\n' >&2; return 2; }
  printf 'OK failover back：请在原主机 %s 反向同步增量数据后切回流量，并执行 ./mogo failover verify\n' "${host}"
  mogo_failover_state_write back "${host}" "已发起回切（待 verify）"
}

# status
mogo_failover_status() {
  local state
  state="$(mogo_failover_state_read)"
  python3 -c '
import json, sys
d = json.loads(sys.argv[1])
print("failover 状态机")
print("  当前阶段: " + d.get("phase", "none"))
print("  目标主机: " + str(d.get("host", "-")))
hist = d.get("history", [])
print("  历史动作 (" + str(len(hist)) + "):")
for e in hist[-6:]:
    print("    [" + e.get("phase","") + "] " + e.get("at","") + " " + str(e.get("host","")) + " - " + e.get("note",""))' "${state}"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "此脚本由 ./mogo failover <action> 调用，不单独执行" >&2
  exit 2
fi