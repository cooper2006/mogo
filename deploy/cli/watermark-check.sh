#!/usr/bin/env bash
# 024 T103 (FR-049)：容量水位检查。
# 读取 deploy/monitoring/watermarks.yml，逐项本地采样并与阈值比较。
#
# 用法（经 ./mogo monitor）：
#   ./mogo monitor                       # 文本输出
#   ./mogo monitor --json                # JSON 输出（供告警/CI 消费）
#   ./mogo monitor --watermarks <file>   # 指定水位文件
#
# 退出码：0 全部 PASS；1 存在 WARN；2 存在 CRIT。
# 本脚本只被 mogo source，不单独执行（单独执行打印用法）。

if [[ -z "${ROOT_DIR:-}" ]]; then
  ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi

DEFAULT_WATERMARKS="${MOGO_WATERMARKS_FILE:-${ROOT_DIR}/deploy/monitoring/watermarks.yml}"

# 读水位文件，输出 JSON 数组（每项含 key/label/metric/value/unit/warn/crit/direction）
mogo_watermark_load() {
  local file="$1"
  python3 - "$file" <<'PY'
import json, sys, yaml
path = sys.argv[1]
cfg = yaml.safe_load(open(path))
out = []
for w in cfg.get("watermarks", []):
    out.append({
        "key": w.get("key"), "label": w.get("label", w.get("key")),
        "metric": w.get("metric"), "value": w.get("value"),
        "unit": w.get("unit", ""), "warn": w.get("warn"),
        "crit": w.get("crit"), "direction": w.get("direction", "max"),
        "source": w.get("source", ""),
    })
print(json.dumps(out, ensure_ascii=False))
PY
}

# ---- 各项采样函数（返回数字或空串表示不可测）----

mogo_watermark_sample_memory() {
  # 返回 0-100 的已用百分比
  if command -v free >/dev/null 2>&1; then
    local total used
    read -r total used <<<"$(free -m | awk '/^Mem:/{print $2, $3}')"
    [[ -z "${total}" || "${total}" -eq 0 ]] && return 1
    awk -v u="${used}" -v t="${total}" 'BEGIN{printf "%.0f", u*100/t}'
    return 0
  fi
  if command -v sysctl >/dev/null 2>&1 && sysctl -n vm.page_pageable_internal_count >/dev/null 2>&1; then
    local total used
    total="$(sysctl -n hw.memsize)"
    used="$(sysctl -n vm.page_pageable_internal_count)"
    awk -v u="${used}" -v t="${total}" 'BEGIN{printf "%.0f", u*100/t}'
    return 0
  fi
  return 1
}

mogo_watermark_sample_cpu() {
  # load average / 核数 → 百分比
  local load ncpu
  if [[ -r /proc/loadavg ]]; then
    load="$(awk '{print $1}' /proc/loadavg)"
  elif command -v sysctl >/dev/null 2>&1; then
    load="$(sysctl -n vm.loadavg 2>/dev/null | awk '{print $2}')"
  else
    return 1
  fi
  ncpu="$(mogo_watermark_cpu_count)"
  [[ -z "${ncpu}" || "${ncpu}" -eq 0 ]] && return 1
  awk -v l="${load}" -v n="${ncpu}" 'BEGIN{printf "%.0f", l*100/n}'
}

mogo_watermark_cpu_count() {
  if [[ -r /proc/cpuinfo ]]; then
    grep -c ^processor /proc/cpuinfo
  elif command -v sysctl >/dev/null 2>&1; then
    sysctl -n hw.ncpu
  fi
}

mogo_watermark_sample_disk() {
  # $1 = 目标路径；返回该盘使用率百分比
  local target="${1:-/}"
  local pct
  pct="$(df -h "${target}" 2>/dev/null | awk 'NR==2{gsub("%","",$5);print $5}')"
  [[ -z "${pct}" ]] && return 1
  printf '%s' "${pct}"
}

mogo_watermark_sample_backup_count() {
  # 统计 backups/ 下的日期目录数量
  local dir="${1:-${ROOT_DIR}/backups}"
  if [[ ! -d "${dir}" ]]; then
    printf '0'
    return 0
  fi
  find "${dir}" -maxdepth 1 -type d -name '2????-??-??' 2>/dev/null | wc -l | tr -d ' '
}

