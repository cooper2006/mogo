#!/usr/bin/env bash
set -Eeuo pipefail

# k3s 本地开发部署：构建镜像 → 导出 tar → 传入 k3s 节点 → containerd 导入 → apply manifests
#
# Why this exists: 本地开发场景需要把代码改动推到 Kiri 上的 k3s 集群（节点名 kiri-k8s）
# 跑起来验证，但不走生产部署逻辑（deploy/production/* 不动）。
# k3s 用 containerd 管镜像，与 Kiri 的 Docker daemon 是两套 image store，
# docker build 出来的镜像 k3s 拉不到，必须经 tar 导出/导入桥接。
#
# 前置条件：
#   1. k3s 节点可通过 SSH 访问（默认 bonc@kiri-k8s，可 SSH_KEY / SSH_HOST 覆盖）
#   2. k3s 节点磁盘足够（全量镜像约 12 GB）
#   3. k3s 节点上 secrets / PVC 已就位（首次需手动确认）
#   4. 本地 Kiri docker context 可用，且 builder 已就绪
#
# ⚠️  builder 重复问题：kiri context 下曾存在 kiri 和 kiri-build 两个 builder
#     都指向同一个 buildkit 容器，导致 buildx history 出现重复构建记录。
#     本脚本默认使用 kiri-bk2（独立 builder），并提供 builder-clean 清理冗余。
#
# Usage:
#   scripts/k3s-rebuild-deploy.sh all            # 全流程：build → export → scp → import → apply
#   scripts/k3s-rebuild-deploy.sh build          # 仅构建镜像
#   scripts/k3s-rebuild-deploy.sh export          # 仅导出 tar
#   scripts/k3s-rebuild-deploy.sh scp            # 仅传 tar 到 k3s 节点
#   scripts/k3s-rebuild-deploy.sh import         # 仅在 k3s 节点导入 containerd
#   scripts/k3s-rebuild-deploy.sh apply          # 仅更新 manifests 并 apply
#   scripts/k3s-rebuild-deploy.sh verify         # 仅验证服务状态
#   scripts/k3s-rebuild-deploy.sh builder-clean  # 清理冗余 builder，确保唯一
#
# Env overrides:
#   SSH_USER      (default: bonc)
#   SSH_HOST      (default: kiri-k8s)
#   SSH_PORT      (default: 22)
#   SSH_KEY       (default: ~/.ssh/id_ed25519)
#   K3S_NS        (default: mogo)
#   K3S_CTX       (default: kiri-k8s)
#   IMAGE_TAG     (default: git rev-parse --short HEAD)
#   OUTDIR        (default: /tmp/mogo-k3s-images)
#   REMOTE_DIR    (default: /tmp/mogo-k3s-images)
#   DOCKER_BIN    (default: docker)
#   BUILDX_BUILDER (default: kiri-bk2)

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

DOCKER_BIN="${DOCKER_BIN:-docker}"
K3S_NS="${K3S_NS:-mogo}"
K3S_CTX="${K3S_CTX:-kiri-k8s}"
SSH_USER="${SSH_USER:-bonc}"
SSH_HOST="${SSH_HOST:-kiri-k8s}"
SSH_PORT="${SSH_PORT:-22}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
OUTDIR="${OUTDIR:-/tmp/mogo-k3s-images}"
REMOTE_DIR="${REMOTE_DIR:-/tmp/mogo-k3s-images}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"

SERVICES=(admin-api chat-api document-parser dsh-runtime-host user-web admin-web gateway)

# ── helpers ────────────────────────────────────────────────────────────────

log()  { printf '[k3s-deploy] %s\n' "$*"; }
die()  { printf '[k3s-deploy][ERROR] %s\n' "$*" >&2; exit 1; }

ssh_cmd() {
  # Build an scp/ssh command with the right identity and port
  local -a cmd=(scp -P "${SSH_PORT}" -o ConnectTimeout=10 -o TCPKeepAlive=true
                -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
                -o LogLevel=ERROR -i "${SSH_KEY}")
  printf '%s ' "${cmd[@]}"
}

remote() {
  # Run a command on the k3s node via SSH
  local -a cmd=(ssh -p "${SSH_PORT}" -o ConnectTimeout=10 -o TCPKeepAlive=true
                -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
                -o LogLevel=ERROR -i "${SSH_KEY}"
                "${SSH_USER}@${SSH_HOST}")
  printf '%s ' "${cmd[@]}"
}

# ── steps ───────────────────────────────────────────────────────────────────

