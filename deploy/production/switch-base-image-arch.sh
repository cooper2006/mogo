#!/usr/bin/env bash
# ============================================================================
# switch-base-image-arch.sh
# ----------------------------------------------------------------------------
# 在「本地 arm64 原生 dev 环境」与「推送离线 amd64 远端」之间，
# 无损地切换基础镜像【干净标签】的架构：4 个运行时 + 2 个构建期（python / node）。
#
# 为什么需要它：
#   同一个 repo:tag 在同一 docker daemon 里不能同时是 arm64 又是 amd64。
#   - 本地 dev 全 arm64 原生（Apple Silicon 上零仿真）；
#   - deploy/production/deploy-remote-push.sh 要求这些干净名基础镜像是 amd64
#     才能推送离线 amd64 远端（其第 328–334 行架构安全网会拦截非 amd64）。
#   因此同一组干净名（alpine:3.21 等）在两种工作流下需要不同架构。
#
#   构建期的 python:3.13-slim-bookworm / node:24-bookworm-slim 也在此列：
#   compose 给服务下了 platform=linux/amd64，但 buildkit 在离线（registry 不可达）
#   时会直接用本地已有的同名 tag。若那个 tag 是 arm64，产物就成了「TARGETARCH=amd64
#   却跑在 arm64 根文件系统里」——apt 装 arm64 deb、pip 因 wheel 平台标签不匹配报
#   "No matching distribution found"。2026-11-07 的 amd64 全量构建就栽在这里。
#
# 切换原理（对一个干净名 CLEAN）：
#   → amd64：优先用离线 bundle 刻意保留的 mogo-staging/<suffix>:amd64 标签 retag；
#             若无该 staging 标签（如 nginx、python、node），则从 base-images/images/amd64/*.tar load。
#   → arm64：从 base-images/images/arm64/*.tar load（arm64 无 staging 标签）。
#   load 出来的 RepoTags 可能是国内镜像站副本名（如 docker.1panel.live/library/python），
#   两个方向都要 retag 到 CLEAN 并清掉别名，否则干净名仍指向旧架构。
#   load / tag 只会改 repo:tag 指向的镜像 ID，被运行中容器引用的原镜像层不受影响，
#   故本脚本对正在运行的 dev 栈是安全的（但切到 amd64 后请勿 `mogo up --build`）。
#
# 用法：
#   ./switch-base-image-arch.sh amd64   切到 amd64（推远端前 / amd64 构建前执行）
#   ./switch-base-image-arch.sh arm64   恢复 arm64（本地 dev 原生运行）
#   ./switch-base-image-arch.sh status  查看 6 个干净名当前的架构
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
# 前 4 条与 deploy-remote-push.sh 的 BASE_IMAGES 完全一致（运行时基础镜像）；
# 后 2 条是构建期基础镜像，只在本地 build 时用到，不推送远端，staging 后缀留空。
#   alpine:3.21                       | alpine_3.21              | alpine_3.21.tar
#   nginx:1.31.5-alpine3.24-slim      | nginx_1.31.5-alpine3.24-slim | 同上
#   redis:7.4.2-alpine                | redis_7.4.2-alpine       | redis_7.4.2-alpine.tar
#   semitechnologies/weaviate:1.25.7  | semitechnologies_weaviate_1.25.7 | 同上
# 注：nginx / python / node 在 mogo-staging 下没有 amd64 标签，故 amd64 走 tar。
MAP=(
  "alpine:3.21|alpine_3.21|alpine_3.21.tar|alpine_3.21.tar"
  "nginx:1.31.5-alpine3.24-slim|nginx_1.31.5-alpine3.24-slim|nginx_1.31.5-alpine3.24-slim.tar|nginx_1.31.5-alpine3.24-slim.tar"
  "redis:7.4.2-alpine|redis_7.4.2-alpine|redis_7.4.2-alpine.tar|redis_7.4.2-alpine.tar"
  "semitechnologies/weaviate:1.25.7|semitechnologies_weaviate_1.25.7|semitechnologies_weaviate_1.25.7.tar|semitechnologies_weaviate_1.25.7.tar"
  "python:3.13-slim-bookworm||python_3.13-slim-bookworm.tar|python_3.13-slim-bookworm.tar"
  "node:24-bookworm-slim||node_24-bookworm-slim.tar|node_24-bookworm-slim.tar"
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

# load 一个 tar，并把 tar 内部的 RepoTags retag 到干净名。
# python / node 的 tar 里是镜像站副本名（docker.1panel.live/library/... 等），
# 只 load 不 retag 的话干净名仍指向原来的 arm64 镜像。
load_and_retag() {
  local tar_path="${1:-}" clean="${2:-}" target="${3:-}" out actual
  log "  • load ${tar_path} -> ${clean} (${target})"
  out="$("${DC[@]}" load -i "$tar_path" 2>&1)" \
    || { warn "load 失败: ${tar_path}"; return 1; }
  actual="$(printf '%s' "$out" | sed -n 's/.*Loaded image: //p' | head -n1)"
  if [[ "$(img_arch "$clean")" != "$target" ]]; then
    if [[ -z "$actual" ]]; then
      warn "load 未产出可识别的 repo:tag，无法 retag 到 ${clean}"
      return 1
    fi
    log "    ↳ retag ${actual} -> ${clean} (${target})"
    "${DC[@]}" tag "$actual" "$clean"
    if [[ "$actual" != "$clean" ]]; then
      "${DC[@]}" rmi "$actual" >/dev/null 2>&1 || true
    fi
  fi
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
    staging_ref=""
    [[ -n "$staging_suffix" ]] && staging_ref="${STAGING_PREFIX}/${staging_suffix}:amd64"
    amd64_tar_path="${BASE_IMAGES_DIR}/amd64/${amd64_tar}"
    arm64_tar_path="${BASE_IMAGES_DIR}/arm64/${arm64_tar}"

    cur="$(img_arch "$clean")"
    if [[ "$cur" == "$target" ]]; then
      log "  • ${clean} 已是 ${target}，跳过"
      continue
    fi

    if [[ "$target" == "amd64" ]]; then
      if [[ -n "$staging_ref" ]] && "${DC[@]}" image inspect "$staging_ref" >/dev/null 2>&1; then
        log "  • tag ${staging_ref} -> ${clean} (amd64)"
        "${DC[@]}" tag "$staging_ref" "$clean"
      elif [[ -f "$amd64_tar_path" ]]; then
        load_and_retag "$amd64_tar_path" "$clean" "$target" || true
      else
        warn "缺少 amd64 源：${staging_ref:-（该镜像无 staging 标签）} 与 ${amd64_tar_path} 均不可用，跳过 ${clean}"
      fi
    else # arm64
      if [[ -f "$arm64_tar_path" ]]; then
        load_and_retag "$arm64_tar_path" "$clean" "$target" || true
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
  log "==> 基础镜像干净名的当前架构："
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
  switch-base-image-arch.sh amd64   切到 amd64（推离线远端 / amd64 构建前执行）
  switch-base-image-arch.sh arm64   恢复 arm64（本地 dev 原生运行）
  switch-base-image-arch.sh status  查看 6 个干净名当前架构
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
