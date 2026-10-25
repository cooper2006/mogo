#!/usr/bin/env bash
# 024 T091/T092 (FR-046/FR-048)：证书到期检查 + 证书链校验 + 外部拨测。
#
# 动作：
#   list   列出 inventory.yml 各域名到期信息
#   check  对每个域名做证书链校验 + 到期天数计算 + 外部拨测，回写 probeStatus
#
# 外部拨测（T092）：默认用 `dig @1.1.1.1`（公共 DNS over TCP，绕过内部 /etc/hosts）
# 解析真实 A 记录，再对该外部 IP 建立 TLS 连接校验证书链，结果写入 inventory.yml
# 的 probeStatus（--write-probe-status 开启回写）。
#
# 用法（经 ./mogo cert）：
#   ./mogo cert list
#   ./mogo cert check [--port 443] [--write-probe-status] [--resolver 1.1.1.1] [--json]
#
# 退出码：0 全部通过；1 存在 WARN/CRIT（到期临近或证书链失败）。
# 本脚本只被 mogo source，不单独执行。

if [[ -z "${ROOT_DIR:-}" ]]; then
  ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi

INVENTORY="${MOGO_CERT_INVENTORY:-${ROOT_DIR}/deploy/certs/inventory.yml}"

# 解析 inventory.yml 到临时 JSON
mogo_cert_load() {
  python3 - "${INVENTORY}" <<'PY'
import json, sys, yaml
path = sys.argv[1]
cfg = yaml.safe_load(open(path))
out = {
  "alert": cfg.get("alert", {}),
  "domains": [{"domain": d.get("domain",""), "owner": d.get("owner",""),
               "purpose": d.get("purpose",""), "expiry": d.get("expiry",""),
               "renewMethod": d.get("renewMethod",""), "tls": d.get("tls", True),
               "probeStatus": d.get("probeStatus","unknown")}
              for d in cfg.get("domains", [])]
}
print(json.dumps(out, ensure_ascii=False, default=str))
PY
}

# 单个域名的 TLS 探测：返回 到期日期 / 剩余天数 / 链验证结论
mogo_cert_probe() {
  local host="$1" port="${2:-443}"
  python3 - "$host" "$port" <<'PY'
import socket, ssl, sys
host = sys.argv[1]
port = int(sys.argv[2])
enddate = ""
verify = "-1"
chain = 0
try:
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=10) as raw:
        with ctx.wrap_socket(raw, server_hostname=host) as ss:
            cert = ss.getpeercert()
            if cert:
                enddate = cert.get("notAfter", "")
                verify = "0"
            try:
                if hasattr(ss, "get_unverified_chain"):
                    chain = len(ss.get_unverified_chain())
            except Exception:
                chain = 0
except ssl.SSLCertVerificationError:
    verify = "-2"
except Exception:
    verify = "-1"
if enddate:
    try:
        import datetime
        d = datetime.datetime.strptime(enddate, "%b %d %H:%M:%S %Y %Z")
        enddate = d.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        pass
print(enddate + "|" + verify + "|" + str(chain))
PY
}

# 剩余天数（按本地时间）
mogo_cert_days_left() {
  python3 - "$1" <<'PY'
import sys, datetime
raw = sys.argv[1].strip()
if not raw:
    print("unknown"); sys.exit(0)
d = datetime.datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z") if "% " in raw else None
if d is None:
    try:
        d = datetime.datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        print("unknown"); sys.exit(0)
left = (d - datetime.datetime.now()).days
print(left)
PY
}

# 用公共 DNS（TCP 直连）解析外部 A 记录，绕内部 hosts
mogo_cert_external_ip() {
  local domain="$1" resolver="${2:-1.1.1.1}"
  dig "@${resolver}" "${domain}" +tcp +short A 2>/dev/null | awk '{print $NF}' | head -1
}

