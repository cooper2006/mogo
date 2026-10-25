#!/usr/bin/env bash
# 026 T040 — 前端性能预算检查脚本（FR-23）
#
# 检查 admin-web / user-web 构建产物的 gzip 包体积是否满足预算
# （admin-web ≤ 500KB、user-web ≤ 300KB，来源 baselines.yaml frontend.*）。
#
# 用法：
#   ./benchmarks/frontend_budget_check.sh \
#       [--admin-dir apps/admin-web/dist] \
#       [--user-dir apps/user-web/dist] \
#       [--admin-max-kb 500] [--user-max-kb 300]
#
# 退出码：0 通过；1 预算超标；2 用法错误或产物缺失。
# 提示：完整 LCP / 请求数检查建议在 CI 用 Lighthouse（`npx lighthouse URL --only-categories=performance`），
#       本脚本负责包体积快速门禁（可在 CI 中被调用）。

set -uo pipefail

ADMIN_DIR="${ADMIN_DIR:-apps/admin-web/dist}"
USER_DIR="${USER_DIR:-apps/user-web/dist}"
ADMIN_MAX_KB="${ADMIN_MAX_KB:-500}"
USER_MAX_KB="${USER_MAX_KB:-300}"

# 解析 --key value 参数
while [[ $# -gt 0 ]]; do
  case "$1" in
    --admin-dir) ADMIN_DIR="$2"; shift 2 ;;
    --user-dir) USER_DIR="$2"; shift 2 ;;
    --admin-max-kb) ADMIN_MAX_KB="$2"; shift 2 ;;
    --user-max-kb) USER_MAX_KB="$2"; shift 2 ;;
    -h|--help) sed -n '1,20p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

fail=0

gzip_size_kb() {
  # 返回 dist 目录内 js/css 产物的 gzip 合计大小（KB，向下取整）
  local dir="$1"
  if [[ ! -d "$dir" ]]; then
    echo 0
    return
  fi
  local total=0
  while IFS= read -r -d '' f; do
    local sz
    sz=$(gzip -c -9 "$f" | wc -c | tr -d ' ')
    total=$(( total + sz ))
  done < <(find "$dir" -type f \( -name "*.js" -o -name "*.css" \) -print0)
  echo $(( total / 1024 ))
}

check_budget() {
  local label="$1" dir="$2" max="$3"
  local actual
  actual=$(gzip_size_kb "$dir")
  if [[ "$actual" -eq 0 ]]; then
    echo "❌ [$label] 构建产物缺失：${dir}（请先执行 vite build）"
    fail=1
    return
  fi
  printf "%-10s gzip 合计 %5d KB / 预算 %5d KB " "$label" "$actual" "$max"
  if [[ "$actual" -le "$max" ]]; then
    echo "✅ 通过"
  else
    echo "❌ 超标"
    fail=1
  fi
}

echo "=== 026 T040 前端性能预算检查（$(date -u +%FT%TZ)）==="
check_budget "admin-web" "$ADMIN_DIR" "$ADMIN_MAX_KB"
check_budget "user-web" "$USER_DIR" "$USER_MAX_KB"

echo "---"
if [[ "$fail" -eq 0 ]]; then
  echo "✅ 预算检查全部通过"
else
  echo "❌ 预算检查未通过"
fi
exit "$fail"