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
# - **两条豁免通道，都不放宽 pattern**：
#     1. 路径级 ALLOWLIST_PATHS —— 整棵目录（测试固件 .qualityforge/、tests/、
#        docs/、specs/、scripts/dev/ 下的伪造样例与文档示例）。
#     2. 行级 LINE_ALLOWLIST_MARKER —— 单行（源码里「看着像密钥赋值、实为
#        变量名 / 函数调用 / 开发占位符」的行）。
#   之所以需要第 2 条：高置信模式 (secret|password|token|api_key)\s*[:=]\s*\S{20,}
#   必然会把 `signing_secret = resolve_...(` 这类赋值算作候选。路径白名单管不到
#   单行，而收紧 pattern 会同时削弱对真实密钥的检出——用行级标记精确豁免，
#   检出能力零损失。
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
  "specs/"
  ".github/workflows/"
  # 开发/测试辅助脚本：内含伪造的本地凭据（与 tests/ 同类）
  "scripts/dev/"
  # 机器生成的依赖锁定文件：内容是 sha512 integrity 哈希（不是密钥），
  # 且每次安装都会重写，行级标记无法持久。
  "pnpm-lock.yaml"
  "versions.lock"
  # 前端构建产物
  "dist/"
  "build/"
  ".venv/"
  "venv/"
)

# 行级豁免标记（detect-secrets 的通行写法）。
#
# 路径白名单只能豁免整棵目录；源码里「看起来像密钥赋值、实际是变量名 / 函数调用 /
# 开发占位符」的行无法靠它消除，而放宽模式会同时削弱对真实密钥的检出——那是不可
# 接受的取舍。所以在行尾加这个标记来精确豁免单行，例如：
#
#     signing_secret = resolve_local_file_signing_secret(  # pragma: allowlist secret
#     accessToken: 'UPGRADE_INVENTORY_MODEL_TOKEN',        // pragma: allowlist secret
#
# 只跳过**命中行**，不影响同文件其它行，也不改变任何 pattern。
LINE_ALLOWLIST_MARKER="pragma: allowlist secret"

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
  # 40+ 位 base64url 随机串，且必须：① 出现在**值位置**（`=` / `:` 右侧，
  # 可带引号）；② 以 base64 填充 `=` 结尾。
  #
  # 两个约束都是实测选出来的，不是随手写的：
  #
  #  ① 值位置。否则任何 40+ 字符的**标识符名字**都会命中，例如
  #       ASKAI_ADMIN_TENANT_BOOTSTRAP_ADMIN_ENABLED=false
  #       MOVO_DOC_PROCESSING_OSS_ACCESS_KEY_SECRET=
  #     以及 `.env.example` / compose / 部署模板里的长 KEY 名。实测 `--all`
  #     最初的 12 条低置信提示**全部**是这类误报，而本通道的意图是
  #     「长**随机串**」（见文件头设计取舍）——变量名不是随机串。
  #
  #  ② 以 `=` 结尾。注意 `==?` 读作「一个**必选** `=` + 一个可选 `=`」，
  #     并不是「可选填充」——这是**刻意保留**的窄化，不是笔误：把它改成语义
  #     正确的 `={0,2}` 后实测 `--all` 的低置信提示由 12 条涨到 24 条
  #     （`.specify/*.manifest.json` 的文件校验和、`sbom.cdx.json`、4 个 XSD、
  #     3 个 requirements.txt、Vue 里的长 CSS 类名…），**逐条核对没有一条是
  #     密钥**。根因是「40+ 字符」这个长度门槛本身就区分不了随机串与校验和 /
  #     长标识符，所以这里只保留最窄的形态：值位置 + base64 填充。
  #
  # 高置信模式（AKIA / ghp_ / PEM / sk_live_ / JWT / `secret = <20+>` 等）
  # 完全不受影响，真实凭据仍会被直接阻断；本通道只是提示、不阻断。
  # 机器生成物里的 `sha512-…==`（pnpm-lock.yaml、versions.lock）由
  # ALLOWLIST_PATHS 豁免。
  $'[:=][[:space:]]*[\'\"]?[A-Za-z0-9_\\-]{40,}==?'
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
    # 条目（目录名或文件名）可能在任意层级出现，不能只做前缀匹配。
    #
    # `--all` 模式用 `git ls-files` 产出的是仓库根相对全路径
    # （`services/admin-api/tests/...`、`apps/user-web/pnpm-lock.yaml`），
    # 而白名单只做前缀比较时会漏掉它们，于是测试固件里的伪造密钥样例、
    # 锁定文件里的 integrity 哈希都会被当成真实泄露报出来。
    #
    # 两种形式都接受：
    #   * `"$entry"*`      —— 仓库根下的 `tests/`、`docs/`、`pnpm-lock.yaml` 等
    #   * `*"/$entry"*`    —— 任意层级下的同名目录 / 文件
    [[ "$path" == "$entry"* || "$path" == *"/$entry"* ]] && return 0
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
  # 行级豁免：命中行若带 LINE_ALLOWLIST_MARKER 则丢弃。`-F` 走字面匹配，
  # 避免标记里的 `:` 被当成 ERE 语法。输出为空时管道返回 1，调用方只看
  # 「输出是否为空」，故用 `|| true` 收尾。
  grep "${args[@]}" -- "$file" 2>/dev/null | grep -vF "${LINE_ALLOWLIST_MARKER}" || true
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