# 回写 probeStatus 到 inventory.yml
mogo_cert_write_status() {
  local results="$1"
  python3 - "${INVENTORY}" "${results}" <<'PY'
import json, sys, yaml
path = sys.argv[1]
status = json.loads(sys.argv[2])
cfg = yaml.safe_load(open(path))
for d in cfg.get("domains", []):
    if d.get("domain") in status:
        d["probeStatus"] = status[d["domain"]]
    d.setdefault("probeCheckedAt", "")
for d in cfg.get("domains", []):
    if d.get("domain") in status:
        import datetime
        d["probeCheckedAt"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
with open(path, "w") as f:
    yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
print("updated")
PY
}

mogo_cert_list() {
  local json
  json="$(mogo_cert_load)"
  python3 - "${json}" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
print("证书清单 (inventory.yml)")
for dm in d["domains"]:
    print(f"  - {dm["domain"]} owner={dm["owner"]} expiry={dm["expiry"]} "
          f"tls={str(dm["tls"]).lower()} probe={dm["probeStatus"]}")
print("告警阈值: 剩余<=%s 天告警, <=%s 天 critical, 外部拨测=%s" % (
    d["alert"].get("daysBeforeExpiry",30), d["alert"].get("daysBeforeCritical",7),
    d["alert"].get("probeFromExternal",True)))
PY
}

mogo_cert_check() {
  local port=443 write_status=false resolver=1.1.1.1 json_out=false
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --port) port="$2"; shift 2 ;;
      --write-probe-status) write_status=true; shift ;;
      --resolver) resolver="$2"; shift 2 ;;
      --json) json_out=true; shift ;;
      -h|--help) echo "用法: cert check [--port 443] [--write-probe-status] [--resolver 1.1.1.1] [--json]"; return 0 ;;
      *) printf 'FAIL 未知参数 %s\n' "$1" >&2; return 2 ;;
    esac
  done
  if ! command -v openssl >/dev/null 2>&1; then
    printf 'FAIL 需要 openssl\n' >&2; return 2
  fi
  local inv warn_after crit_after
  inv="$(mogo_cert_load)"
  warn_after="$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["alert"].get("daysBeforeExpiry",30))' "${inv}")"
  crit_after="$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["alert"].get("daysBeforeCritical",7))' "${inv}")"

  local status_json="{}" rows="" any_fail=0
  while IFS='|' read -r domain owner purpose expiry renew probe; do
    [[ -z "${domain}" ]] && continue
    # 外部拨测：先解析外部 IP，再对 IP 建立 TLS（T092）
    local ip=""
    if [[ "${resolver}" != "none" ]]; then
      ip="$(mogo_cert_external_ip "${domain}" "${resolver}")"
    fi
    local probe_host="${ip:-${domain}}"
    local detail
    detail="$(mogo_cert_probe "${probe_host}" "${port}")"
    local enddate verify chain
    enddate="$(printf '%s\n' "${detail}" | cut -d'|' -f1)"
    verify="$(printf '%s\n' "${detail}" | cut -d'|' -f2)"
    chain="$(printf '%s\n' "${detail}" | cut -d'|' -f3)"

    local level="PASS" left="unknown"
    if [[ "${verify}" == "0" ]]; then
      left="$(mogo_cert_days_left "${enddate}")"
      if [[ "${left}" == "unknown" ]]; then
        level="FAIL"
      elif (( left <= crit_after )); then
        level="CRIT"
      elif (( left <= warn_after )); then
        level="WARN"
      fi
    else
      level="FAIL"
    fi

    # 链长度：证书数 >=2 视为链完整（叶 + 中间），否则标注
    local chainnote=""
    if [[ "${chain}" -ge 1 ]]; then
      chainnote="链 ${chain} 段"
    else
      chainnote="无证书"
    fi

    rows+="${domain}|${level}|${left}|${enddate}|${verify}|${chainnote}|${probe_host}\n"
    if [[ "${level}" != "PASS" ]]; then any_fail=1; fi
    status_json="$(python3 -c 'import json,sys;a=json.loads(sys.argv[1]);a[sys.argv[2]]=sys.argv[3];print(json.dumps(a))' "${status_json}" "${domain}" "${level}")"
  done < <(printf '%s' "${inv}" | python3 -c '
import json, sys
d = json.loads(sys.stdin.read())
for dm in d["domains"]:
    if dm.get("tls"):
        print("|".join([dm["domain"], dm["owner"], dm["purpose"], dm["expiry"], dm["renewMethod"], dm["probeStatus"]]))
')

  if [[ "${write_status}" == true ]]; then
    mogo_cert_write_status "${status_json}" >/dev/null
  fi

  if [[ "${json_out}" == true ]]; then
    python3 - "$(printf '%b' "${rows}")" "${port}" "${warn_after}" "${crit_after}" "${any_fail}" <<'PY'
import json, sys
rows = []
for line in sys.argv[1].splitlines():
    if not line: continue
    p = line.split("|")
    rows.append({"domain": p[0], "level": p[1], "daysLeft": p[2], "notAfter": p[3],
                 "verifyCode": p[4], "chain": p[5], "probedHost": p[6]})
print(json.dumps({"port": sys.argv[2], "warnDays": sys.argv[3], "critDays": sys.argv[4],
                  "exit": sys.argv[5], "results": rows}, ensure_ascii=False, indent=2))
PY
  else
    printf '证书检查（外部拨测 resolver=%s）\n' "${resolver}"
    printf '  阈值: WARN<=%s 天, CRIT<=%s 天\n' "${warn_after}" "${crit_after}"
    while IFS='|' read -r domain level left enddate verify chain probe_host; do
      [[ -z "${domain}" ]] && continue
      printf '  [%s] %s 剩余%s天 notAfter=%s 验证码=%s %s (拨测 %s)\n' \
        "${level}" "${domain}" "${left}" "${enddate:-?}" "${verify:-?}" "${chain}" "${probe_host}"
    done < <(printf '%b' "${rows}")
    if (( any_fail == 0 )); then
      printf '证书检查全部 PASS\n'
    else
      printf 'FAIL 存在证书告警/失败项\n' >&2
    fi
  fi
  return "${any_fail}"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "此脚本由 ./mogo cert <action> 调用，不单独执行" >&2
  exit 2
fi
