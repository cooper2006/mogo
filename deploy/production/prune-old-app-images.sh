#!/usr/bin/env bash
# =============================================================================
# mogo 应用镜像旧版本清理 —— 仅保留当前部署版本（默认 :latest）
# -----------------------------------------------------------------------------
# 远端 daemon（默认 docker context=mogo-remote）必清；
# 加 --local 额外清理本地 orbstack 的构建缓存旧 commit tag。
#
# 清理范围：仅 ghcr.io/mogoai/<7个应用> 命名空间下、tag 不等于当前
#           MOGO_VERSION（默认 latest）的镜像。基础镜像（alpine/nginx/redis/
#           weaviate）、mesc-*、localhost:5000/* 等一概不动。
#
# 若旧镜像仍被「已停止」的旧容器引用，会先移除这些容器再删镜像；
# 若被「运行中的」容器引用（例如清理过早），则跳过并告警，绝不破坏在跑服务。
#
# 用法：
#   bash prune-old-app-images.sh [--local] [--dry-run] [--remote-env <file>]
# =============================================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${ROOT_DIR}"

REMOTE_ENV="${REMOTE_ENV:-${SCRIPT_DIR}/remote.env}"
[[ -f "${REMOTE_ENV}" ]] && { set -a; . "${REMOTE_ENV}"; set +a; }

REMOTE_HOST="${REMOTE_HOST:-172.17.5.96}"
REMOTE_PORT="${REMOTE_PORT:-22}"
REMOTE_USER="${REMOTE_USER:-bonc}"
REMOTE_PASSWORD="${REMOTE_PASSWORD:-}"
DOCKER_CONTEXT="${DOCKER_CONTEXT:-mogo-remote}"
LOCAL_CONTEXT="${LOCAL_CONTEXT:-orbstack}"
MOGO_VERSION="${MOGO_VERSION:-latest}"
DO_LOCAL=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local)     DO_LOCAL=1; shift ;;
    --remote-env) REMOTE_ENV="$2"; shift 2 ;;
    --dry-run)   DRY_RUN=1; shift ;;
    -h|--help)   sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^#\{1,2\} //'; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

log()  { printf '\033[0;32m[prune]\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33m[warn]\033[0m %s\n' "$*" >&2; }
run()  { if [[ "${DRY_RUN}" -eq 1 ]]; then log "(dry-run) $*"; else eval "$@"; fi; }

# ── sshpass 包装（若配置了密码）─────────────────────────────────────────────
REAL_SSH="$(command -v ssh || true)"
if [[ -n "${REMOTE_PASSWORD:-}" && -n "${REAL_SSH:-}" ]]; then
  SSHPASS_BIN="$(command -v sshpass || true)"
  if [[ -n "${SSHPASS_BIN:-}" ]]; then
    SSH_WRAP_DIR="$(mktemp -d)"
    cat > "${SSH_WRAP_DIR}/ssh" <<WRAP
#!/usr/bin/env bash
exec "${SSHPASS_BIN}" -p "\${REMOTE_PASSWORD}" "${REAL_SSH}" \\
  -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "\$@"
WRAP
    chmod +x "${SSH_WRAP_DIR}/ssh"
    export PATH="${SSH_WRAP_DIR}:${PATH}"
  fi
fi

# ── 确保远端 context 可用 ───────────────────────────────────────────────────
if ! docker context inspect "${DOCKER_CONTEXT}" >/dev/null 2>&1; then
  run "docker context create ${DOCKER_CONTEXT} --docker host=ssh://${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PORT}"
fi

APP_IMAGES=(chat-api document-parser dsh-runtime-host gateway admin-api admin-web user-web)
keep_refs=()
for svc in "${APP_IMAGES[@]}"; do
  keep_refs+=("ghcr.io/mogoai/${svc}:${MOGO_VERSION}")
done

prune_one_context() {
  local desc="$1"; shift
  local -a dc=("$@")
  log "清理 ${desc} 旧版本应用镜像（保留: ${keep_refs[*]}）..."
  local imgs
  imgs="$("${dc[@]}" images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -E '^ghcr\.io/mogoai/.+:.+' || true)"
  [[ -z "${imgs:-}" ]] && { log "  (无 mogoai 镜像，跳过)"; return 0; }
  while IFS= read -r ref; do
    [[ -z "${ref:-}" ]] && continue
    local keep=0
    for k in "${keep_refs[@]}"; do
      [[ "${ref}" == "${k}" ]] && { keep=1; break; }
    done
    if [[ "${keep}" -eq 0 ]]; then
      if [[ "${DRY_RUN}" -eq 1 ]]; then
        echo "  [dry-run] 将删除: ${ref}"
        continue
      fi
      if "${dc[@]}" rmi "${ref}" >/dev/null 2>&1; then
        log "  ✓ 已删除: ${ref}"
      else
        # 可能被「已停止」的旧容器引用 -> 先移除这些容器再删镜像
        local cids
        cids="$("${dc[@]}" ps -a --filter "ancestor=${ref}" --format '{{.ID}}' 2>/dev/null | tr '\n' ' ')"
        if [[ -n "${cids:-}" ]]; then
          log "  ↳ 先移除引用 ${ref} 的旧容器: ${cids}"
          if "${dc[@]}" rm -f ${cids} >/dev/null 2>&1; then
            if "${dc[@]}" rmi "${ref}" >/dev/null 2>&1; then
              log "  ✓ 已删除（旧容器已移除）: ${ref}"
            else
              warn "  ✗ 仍无法删除: ${ref}"
            fi
          else
            warn "  ✗ 移除旧容器失败，跳过: ${ref}"
          fi
        else
          warn "  ✗ 删除失败（可能被运行容器引用，跳过）: ${ref}"
        fi
      fi
    fi
  done <<< "${imgs}"
}

prune_one_context "远端 daemon (${DOCKER_CONTEXT})" docker --context "${DOCKER_CONTEXT}"
[[ "${DO_LOCAL}" -eq 1 ]] && prune_one_context "本地 orbstack (${LOCAL_CONTEXT})" docker --context "${LOCAL_CONTEXT}"

log "清理完成。"
