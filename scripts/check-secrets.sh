#!/usr/bin/env bash
# 022 FR-26 (T048)：提交钩子 / CI 步骤 —— 阻止密钥进入版本库。
#
# 用法：
#   scripts/check-secrets.sh                # 检查本次提交（HEAD^..HEAD）
#   scripts/check-secrets.sh --all           # 检查全部文件（CI 全量）
#   scripts/check-secrets.sh --baseline      # 检查相对 HEAD 的工作区改动
#   scripts/check-secrets.sh <path>...       # 检查指定路径
#
# 退出码：0 = 干净；1 = 发现疑似密钥。
#
# 设计取舍：
# - **不做上下文豁免**：密钥是「零容忍」类，任何路径出现都失败。需要豁免的
#   是**测试固件**（.qualityforge/、tests/ 下的伪造样例），集中登记在
#   ALLOWLIST_PATHS，而不是靠 pattern 白名单绕过。
# - **只报不猜**：AKIA / BEGIN PRIVATE KEY 这类高置信模式直接判失败；
#   低置信模式（长随机串）只在 --all 模式下报告，避免钩子里噪音太大。
# - 钩子版本用 git 的 diff 范围，速度可控；CI 用 --all 保证全量覆盖。

set -uo pipefail

ALLOWLIST_PATHS=(
  # 测试固件：伪造的、不可能有效的密钥样例
  "tests/"
  "tests/fixtures/"
  ".qualityforge/"
  "node_modules/"
  # 文档里的示例（占位符而非真实密钥）
  "docs/"
  ".github/workflows/"
  # 前端构建产物
  "dist/"
  "build/"
  ".venv/"
  "venv/"
)

# 高置信模式：任何路径出现即失败。
HIGH_CONFIDENCE_PATTERNS=(
  # ----- PEM / PKCS#8 / OpenSSH 私钥头 -----
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'
  # ----- AWS -----
  # Access Key ID：AKIA + 16 位大写字母数字（官方格式，共 20 字符）。
  # 不加尾部锚点是因为 AKIA 可能出现在带引号的赋值或 JSON 值里。
  'AKIA[0-9A-Z]{16}'
  # Secret Access Key：40 位 base64，跟在赋值符号后。
  $'aws_secret_access_key[[:space:]]*[:=][[:space:]]*[\'\"]?[A-Za-z0-9/+=]{40}'
  # ----- Google Cloud -----
  'AIza[0-9A-Za-z-]{35}'
  'private_key_id[[:space:]]*[:=]'
  # ----- GitHub -----
  'ghp_[0-9A-Za-z]{36,255}'
  'gho_[0-9A-Za-z]{36,255}'
  'github_pat_[0-9A-Za-z_]{22,255}'
  # ----- Slack / Stripe -----
  'xox[baprs]-[0-9A-Za-z-]{10,48}'
  'sk_live_[0-9A-Za-z]{16,}'
  'rk_live_[0-9A-Za-z]{16,}'
  # ----- JWT（非 test/占位）-----
  'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}'
  $'(secret|password|passwd|token|api[_-]?key)[[:space:]]*[:=][[:space:]]*[\'\"]?[A-Za-z0-9/+=_-]{20,}'
  $'jwt[_-]?secret[[:space:]]*[:=][[:space:]]*[\'\"]?[A-Za-z0-9/+=_-]{20,}'
)

# 低置信模式：仅在 --all 模式报告（不阻断钩子）。
LOW_CONFIDENCE_PATTERNS=(
  # 40+ 位 base64url 随机串
  '[A-Za-z0-9_\-]{40,}==?'
)

MODE="commit"
CASES_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)      MODE="all"; shift ;;
    --baseline) MODE="baseline"; shift ;;
    -h|--help)  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*)         echo "unknown option: $1" >&2; exit 2 ;;
    *)          CASES_ARGS+=("$1"); shift ;;
  esac
done

# 收集待检查文件（NUL 分隔）。显式传入路径时优先按路径扫，
# 这样脚本可以脱离 git 上下文使用（单元测试、CI 的定点扫描）。
collect_files() {
  if [[ "${#CASES_ARGS[@]}" -gt 0 ]]; then
    printf '%s\0' "${CASES_ARGS[@]}"
    return
  fi
  case "$MODE" in
    all)
      git ls-files -z
      ;;
    baseline)
      { git diff --name-only --diff-filter=ACM HEAD -z
        git ls-files --others --exclude-standard -z; }
      ;;
    commit)
      git diff --name-only --diff-filter=ACM HEAD^..HEAD -z
      ;;
  esac
}

is_allowlisted() {
  local path="$1" entry
  for entry in "${ALLOWLIST_PATHS[@]}"; do
    [[ "$path" == "$entry"* ]] && return 0
  done
  return 1
}

# 用 grep 扫描单个文件，输出命中行（行号:内容）。
# 参数：$1 = 文件路径，其余 = pattern 列表。
#
# 用 grep 而不是 ripgrep：rg 不是默认安装的工具，grep 在所有 CI runner
# 与 macOS / Linux 上都有。-i 让模式统一大小写不敏感，因此 pattern 表里
# 不必逐个写 (?i)。-E 用 POSIX ERE（[[:space:]] 是 POSIX 字符类）。
#
# 注意两点坑：
#  1. 每个 pattern 必须单独跟一个 -e。`grep -e p1 p2 p3` 里 p2/p3 会被当成
#     **文件名**而不是 pattern。
#  2. 不用 `local -n`（nameref）—— macOS 自带 bash 3.2 不支持，只在 bash 4.3+
#     可用。改为按位置传参。
grep_patterns() {
  local file="$1"
  shift
  local args=(-inE)
  while [[ $# -gt 0 ]]; do
    args+=(-e "$1")
    shift
  done
  grep "${args[@]}" -- "$file" 2>/dev/null
}

found=0
while IFS= read -r -d '' file; do
  [[ -z "$file" || ! -f "$file" ]] && continue
  is_allowlisted "$file" && continue

  # 高置信模式：任何模式命中即失败。
  high="$(grep_patterns "$file" "${HIGH_CONFIDENCE_PATTERNS[@]}")"
  if [[ -n "$high" ]]; then
    echo "✗ 疑似密钥：$file" >&2
    echo "$high" | head -5 >&2
    echo "" >&2
    found=1
    continue
  fi

  # 低置信模式：仅 --all 模式提示，不阻断（避免钩子噪音）。
  if [[ "$MODE" == "all" ]]; then
    low="$(grep_patterns "$file" "${LOW_CONFIDENCE_PATTERNS[@]}")"
    [[ -n "$low" ]] && echo "⚠  低置信：$file" >&2 && echo "$low" | head -3 >&2
  fi
done < <(collect_files)

if [[ "$found" -eq 0 ]]; then
  echo "✓ 未发现疑似密钥"
  exit 0
fi

cat >&2 <<'EOF'

如果这是测试固件或文档示例，请把它加入 scripts/check-secrets.sh 的
ALLOWLIST_PATHS；如果确实需要提交密钥，请改用 secrets manager 并在
docs/security/RESIDUAL_RISK.md 登记豁免。
EOF
exit 1
