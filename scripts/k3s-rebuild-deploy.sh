#!/usr/bin/env bash
set -Eeuo pipefail

# k3s 本地开发部署：构建镜像 → 导出 tar → 传入 k3s 节点 → containerd 导入 → apply manifests → 验证
#
# Why this exists: 本地开发场景需要把代码改动推到 Kiri 上的 k3s 集群（节点容器 kiri-k8s）
# 跑起来验证，但不走生产部署逻辑（deploy/production/* 不动）。
# k3s 用 containerd 管镜像，与 Kiri 的 Docker daemon 是两套 image store，
# docker build 出来的镜像 k3s 拉不到，必须经 tar 导出/导入桥接。
#
# 前置条件：
#   1. Kiri docker context 可用，且默认 context 指向 kiri（或显式设置 DOCKER_CTX）
#   2. k3s 节点容器在运行，节点 Ready 且无 DiskPressure（preflight 会检查）
#   3. k3s 节点上 secrets / PVC 已就位（首次需手动确认）
#   4. k3s containerd 内已有 pause 镜像（缺失会导致所有 Pod 起不来，preflight 会告警）
#
# 镜像清单：
#   - 7 个业务镜像  ghcr.io/mogoai/<svc>:<IMAGE_TAG>
#   - 3 个基础镜像  mongo:8.3.13 / redis:7.4.2-alpine / semitechnologies/weaviate:1.25.7
#   基础镜像同样必须导入，否则 mongo/redis/weaviate 三个 Pod 会 ImagePullBackOff
#   （k3s 的 registries.yaml 只代理 ghcr.io/quay.io/registry.k8s.io，docker.io 拉取不通）。
#   基础镜像 tar 名 base-<short>.tar；可预先用离线包切分好放进 OUTDIR，export 会直接复用。
#
# ⚠️  builder 重复问题：kiri context 下曾存在 kiri 和 kiri-build 两个 builder
#     都指向同一个 buildkit 容器，导致 buildx history 出现重复构建记录。
#     本脚本默认使用 kiri-bk2（独立 builder），并提供 builder-clean 清理冗余。
#     注意：新建的 buildkit 容器必须接入 mogo-build-net 且 DNS 指向 127.0.0.11，
#     否则解析不到 mogo-local-reg 镜像源（builder-ensure 会做检查并告警）。
#
# Usage:
#   scripts/k3s-rebuild-deploy.sh all            # 全流程
#   scripts/k3s-rebuild-deploy.sh preflight      # 仅环境自检
#   scripts/k3s-rebuild-deploy.sh build          # 仅构建镜像
#   scripts/k3s-rebuild-deploy.sh export         # 仅导出 tar
#   scripts/k3s-rebuild-deploy.sh scp            # 仅传 tar 到 k3s 节点（docker cp）
#   scripts/k3s-rebuild-deploy.sh import         # 仅在 k3s 节点导入 containerd
#   scripts/k3s-rebuild-deploy.sh apply          # 仅更新 manifests 并 apply + 重启
#   scripts/k3s-rebuild-deploy.sh verify         # 仅验证服务状态（不通过则非零退出）
#   scripts/k3s-rebuild-deploy.sh builder-clean  # 清理冗余 builder
#   scripts/k3s-rebuild-deploy.sh clean          # 清理 k3s 节点上的 tar
#
# Env overrides:
#   DOCKER_CTX     (default: kiri)          docker context 名
#   K3S_NS         (default: mogo)          k8s namespace
#   K3S_NODE       (default: kiri-k8s)      k3s 节点容器名（docker cp / exec 目标）
#   K3S_CTX        (default: kiri-k8s)      保留字段（当前 apply 走容器内 kubectl）
#   IMAGE_TAG      (default: git short HEAD)
#   OUTDIR         (default: /tmp/mogo-k3s-images)
#   REMOTE_DIR     (default: /tmp/mogo-k3s-images)
#   DOCKER_BIN     (default: docker)
#   BUILDX_BUILDER (default: kiri-bk2)
#   BASE_BUNDLE    (default: backups/kiri-to-dory-20261108/images.tar)
#                  基础镜像离线包；本机 Docker 里没有基础镜像时自动切出 base-*.tar
#   SKIP_BUILD     (default: 0)    all 流程跳过 build，复用已有镜像/tar（离线重部署）
#   FORCE_EXPORT   (default: 0)    强制重新 docker save，覆盖已有 tar
#   KEEP_TARS      (default: 0)    import 后保留节点上的 tar（默认边导边删，降低磁盘峰值）
#   VERIFY_TIMEOUT (default: 120)  每个 deployment 的 rollout 等待秒数

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

