#!/usr/bin/env bash
# ============================================================================
# switch-base-image-arch.sh
# ----------------------------------------------------------------------------
# 在「本地 arm64 原生 dev 环境」与「推送离线 amd64 远端」之间，
# 无损地切换 4 个运行时基础镜像的【干净标签】架构。
#
# 为什么需要它：
#   同一个 repo:tag 在同一 docker daemon 里不能同时是 arm64 又是 amd64。
#   - 本地 dev 全 arm64 原生（Apple Silicon 上零仿真）；
#   - deploy/production/deploy-remote-push.sh 要求这些干净名基础镜像是 amd64
#     才能推送离线 amd64 远端（其第 328–334 行架构安全网会拦截非 amd64）。
#   因此同一组干净名（alpine:3.21 等）在两种工作流下需要不同架构。
#
# 切换原理（对一个干净名 CLEAN）：
#   → amd64：优先用离线 bundle 刻意保留的 mogo-staging/<suffix>:amd64 标签 retag；
#             若无该 staging 标签（如 nginx），则从 base-images/images/amd64/*.tar load。
#   → arm64：从 base-images/images/arm64/*.tar load（arm64 无 staging 标签）。
#   load / tag 只会改 repo:tag 指向的镜像 ID，被运行中容器引用的原镜像层不受影响，
#   故本脚本对正在运行的 dev 栈是安全的（但切到 amd64 后请勿 `mogo up --build`）。
#
# 用法：
#   ./switch-base-image-arch.sh amd64   切到 amd64（推远端前执行）
#   ./switch-base-image-arch.sh arm64   恢复 arm64（本地 dev 原生运行）
#   ./switch-base-image-arch.sh status  查看 4 个干净名当前的架构
#   ./switch-base-image-arch.sh -h      帮助
#
# 环境变量：
#   MOGO_DOCKER_CONTEXT   docker context 名（默认 orbstack）
# ============================================================================
set -euo pipefail

# ── docker context ──────────────────────────────────────────────────────────
CTX="${MOGO_DOCKER_CONTEXT:-orbstack}"
DC=(docker -c "$CTX")

# ── 路径 ────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_IMAGES_DIR="$(cd "${SCRIPT_DIR}/../../base-images/images" && pwd)"
STAGING_PREFIX="mogo-staging"

# ── 干净名 → (staging 后缀 | amd64 tar | arm64 tar) ─────────────────────────
# 与 deploy-remote-push.sh 的 BASE_IMAGES 完全一致。
#   alpine:3.21                       | alpine_3.21              | alpine_3.21.tar
#   nginx:1.31.5-alpine3.24-slim      | nginx_1.31.5-alpine3.24-slim | 同上
#   redis:7.4.2-alpine                | redis_7.4.2-alpine       | redis_7.4.2-alpine.tar
#   semitechnologies/weaviate:1.25.7  | semitechnologies_weaviate_1.25.7 | 同上
# 注：nginx 在 mogo-staging 下没有 amd64 标签，故 amd64 走 tar。
MAP=(
  "alpine:3.21|alpine_3.21|alpine_3.21.tar|alpine_3.21.tar"
  "nginx:1.31.5-alpine3.24-slim|nginx_1.31.5-alpine3.24-slim|nginx_1.31.5-alpine3.24-slim.tar|nginx_1.31.5-alpine3.24-slim.tar"
  "redis:7.4.2-alpine|redis_7.4.2-alpine|redis_7.4.2-alpine.tar|redis_7.4.2-alpine.tar"
  "semitechnologies/weaviate:1.25.7|semitechnologies_weaviate_1.25.7|semitechnologies_weaviate_1.25.7.tar|semitechnologies_weaviate_1.25.7.tar"
)

# ── 工具函数 ────────────────────────────────────────────────────────────────
log()  { printf '%s\n' "$*"; }
warn() { printf '  ⚠ %s\n' "$*" >&2; }

img_arch() {
  local ref="$1"
  "${DC[@]}" image inspect "$ref" --format '{{.Architecture}}' 2>/dev/null || true
}

each_entry() {
  # 调用方通过回调变量 CALLBACK 传入处理函数；这里逐行解析 MAP 并暴露 4 个变量。
  local entry clean staging_suffix amd64_tar arm64_tar
  for entry in "${MAP[@]}"; do
    IFS='|' read -r clean staging_suffix amd64_tar arm64_tar <<< "$entry"
    eval "$1"
  done
}