mogo_watermark_sample_backup_size() {
  # 最新备份目录的字节大小
  local dir="${1:-${ROOT_DIR}/backups}"
  local latest
  latest="$(find "${dir}" -maxdepth 1 -type d -name '2????-??-??' 2>/dev/null | sort -r | head -1)"
  [[ -z "${latest}" ]] && { printf '0'; return 0; }
  du -sb "${latest}" 2>/dev/null | awk '{print $1}'
}

mogo_watermark_sample_logs() {
  local dir="${1:-${ROOT_DIR}/logs}"
  if [[ ! -d "${dir}" ]]; then
    printf '0'
    return 0
  fi
  du -sb "${dir}" 2>/dev/null | awk '{print $1}'
}

# MongoDB 连接数（占 max_connections 百分比）；无 mongosh / 连不上返回空 → UNKNOWN
mogo_watermark_sample_mongo_connections() {
  local uri="${1:-mongodb://mongo:27017/?replicaSet=rs0}"
  local maxconn="${2:-65536}"
  if ! command -v mongosh >/dev/null 2>&1; then
    # 容器内才有 mongosh：优先进 mongo-backup / mongo 容器查询
    local cid
    cid="$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '^mogo-mongo(-backup)?-1$' | head -1)"
    [[ -z "${cid}" ]] && return 1
    if ! docker exec "${cid}" mongosh --quiet --eval "db.adminCommand({serverStatus:1}).connections.current" 2>/dev/null; then
      return 1
    fi
    return 0
  fi
  local cur
  cur="$(mongosh --quiet "${uri}" --eval "db.adminCommand({serverStatus:1}).connections.current" 2>/dev/null)"
  [[ -z "${cur}" ]] && return 1
  awk -v c="${cur}" -v m="${maxconn}" 'BEGIN{printf "%.0f", c*100/m}'
}

# 异步任务队列深度：从应用 /metrics 读取 queue_depth
mogo_watermark_sample_queue_depth() {
  local url="${1:-http://127.0.0.1:3000/metrics}"
  local val
  val="$(curl -s --max-time 5 "${url}" 2>/dev/null | awk -F'[ {]' '/^queue_depth/{print $2; exit}')"
  [[ -z "${val}" ]] && return 1
  printf '%s' "${val}"
}

mogo_watermark_sample_one() {
  local metric="$1" value="$2"
  case "${metric}" in
    memory_used_percent) mogo_watermark_sample_memory ;;
    cpu_used_percent) mogo_watermark_sample_cpu ;;
    disk_used_percent) mogo_watermark_sample_disk "${value:-/}" ;;
    count_of) mogo_watermark_sample_backup_count "${value:-${ROOT_DIR}/backups}" ;;
    backup_size_bytes) mogo_watermark_sample_backup_size "${value:-${ROOT_DIR}/backups}" ;;
    total_bytes) mogo_watermark_sample_logs "${value:-${ROOT_DIR}/logs}" ;;
    mongo_connections_count) mogo_watermark_sample_mongo_connections "${value:-mongodb://mongo:27017/?replicaSet=rs0}" ;;
    queue_depth_count) mogo_watermark_sample_queue_depth "${value:-http://127.0.0.1:3000/metrics}" ;;
    *) printf ''; return 1 ;;
  esac
}

# 列出水位定义（供 ./mogo monitor watermarks 使用）
mogo_watermark_list() {
  local watermarks="${DEFAULT_WATERMARKS}"
  if [[ ! -f "${watermarks}" ]]; then
    printf 'FAIL 水位文件 %s 不存在\n' "${watermarks}" >&2
    return 2
  fi
  python3 - "${watermarks}" <<'PY'
import json, sys, yaml
cfg = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
print("容量水位定义（watermarks.yml）")
for w in cfg.get("watermarks", []):
    direction = w.get("direction", "max")
    op = "低于" if direction == "min" else "超过"
    print(f"  - {w.get('key')}: {w.get('label')}  {op} warn({w.get('warn')}) / crit({w.get('crit')}) {w.get('unit','')}")
print("换算关系见 docs/capacity-model.md（024 T105/T108）")
PY
}