DOCKER_BIN="${DOCKER_BIN:-docker}"
DOCKER_CTX="${DOCKER_CTX:-kiri}"
K3S_NS="${K3S_NS:-mogo}"
K3S_CTX="${K3S_CTX:-kiri-k8s}"
K3S_NODE="${K3S_NODE:-kiri-k8s}"
OUTDIR="${OUTDIR:-/tmp/mogo-k3s-images}"
REMOTE_DIR="${REMOTE_DIR:-/tmp/mogo-k3s-images}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"
BUILDX_BUILDER="${BUILDX_BUILDER:-kiri-bk2}"
BASE_BUNDLE="${BASE_BUNDLE:-${ROOT_DIR}/backups/kiri-to-dory-20261108/images.tar}"
SKIP_BUILD="${SKIP_BUILD:-0}"
FORCE_EXPORT="${FORCE_EXPORT:-0}"
KEEP_TARS="${KEEP_TARS:-0}"
VERIFY_TIMEOUT="${VERIFY_TIMEOUT:-120}"

SERVICES=(admin-api chat-api document-parser dsh-runtime-host user-web admin-web gateway)
BASE_IMAGES=(mongo:8.3.13 redis:7.4.2-alpine semitechnologies/weaviate:1.25.7)
BASE_NAMES=(mongo redis weaviate)
TAR_SPECS=()

# ── helpers ────────────────────────────────────────────────────────────────

log()  { printf '[k3s-deploy] %s\n' "$*"; }
die()  { printf '[k3s-deploy][ERROR] %s\n' "$*" >&2; exit 1; }

docker_cli() { "${DOCKER_BIN}" --context "${DOCKER_CTX}" "$@"; }

docker_cp() {
  # Copy a file into the k3s node container
  docker_cli cp "$1" "${K3S_NODE}:$2"
}

docker_exec() {
  # Run a command inside the k3s node container
  docker_cli exec "${K3S_NODE}" "$@"
}

docker_exec_i() {
  # Run a command inside the k3s node container with stdin attached
  docker_cli exec -i "${K3S_NODE}" "$@"
}

# TAR_SPECS entries: "<tar filename>|<docker image ref>"
build_specs() {
  TAR_SPECS=()
  local svc i
  for svc in "${SERVICES[@]}"; do
    TAR_SPECS+=("${svc}.tar|ghcr.io/mogoai/${svc}:${IMAGE_TAG}")
  done
  for i in "${!BASE_IMAGES[@]}"; do
    TAR_SPECS+=("base-${BASE_NAMES[$i]}.tar|${BASE_IMAGES[$i]}")
  done
}

file_size() {
  # Portable file size in bytes (macOS BSD stat vs GNU stat)
  stat -f%z "$1" 2>/dev/null || stat -c%s "$1"
}