step_builder_ensure() {
  log "=== Ensuring single, healthy buildx builder ==="

  local desired="${BUILDX_BUILDER:-kiri-bk2}"
  local -a all_builders
  while IFS= read -r line; do
    all_builders+=("$line")
  done < <("${DOCKER_BIN}" --context kiri buildx ls 2>/dev/null \
    | grep -E '^[a-zA-Z]' | awk '{print $1}' | tr -d '*')

  # Count running builders pointing to the same context
  local running=0
  for b in "${all_builders[@]}"; do
    if "${DOCKER_BIN}" --context kiri buildx inspect "${b}" 2>/dev/null \
        | grep -q 'Status:.*running'; then
      running=$((running + 1))
    fi
  done

  if [[ "${running}" -gt 1 ]]; then
    log "  WARNING: ${running} running builders detected (duplicate history risk)"
    log "  Run 'scripts/k3s-rebuild-deploy.sh builder-clean' to remove extras"
  fi

  # Ensure desired builder is selected
  "${DOCKER_BIN}" --context kiri buildx use "${desired}" 2>/dev/null || true
  log "  builder: ${desired}"
}

step_build() {
  log "=== Step 1/5: building images (tag=${IMAGE_TAG}) ==="

  step_builder_ensure

  BUILDX_BUILDER="${BUILDX_BUILDER:-kiri-bk2}" \
  MOGO_BASE_IMAGE_POLICY=local \
  MOGO_DATA_BACKEND=mongo \
  APT_OFFLINE_INSTALL=true PIP_OFFLINE_INSTALL=true \
    ./mogo up --build

  # Verify all 7 images exist with the expected tag
  for svc in "${SERVICES[@]}"; do
    if ! "${DOCKER_BIN}" images --format '{{.Repository}}:{{.Tag}}' \
        | grep -q "ghcr.io/mogoai/${svc}:${IMAGE_TAG}"; then
      die "image ghcr.io/mogoai/${svc}:${IMAGE_TAG} not found after build"
    fi
  done
  log "all 7 images built and verified"
}