# ── 切换到目标架构 ──────────────────────────────────────────────────────────
switch_to() {
  local target="$1"
  log "==> 将基础镜像干净名切换为 ${target} ..."

  if [[ "$target" == "amd64" ]]; then
    log "    提示：切换后请勿执行 \`mogo up --build\`（否则 dev 会构建出 amd64 应用）。"
    log "    应直接运行 deploy/production/deploy-remote-push.sh 推送到离线 amd64 远端。"
  fi

  local clean staging_suffix amd64_tar arm64_tar staging_ref amd64_tar_path arm64_tar_path cur
  for entry in "${MAP[@]}"; do
    IFS='|' read -r clean staging_suffix amd64_tar arm64_tar <<< "$entry"
    staging_ref="${STAGING_PREFIX}/${staging_suffix}:amd64"
    amd64_tar_path="${BASE_IMAGES_DIR}/amd64/${amd64_tar}"
    arm64_tar_path="${BASE_IMAGES_DIR}/arm64/${arm64_tar}"

    cur="$(img_arch "$clean")"
    if [[ "$cur" == "$target" ]]; then
      log "  • ${clean} 已是 ${target}，跳过"
      continue
    fi

    if [[ "$target" == "amd64" ]]; then
      if "${DC[@]}" image inspect "$staging_ref" >/dev/null 2>&1; then
        log "  • tag ${staging_ref} -> ${clean} (amd64)"
        "${DC[@]}" tag "$staging_ref" "$clean"
      elif [[ -f "$amd64_tar_path" ]]; then
        log "  • load ${amd64_tar_path} (amd64)"
        local out actual
        out="$("${DC[@]}" load -i "$amd64_tar_path" 2>&1)" \
          || { warn "load 失败: ${amd64_tar_path}"; continue; }
        # tar 内部 repo:tag 可能不是干净名（如早期镜像站副本），需 retag 到干净名并清理别名。
        actual="$(printf '%s' "$out" | sed -n 's/.*Loaded image: //p' | head -n1)"
        if [[ "$(img_arch "$clean")" != "amd64" ]]; then
          if [[ -n "$actual" ]]; then
            log "    ↳ retag ${actual} -> ${clean} (amd64)"
            "${DC[@]}" tag "$actual" "$clean"
            if [[ "$actual" != "$clean" ]]; then
              "${DC[@]}" rmi "$actual" >/dev/null 2>&1 || true
            fi
          else
            warn "load 未产出可识别的 repo:tag，无法 retag 到 ${clean}"
          fi
        fi
      else
        warn "缺少 amd64 源：${staging_ref} 与 ${amd64_tar_path} 均不可用，跳过 ${clean}"
      fi
    else # arm64
      if [[ -f "$arm64_tar_path" ]]; then
        log "  • load ${arm64_tar_path} -> ${clean} (arm64)"
        "${DC[@]}" load -i "$arm64_tar_path"
      else
        warn "缺少 arm64 源：${arm64_tar_path} 不可用，跳过 ${clean}"
      fi
    fi
  done

  log "==> 完成。当前状态："
  show_status
}

# ── 查看状态 ────────────────────────────────────────────────────────────────
show_status() {
  log "==> 4 个运行时基础镜像干净名的当前架构："
  local clean
  for entry in "${MAP[@]}"; do
    IFS='|' read -r clean _ <<< "$entry"
    printf '  %-35s %s\n' "$clean" "$(img_arch "$clean" || echo '缺失')"
  done
}

# ── 帮助 ────────────────────────────────────────────────────────────────────
usage() {
  cat <<'EOF'
用法:
  switch-base-image-arch.sh amd64   切到 amd64（推离线远端前执行）
  switch-base-image-arch.sh arm64   恢复 arm64（本地 dev 原生运行）
  switch-base-image-arch.sh status  查看 4 个干净名当前架构
  switch-base-image-arch.sh -h      本帮助

环境变量:
  MOGO_DOCKER_CONTEXT   docker context（默认 orbstack）
EOF
}

# ── 入口 ────────────────────────────────────────────────────────────────────
case "${1:-}" in
  amd64|arm64) switch_to "$1" ;;
  status)      show_status ;;
  -h|--help|"") usage ;;
  *) warn "未知参数: $1"; usage; exit 1 ;;
esac