# Split the 3 base images out of a docker save bundle when they are neither in
# the local Docker store nor already present as tar files. The bundle is a
# Docker OCI-store save archive: manifest.json + blobs/sha256/*.
# Keep WANTED in sync with BASE_IMAGES / BASE_NAMES above.
split_base_bundle() {
  [[ -f "${BASE_BUNDLE}" ]] \
    || die "base image bundle not found: ${BASE_BUNDLE} (override with BASE_BUNDLE)"
  command -v python3 >/dev/null 2>&1 || die "python3 is required to split the base image bundle"
  log "  splitting base images from ${BASE_BUNDLE} ..."
  python3 - "${BASE_BUNDLE}" "${OUTDIR}" <<'PY'
import io
import json
import os
import sys
import tarfile

WANTED = {
    "mongo:8.3.13": "mongo",
    "redis:7.4.2-alpine": "redis",
    "semitechnologies/weaviate:1.25.7": "weaviate",
}
bundle, outdir = sys.argv[1], sys.argv[2]
os.makedirs(outdir, exist_ok=True)

with tarfile.open(bundle) as src:
    manifest = json.load(src.extractfile("manifest.json"))
    members = {m.name: m for m in src.getmembers() if m.isfile()}
    for entry in manifest:
        tag = next((t for t in (entry.get("RepoTags") or []) if t in WANTED), None)
        if tag is None:
            continue
        path = os.path.join(outdir, "base-" + WANTED[tag] + ".tar")
        payload = json.dumps([entry], separators=(",", ":")).encode()
        with tarfile.open(path, "w") as out:
            info = tarfile.TarInfo("manifest.json")
            info.size = len(payload)
            out.addfile(info, io.BytesIO(payload))
            for blob in dict.fromkeys([entry["Config"], *entry["Layers"]]):
                member = members.get(blob)
                if member is None:
                    raise SystemExit("missing blob in bundle: " + blob)
                out.addfile(member, src.extractfile(member))
        print("  generated " + path)
PY
}

# ── steps ───────────────────────────────────────────────────────────────────