step_export() {
  log "=== Step 2/5: exporting images to tar ==="
  mkdir -p "${OUTDIR}"

  for svc in "${SERVICES[@]}"; do
    local tar="${OUTDIR}/${svc}.tar"
    if [[ -f "${tar}" ]]; then
      log "  ${svc}.tar already exists, skipping (set OUTDIR fresh to force re-export)"
      continue
    fi
    log "  exporting ${svc} ..."
    "${DOCKER_BIN}" save "ghcr.io/mogoai/${svc}:${IMAGE_TAG}" -o "${tar}"
  done

  log "export complete:"
  ls -lh "${OUTDIR}"/*.tar
}

step_scp() {
  log "=== Step 3/5: transferring tars to k3s node ==="

  # Ensure remote directory exists
  "$(remote)" "mkdir -p ${REMOTE_DIR}" || die "cannot create remote dir"

  for svc in "${SERVICES[@]}"; do
    local tar="${OUTDIR}/${svc}.tar"
    local remote_tar="${REMOTE_DIR}/${svc}.tar"
    if "$(remote)" "test -f ${remote_tar}" 2>/dev/null; then
      log "  ${svc}.tar already on remote, skipping"
      continue
    fi
    log "  scp ${svc}.tar (${SERVICES[*]}) ..."
    "$(ssh_cmd)" "${tar}" "${SSH_USER}@${SSH_HOST}:${remote_tar}"
  done
  log "transfer complete"
}

step_import() {
  log "=== Step 4/5: importing images into k3s containerd ==="

  for svc in "${SERVICES[@]}"; do
    local remote_tar="${REMOTE_DIR}/${svc}.tar"
    log "  importing ${svc} ..."
    "$(remote)" "ctr --namespace k8s.io image import ${remote_tar}" \
      || die "failed to import ${svc}"
  done

  log "import complete, verifying:"
  "$(remote)" "ctr --namespace k8s.io image ls | grep mogoai" \
    || log "  (warning: no mogoai images found on remote)"
}

step_apply() {
  log "=== Step 5/5: updating manifests and applying to k3s ==="

  # Update image tags in the generated deployment manifests
  local deploy_file="${ROOT_DIR}/deploy/k8s/generated/06-deployments.yaml"
  local old_tag
  old_tag=$(grep -oP '(?<=ghcr\.io/mogoai/[^"]+):[^"]+' "${deploy_file}" \
            | head -1 | cut -d: -f2)

  if [[ "${old_tag}" != "${IMAGE_TAG}" ]]; then
    log "  updating image tag: ${old_tag} → ${IMAGE_TAG}"
    sed -i "s/:\([a-f0-9]\{7,\}\)/:${IMAGE_TAG}/g" "${deploy_file}"
  else
    log "  image tag already ${IMAGE_TAG}, no manifest update needed"
  fi

  # Apply in dependency order
  for f in 00-namespace 01-pvc 03-secrets 04-bootstrap-job 05-services 06-deployments; do
    log "  applying ${f}.yaml ..."
    kubectl --context "${K3S_CTX}" apply -f "${ROOT_DIR}/deploy/k8s/generated/${f}.yaml" \
      || die "kubectl apply failed for ${f}.yaml"
  done
  log "apply complete"
}

step_verify() {
  log "=== Verify: service status ==="

  log "  pods:"
  kubectl --context "${K3S_CTX}" get pods -n "${K3S_NS}" -o wide 2>&1 || true

  log "  rollout status:"
  for svc in gateway admin-api chat-api document-api document-worker; do
    printf '    %-20s ' "${svc}"
    kubectl --context "${K3S_CTX}" rollout status "deployment/${svc}" \
      -n "${K3S_NS}" --timeout=120s 2>&1 || true
  done

  log "  HTTP probe:"
  local http_code
  http_code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 \
    http://localhost:3000/admin/setup 2>/dev/null || echo "000")
  log "  GET /admin/setup → ${http_code}"
}

cleanup_remote() {
  log "=== Cleanup: removing tars from k3s node ==="
  for svc in "${SERVICES[@]}"; do
    "$(remote)" "rm -f ${REMOTE_DIR}/${svc}.tar" 2>/dev/null || true
  done
  log "remote tars removed"
}

step_builder_clean() {
  log "=== Cleaning redundant buildx builders ==="

  local desired="${BUILDX_BUILDER:-kiri-bk2}"
  local -a all_builders
  while IFS= read -r line; do
    all_builders+=("$line")
  done < <("${DOCKER_BIN}" --context kiri buildx ls 2>/dev/null \
    | grep -E '^[a-zA-Z]' | awk '{print $1}' | tr -d '*')

  for b in "${all_builders[@]}"; do
    if [[ "${b}" == "${desired}" ]]; then
      log "  keeping ${b} (desired builder)"
      continue
    fi
    # Skip context builders (cannot be removed via buildx rm)
    if "${DOCKER_BIN}" --context kiri buildx inspect "${b}" 2>/dev/null \
        | grep -q 'Driver Options.*default-load'; then
      # Check if it's a context builder (name matches docker context)
      if "${DOCKER_BIN}" --context kiri context ls --format '{{.Name}}' 2>/dev/null \
          | grep -qx "${b}"; then
        log "  skipping ${b} (context builder, cannot remove)"
        continue
      fi
    fi
    log "  removing ${b} ..."
    "${DOCKER_BIN}" --context kiri buildx rm "${b}" 2>/dev/null || true
  done

  "${DOCKER_BIN}" --context kiri buildx use "${desired}" 2>/dev/null || true
  log "  active builder: ${desired}"
  "${DOCKER_BIN}" --context kiri buildx ls 2>/dev/null | grep -E "NAME|${desired}"
}

# ── main ────────────────────────────────────────────────────────────────────

usage() {
  cat <<EOF
Usage: $0 <step|all|verify|clean|builder-clean>

Steps (run individually or 'all' for full pipeline):
  build          Build 7 service images on Kiri (tag = ${IMAGE_TAG})
  export         Export built images to tar files in ${OUTDIR}
  scp            Transfer tars to k3s node (${SSH_USER}@${SSH_HOST})
  import         Import tars into k3s containerd
  apply          Update manifests + kubectl apply
  verify         Check pod status and HTTP probe
  builder-clean  Remove redundant buildx builders (fixes duplicate history)
  all            Run build → export → scp → import → apply → verify
  clean          Remove tars from k3s node

Env: SSH_USER SSH_HOST SSH_PORT SSH_KEY K3S_NS K3S_CTX IMAGE_TAG OUTDIR REMOTE_DIR
     DOCKER_BIN BUILDX_BUILDER
EOF
}

case "${1:-}" in
  build)          step_build ;;
  export)         step_export ;;
  scp)            step_scp ;;
  import)         step_import ;;
  apply)          step_apply ;;
  verify)         step_verify ;;
  builder-clean)  step_builder_clean ;;
  clean)          cleanup_remote ;;
  all)
    step_build
    step_export
    step_scp
    step_import
    step_apply
    step_verify
    cleanup_remote
    log "=== Done. Full pipeline complete. ==="
    ;;
  *)              usage; exit 2 ;;
esac