mogo_watermark_check() {
  local watermarks="${DEFAULT_WATERMARKS}" json_out=false
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --watermarks) watermarks="$2"; shift 2 ;;
      --json) json_out=true; shift ;;
      -h|--help) echo "用法: ./mogo monitor [--watermarks <file>] [--json]"; return 0 ;;
      *) printf 'FAIL 未知参数 %s\n' "$1" >&2; return 2 ;;
    esac
  done
  if [[ ! -f "${watermarks}" ]]; then
    printf 'FAIL 水位文件 %s 不存在\n' "${watermarks}" >&2
    return 2
  fi

  local list
  list="$(mogo_watermark_load "${watermarks}")" || { printf 'FAIL 无法解析 %s\n' "${watermarks}" >&2; return 2; }

  local rows="" exit_code=0
  while IFS=$'\t' read -r key label metric value unit warn crit direction; do
    [[ -z "${key}" ]] && continue
    local actual status
    # `|| true`：采样失败（df 目标不存在 / 指标不支持）在 mogo 的 `set -e` 下
    # 不能中断调用方，返回空串由下方判定为 UNKNOWN。
    actual="$(mogo_watermark_sample_one "${metric}" "${value}" 2>/dev/null || true)"
    local warn_num crit_num actual_num
    warn_num="$(printf '%s\n' "${warn}" | tr -d '[:space:]')"
    crit_num="$(printf '%s\n' "${crit}" | tr -d '[:space:]')"
    actual_num="$(printf '%s\n' "${actual}" | tr -d '[:space:]')"

    if [[ -z "${actual_num}" ]]; then
      status="UNKNOWN"
    elif [[ "${direction}" == "min" ]]; then
      if awk -v a="${actual_num}" -v c="${crit_num}" 'BEGIN{exit !(a<=c)}'; then status="CRIT"
      elif awk -v a="${actual_num}" -v w="${warn_num}" 'BEGIN{exit !(a<=w)}'; then status="WARN"
      else status="PASS"; fi
    else
      if awk -v a="${actual_num}" -v c="${crit_num}" 'BEGIN{exit !(a>=c)}'; then status="CRIT"
      elif awk -v a="${actual_num}" -v w="${warn_num}" 'BEGIN{exit !(a>=w)}'; then status="WARN"
      else status="PASS"; fi
    fi

    rows+="${key}|${label}|${actual_num}${unit}|${status}|${warn_num}|${crit_num}\n"
    if [[ "${status}" == "CRIT" ]]; then exit_code=2
    elif [[ "${status}" == "WARN" ]] && [[ "${exit_code}" -lt 2 ]]; then exit_code=1
    fi
  done < <(printf '%s' "${list}" | python3 -c '
import json, sys
for w in json.loads(sys.stdin.read()):
    print("\t".join(str(w.get(k, "")) for k in
        ["key", "label", "metric", "value", "unit", "warn", "crit", "direction"]))
')

  if [[ "${json_out}" == true ]]; then
    python3 -c '
import json, sys
rows = []
for line in sys.argv[1].splitlines():
    if not line: continue
    p = line.split("|")
    rows.append({"key": p[0], "label": p[1], "actual": p[2], "status": p[3],
                 "warn": p[4], "crit": p[5]})
print(json.dumps({"exit": int(sys.argv[2]), "results": rows}, ensure_ascii=False, indent=2))
' "$(printf '%b' "${rows}")" "${exit_code}"
  else
    printf '容量水位检查（%s）\n' "${watermarks}"
    while IFS='|' read -r key label actual status warn crit; do
      [[ -z "${key}" ]] && continue
      printf '  [%s] %-28s 当前=%s  WARN<%s  CRIT<%s\n' \
        "${status}" "${label}" "${actual}" "${warn}" "${crit}"
    done < <(printf '%b' "${rows}")
    case "${exit_code}" in
      0) printf '容量水位全部 PASS\n' ;;
      1) printf 'WARN 存在容量水位告警\n' >&2 ;;
      2) printf 'CRIT 存在容量水位严重项\n' >&2 ;;
    esac
  fi
  return "${exit_code}"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "此脚本由 ./mogo monitor 调用，不单独执行" >&2
  exit 2
fi