step_preflight() {
  log "=== Preflight: environment check ==="

  local status
  status=$(docker_cli ps --filter "name=^${K3S_NODE}$" --format '{{.Status}}' 2>/dev/null || true)
  [[ "${status}" == Up* ]] || die "k3s node container '${K3S_NODE}' is not running (status='${status}')"
  log "  node container: ${status}"

  if ! docker_exec kubectl get nodes --no-headers 2>/dev/null | grep -q ' Ready '; then
    log "  WARNING: k3s node is not Ready yet"
  else
    log "  k3s node: Ready"
  fi

  # Disk pressure is the most common cause of evicted / pending pods in this setup
  local avail_kb avail_gb
  avail_kb=$(docker_exec sh -c "df -Pk / | tail -1 | tr -s ' ' | cut -d' ' -f4" 2>/dev/null || echo 0)
  avail_gb=$(( avail_kb / 1024 / 1024 ))
  log "  node free space: ${avail_gb} GiB"
  # Re-importing the same tags reuses existing blobs, so a steady-state node at
  # ~6-7 GiB free is fine; only a first full import needs more headroom.
  (( avail_gb >= 6 )) || die "node free space < 6 GiB; clean old images/tars first (DiskPressure risk)"

  if docker_exec kubectl describe nodes 2>/dev/null | grep -q 'DiskPressure.*True'; then
    die "node reports DiskPressure=True; free space before retry"
  fi

  if ! docker_exec ctr --namespace k8s.io image ls 2>/dev/null | grep -q 'rancher/mirrored-pause'; then
    log "  WARNING: pause image missing in containerd; pods will fail to start"
  else
    log "  pause image: present"
  fi

  # Host entry: mogo-gateway-relay L4-forwards 3000/8443 to the k3s hostPort.
  # Its upstream is resolved via Docker embedded DNS, which only works while
  # relay and kiri-k8s share a user-defined network.
  local relay_status relay_nets
  relay_status=$(docker_cli ps --filter "name=^mogo-gateway-relay$" \
    --format '{{.Status}}' 2>/dev/null || true)
  if [[ -z "${relay_status}" || "${relay_status}" != Up* ]]; then
    log "  WARNING: mogo-gateway-relay not running (${relay_status:-absent}); localhost:3000 unreachable"
  else
    relay_nets=$(docker_cli inspect mogo-gateway-relay \
      --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' 2>/dev/null || true)
    if [[ "${relay_nets}" != *mogo-build-net* ]]; then
      log "  WARNING: relay is not on mogo-build-net; kiri-k8s DNS will not resolve"
      log "  -> docker --context ${DOCKER_CTX} network connect mogo-build-net mogo-gateway-relay"
    else
      log "  host relay: running on mogo-build-net"
    fi
  fi

  build_specs
  local -a missing=()
  local spec name ref
  for spec in "${TAR_SPECS[@]}"; do
    IFS='|' read -r name ref <<< "${spec}"
    [[ -f "${OUTDIR}/${name}" ]] || missing+=("${name}")
  done
  if (( ${#missing[@]} > 0 )); then
    log "  tar files not yet present (${#missing[@]}): ${missing[*]}"
    log "  -> will be produced by 'build' + 'export'"
  else
    log "  all 10 tar files present in ${OUTDIR}"
  fi
}

step_builder_ensure() {
  log "=== Ensuring single, healthy buildx builder ==="

  local desired="${BUILDX_BUILDER:-kiri-bk2}"
  local -a all_builders=()
  while IFS= read -r line; do
    all_builders+=("$line")
  done < <(docker_cli buildx ls 2>/dev/null \
    | grep -E '^[a-zA-Z]' | awk '{print $1}' | tr -d '*')

  local running=0 b
  for b in "${all_builders[@]}"; do
    if docker_cli buildx inspect "${b}" 2>/dev/null | grep -q 'Status:.*running'; then
      running=$((running + 1))
    fi
  done

  if (( running > 1 )); then
    log "  WARNING: ${running} running builders detected (duplicate buildx history risk)"
    log "  Run 'scripts/k3s-rebuild-deploy.sh builder-clean' to remove extras"
  fi

  docker_cli buildx use "${desired}" 2>/dev/null || true

  # A freshly created buildkit container lands on the default bridge network and
  # cannot resolve mogo-local-reg; it must be on mogo-build-net with embedded DNS.
  local bk_container="buildx_buildkit_${desired}0"
  if docker_cli inspect "${bk_container}" >/dev/null 2>&1; then
    local networks
    networks=$(docker_cli inspect "${bk_container}" \
      --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' 2>/dev/null || true)
    if [[ "${networks}" != *mogo-build-net* ]]; then
      log "  WARNING: ${bk_container} is not on mogo-build-net (${networks:-none})"
      log "  -> docker --context ${DOCKER_CTX} network connect mogo-build-net ${bk_container}"
    fi
    if ! docker_cli exec "${bk_container}" getent hosts mogo-local-reg >/dev/null 2>&1; then
      log "  WARNING: ${bk_container} cannot resolve mogo-local-reg"
      log "  -> docker --context ${DOCKER_CTX} exec ${bk_container} sh -c 'echo nameserver 127.0.0.11 > /etc/resolv.conf'"
    fi
  fi
  log "  builder: ${desired}"
}

step_build() {
  log "=== Step 1/5: building images (tag=${IMAGE_TAG}) ==="

  step_builder_ensure

  DOCKER_CONTEXT="${DOCKER_CTX}" \
  BUILDX_BUILDER="${BUILDX_BUILDER:-kiri-bk2}" \
  MOGO_BASE_IMAGE_POLICY=local \
  MOGO_DATA_BACKEND=mongo \
  APT_OFFLINE_INSTALL=true PIP_OFFLINE_INSTALL=true \
    ./mogo up --build

  # Verify all 7 images exist with the expected tag
  local svc
  for svc in "${SERVICES[@]}"; do
    if ! docker_cli images --format '{{.Repository}}:{{.Tag}}' \
        | grep -q "ghcr.io/mogoai/${svc}:${IMAGE_TAG}"; then
      die "image ghcr.io/mogoai/${svc}:${IMAGE_TAG} not found after build"
    fi
  done
  log "all 7 images built and verified"
}

step_export() {
  log "=== Step 2/5: exporting images to tar ==="
  build_specs
  mkdir -p "${OUTDIR}"

  # Base images are pulled by compose, not built. If the local Docker store was
  # pruned and no tar exists, fall back to the offline bundle.
  local i need_split=0
  for i in "${!BASE_IMAGES[@]}"; do
    if [[ ! -f "${OUTDIR}/base-${BASE_NAMES[$i]}.tar" || "${FORCE_EXPORT}" == "1" ]] \
       && ! docker_cli image inspect "${BASE_IMAGES[$i]}" >/dev/null 2>&1; then
      need_split=1
    fi
  done
  if (( need_split )); then
    split_base_bundle
  fi

  local spec name ref tar
  for spec in "${TAR_SPECS[@]}"; do
    IFS='|' read -r name ref <<< "${spec}"
    tar="${OUTDIR}/${name}"
    if [[ -f "${tar}" && "${FORCE_EXPORT}" != "1" ]]; then
      log "  ${name} exists, skipping (FORCE_EXPORT=1 to re-export)"
      continue
    fi
    if ! docker_cli image inspect "${ref}" >/dev/null 2>&1; then
      if [[ -f "${tar}" ]]; then
        log "  ${name}: source image ${ref} not in local docker, keeping prebuilt tar"
        continue
      fi
      die "missing image ${ref} and no prebuilt tar ${tar}; run 'build' first"
    fi
    log "  exporting ${ref} ..."
    docker_cli save "${ref}" -o "${tar}"
  done

  log "export complete:"
  ls -lh "${OUTDIR}"/*.tar
}

step_scp() {
  log "=== Step 3/5: transferring tars to k3s node ==="
  build_specs
  docker_exec mkdir -p "${REMOTE_DIR}" || die "cannot create remote dir"

  local spec name ref tar remote_tar local_sz remote_sz
  for spec in "${TAR_SPECS[@]}"; do
    IFS='|' read -r name ref <<< "${spec}"
    tar="${OUTDIR}/${name}"
    remote_tar="${REMOTE_DIR}/${name}"
    [[ -f "${tar}" ]] || die "missing ${tar}; run 'export' first"

    local_sz=$(file_size "${tar}")
    remote_sz=$(docker_exec stat -c %s "${remote_tar}" 2>/dev/null || echo 0)
    if [[ "${local_sz}" == "${remote_sz}" ]]; then
      log "  ${name} already on node (${local_sz} bytes), skipping"
      continue
    fi
    log "  copying ${name} (${local_sz} bytes) ..."
    docker_cp "${tar}" "${remote_tar}" || die "failed to copy ${name}"
  done
  log "transfer complete"
}

step_import() {
  log "=== Step 4/5: importing images into k3s containerd ==="
  build_specs

  local spec name ref remote_tar
  for spec in "${TAR_SPECS[@]}"; do
    IFS='|' read -r name ref <<< "${spec}"
    remote_tar="${REMOTE_DIR}/${name}"
    docker_exec test -f "${remote_tar}" || die "missing ${remote_tar} on node; run 'scp' first"
    log "  importing ${name} ..."
    docker_exec ctr --namespace k8s.io image import "${remote_tar}" \
      || die "failed to import ${name}"
    # Delete each tar right after import: keeps peak disk usage low (DiskPressure).
    if [[ "${KEEP_TARS}" != "1" ]]; then
      docker_exec rm -f "${remote_tar}" 2>/dev/null || true
    fi
  done

  log "import complete, relevant images in containerd:"
  docker_exec ctr --namespace k8s.io image ls 2>&1 \
    | grep -E 'mogoai|mongo:|redis:|weaviate' || true
}

step_apply() {
  log "=== Step 5/5: updating manifests and applying to k3s ==="

  local gen_dir="${ROOT_DIR}/deploy/k8s/generated"
  local deploy_file="${gen_dir}/06-deployments.yaml"
  [[ -f "${deploy_file}" ]] || die "missing ${deploy_file}"

  local old_tag
  old_tag=$(grep -oE 'ghcr\.io/mogoai/[^:"]+:[a-f0-9]{7,}' "${deploy_file}" \
            | head -1 | awk -F: '{print $NF}' || true)
  if [[ -n "${old_tag}" && "${old_tag}" != "${IMAGE_TAG}" ]]; then
    log "  updating image tag: ${old_tag} → ${IMAGE_TAG}"
    # -i.bak works on both GNU sed and macOS BSD sed
    sed -E -i.bak "s#(ghcr\.io/mogoai/[^:]+):[a-f0-9]{7,}#\1:${IMAGE_TAG}#g" "${deploy_file}"
    rm -f "${deploy_file}.bak"
  else
    log "  image tag already ${IMAGE_TAG}, no manifest update needed"
  fi

  # Feed manifests over stdin instead of a host path: does not depend on the
  # k3s container bind-mounting /Users.
  local f file
  for f in 00-namespace 01-pvc 02-configmaps 03-secrets 04-bootstrap-job 05-services 06-deployments; do
    file="${gen_dir}/${f}.yaml"
    [[ -f "${file}" ]] || die "missing manifest ${file}"
    log "  applying ${f}.yaml ..."
    docker_exec_i kubectl apply -f - < "${file}" || die "kubectl apply failed for ${f}.yaml"
  done

  # Re-importing the same tag does not change the Deployment spec, so kubectl
  # apply alone would leave old pods (esp. ImagePullBackOff) untouched.
  log "  restarting deployments to pick up imported images ..."
  local -a deployments=()
  while IFS= read -r line; do
    [[ -n "${line}" ]] && deployments+=("${line#deployment.apps/}")
  done < <(docker_exec kubectl get deployments -n "${K3S_NS}" -o name 2>/dev/null || true)
  for f in "${deployments[@]}"; do
    docker_exec kubectl rollout restart "deployment/${f}" -n "${K3S_NS}" >/dev/null \
      || die "rollout restart failed for ${f}"
  done
  log "  ${#deployments[@]} deployments restarted"
  log "apply complete"
}

step_verify() {
  log "=== Verify: service status ==="

  log "  pods:"
  docker_exec kubectl get pods -n "${K3S_NS}" -o wide 2>&1 || true

  local failed=0
  local -a deployments=()
  while IFS= read -r line; do
    [[ -n "${line}" ]] && deployments+=("${line#deployment.apps/}")
  done < <(docker_exec kubectl get deployments -n "${K3S_NS}" -o name 2>/dev/null || true)

  log "  rollout status (timeout ${VERIFY_TIMEOUT}s each):"
  local d
  for d in "${deployments[@]}"; do
    printf '    %-22s ' "${d}"
    if docker_exec kubectl rollout status "deployment/${d}" \
        -n "${K3S_NS}" --timeout="${VERIFY_TIMEOUT}s" >/dev/null 2>&1; then
      printf 'OK\n'
    else
      printf 'NOT READY\n'
      failed=$((failed + 1))
    fi
  done

  local bad_pods
  bad_pods=$(docker_exec kubectl get pods -n "${K3S_NS}" --no-headers 2>/dev/null \
    | awk '$3 !~ /^(Running|Completed)$/ {print $1 "=" $3}' || true)
  if [[ -n "${bad_pods}" ]]; then
    log "  non-running pods: ${bad_pods}"
    failed=$((failed + 1))
  fi

  # HTTP probe from inside the cluster: the host-side relay on :3000 is a
  # separate compose-era nginx and does NOT front the k3s gateway Service.
  local cluster_ip probe http_code
  cluster_ip=$(docker_exec kubectl get svc gateway -n "${K3S_NS}" \
    -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)
  if [[ -n "${cluster_ip}" ]]; then
    probe="wget -S -q -O /dev/null --timeout=10 http://${cluster_ip}/admin/setup 2>&1 | grep -o 'HTTP/1.[01] [0-9][0-9][0-9]' | tail -1 | awk '{print \$2}'"
    http_code=$(docker_exec sh -c "${probe}" 2>/dev/null || true)
    http_code="${http_code:-000}"
  else
    http_code="000"
  fi
  log "  GET http://gateway(${cluster_ip:-?})/admin/setup → ${http_code}"
  if [[ ! "${http_code}" =~ ^2 ]]; then
    log "  gateway HTTP probe did not return 2xx"
    failed=$((failed + 1))
  fi

  # Host-side entry through mogo-gateway-relay: advisory only, because the
  # in-cluster probe above is the authoritative verdict for the deployment.
  local host_code
  host_code=$(curl -sS --noproxy '*' -o /dev/null -w '%{http_code}' --max-time 10 \
    http://localhost:3000/admin/ 2>/dev/null) || host_code="000"
  log "  GET http://localhost:3000/admin/ → ${host_code} (host entry, advisory)"
  if [[ ! "${host_code}" =~ ^2 ]]; then
    log "  (warning: check deploy/k8s/relay/nginx-stream.conf and relay network)"
  fi

  if (( failed > 0 )); then
    die "verify failed: ${failed} check(s) not ready"
  fi
  log "verify passed: all deployments ready, no failing pods"
}

cleanup_remote() {
  log "=== Cleanup: removing tars from k3s node ==="
  build_specs
  local spec name ref
  for spec in "${TAR_SPECS[@]}"; do
    IFS='|' read -r name ref <<< "${spec}"
    docker_exec rm -f "${REMOTE_DIR}/${name}" 2>/dev/null || true
  done
  log "remote tars removed"
}

step_builder_clean() {
  log "=== Cleaning redundant buildx builders ==="

  local desired="${BUILDX_BUILDER:-kiri-bk2}"
  local -a all_builders=()
  while IFS= read -r line; do
    all_builders+=("$line")
  done < <(docker_cli buildx ls 2>/dev/null \
    | grep -E '^[a-zA-Z]' | awk '{print $1}' | tr -d '*')

  local b
  for b in "${all_builders[@]}"; do
    if [[ "${b}" == "${desired}" ]]; then
      log "  keeping ${b} (desired builder)"
      continue
    fi
    if docker_cli context ls --format '{{.Name}}' 2>/dev/null | grep -qx "${b}"; then
      log "  skipping ${b} (docker context builder, cannot remove)"
      continue
    fi
    log "  removing ${b} ..."
    docker_cli buildx rm "${b}" 2>/dev/null || true
  done

  docker_cli buildx use "${desired}" 2>/dev/null || true
  log "  active builder: ${desired}"
  docker_cli buildx ls 2>/dev/null | grep -E "NAME|${desired}" || true
}

# ── main ────────────────────────────────────────────────────────────────────

usage() {
  cat <<EOF
Usage: $0 <step|all|preflight|verify|clean|builder-clean>

Steps (run individually or 'all' for full pipeline):
  preflight      Check node / disk / pause image / tar readiness
  build          Build 7 service images on Kiri (tag = ${IMAGE_TAG})
  export         Export 7 service + 3 base images to tar files in ${OUTDIR}
  scp            Transfer tars to k3s node (docker cp)
  import         Import tars into k3s containerd, deleting each tar afterwards
  apply          Update manifests + kubectl apply + rollout restart
  verify         Check rollout / pods / HTTP probe (non-zero exit on failure)
  builder-clean  Remove redundant buildx builders (fixes duplicate history)
  all            preflight → [build] → export → scp → import → apply → verify → clean
  clean          Remove tars from k3s node

Env: DOCKER_CTX K3S_NS K3S_NODE K3S_CTX IMAGE_TAG OUTDIR REMOTE_DIR
     DOCKER_BIN BUILDX_BUILDER BASE_BUNDLE SKIP_BUILD FORCE_EXPORT
     KEEP_TARS VERIFY_TIMEOUT
EOF
}

case "${1:-}" in
  preflight)      step_preflight ;;
  build)          step_build ;;
  export)         step_export ;;
  scp)            step_scp ;;
  import)         step_import ;;
  apply)          step_apply ;;
  verify)         step_verify ;;
  builder-clean)  step_builder_clean ;;
  clean)          cleanup_remote ;;
  all)
    step_preflight
    if [[ "${SKIP_BUILD}" != "1" ]]; then
      step_build
    else
      log "=== SKIP_BUILD=1: reusing existing images/tars ==="
    fi
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
