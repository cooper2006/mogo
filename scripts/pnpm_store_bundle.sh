#!/usr/bin/env bash
set -Eeuo pipefail

# pnpm store + CLI offline bundle.
#
# Why this exists: on a linux/amd64 build emulated by QEMU on an arm64 Mac,
# the three Node services spent 18 minutes in `npm install -g pnpm` +
# `pnpm install --frozen-lockfile` (amd64-build.log: #49 DONE 722.6s,
# #50 DONE 1081.2s) pulling 600-1000 tarballs from registry.npmmirror.com.
# apt / pip / playwright / docling already ship offline bundles; pnpm was the
# last gap.
#
# Two things have to be offline, not just one:
#   * the content-addressable store (v11/files/...), i.e. the project deps;
#   * the pnpm CLI itself. pnpm >=11 is NOT a JS package -- `npm install -g
#     pnpm` resolves @pnpm/exe.<platform-arch>, a ~40MB native binary. That
#     single step cost 722s under QEMU and is the reason a store-only bundle
#     still leaves the build online for 12 minutes.
# The CLI is therefore shipped per target architecture and selected by the
# Dockerfiles' TARGETARCH (Debian/glibc variants: linux-x64 / linux-arm64).
# Both architectures are bundled by default. amd64 is the QEMU target where
# `npm install -g pnpm` costs 722s; arm64 is the native dev target, and even
# though npm is fast there when online, an offline / restricted build network
# makes that fallback hang (measured: ETIMEDOUT after 495s at Dockerfile:24).
# The store itself is arch-agnostic and is always used offline.
#
# Layout (mirrors the other bundles):
#   base-images/pnpm-store/              durable cache (git-ignored)
#       store/v11/files/...              pnpm content-addressable store
#       pnpm-cli/amd64/pnpm              @pnpm/exe.linux-x64 binary
#       pnpm-cli/arm64/pnpm              @pnpm/exe.linux-arm64 binary
#       manifest.txt
#   apps/admin-web/pnpm-store-bundle.tar.gz                    (generated)
#   apps/user-web/pnpm-store-bundle.tar.gz                     (generated)
#   services/chat-api/dsh/runtime-host/pnpm-store-bundle.tar.gz (generated)
#
# Usage:
#   scripts/pnpm_store_bundle.sh fetch    # RECOMMENDED: rebuild a complete multi-arch
#                                        #   store on the host from committed lockfiles
#   scripts/pnpm_store_bundle.sh cli      # refresh only the pnpm CLI binaries
#   scripts/pnpm_store_bundle.sh pack     # write the three build-context bundles
#   scripts/pnpm_store_bundle.sh save     # export the BuildKit /pnpm-store cache mount
#                                        #   (may be incomplete; OVERWRITES the store)
#   scripts/pnpm_store_bundle.sh status   # show cache + bundle state
#
# Env overrides: DOCKER_BIN, BUILDX_BUILDER, MOGO_DOCKER_CONTEXT, ARCH_LIST
#   (default "amd64 arm64"), PNPM_VERSION, MOGO_NPM_REGISTRY,
#   PNPM_CLI_TGZ_DIR (reuse already-downloaded @pnpm/exe.*.tgz files).
#   An existing binary at base-images/pnpm-store/pnpm-cli/<arch>/pnpm is
#   reused as-is, so `docker cp` from a running container works offline.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

# shellcheck source=scripts/bundle_pack_lib.sh
source "${ROOT_DIR}/scripts/bundle_pack_lib.sh"

BUNDLE_NAME="pnpm-store-bundle.tar.gz"
CACHE_DIR="base-images/pnpm-store"
PNPM_VERSION="${PNPM_VERSION:-12.14.0}"
NPM_REGISTRY="${MOGO_NPM_REGISTRY:-https://registry.npmmirror.com}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
BUILDX_BUILDER="${BUILDX_BUILDER:-kiri}"
DOCKER_CONTEXT="${MOGO_DOCKER_CONTEXT:-kiri}"
# Ship both by default: dropping either one makes that architecture fall back
# to `npm install -g pnpm`, which hangs on an offline build network.
ARCH_LIST="${ARCH_LIST:-amd64 arm64}"

CONTEXTS=(
  "apps/admin-web"
  "apps/user-web"
  "services/chat-api/dsh/runtime-host"
)

log()  { printf '[pnpm-bundle] %s\n' "$*"; }
die()  { printf '[pnpm-bundle] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  sed -n '2,45p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# Map a Docker TARGETARCH to the @pnpm/exe.* package suffix (glibc builds).
cli_package_for_arch() {
  case "$1" in
    amd64) printf 'linux-x64' ;;
    arm64) printf 'linux-arm64' ;;
    *)     die "不支持的架构: $1（可用 amd64 / arm64）" ;;
  esac
}

# Export the shared BuildKit cache mount. The cache mount id defaults to its
# target path (/pnpm-store), so this is the very same store the three
# Dockerfiles fill -- no network, no re-download.
write_store_export_dockerfile() {
  local stage="$1"
  mkdir -p "${stage}"
  cat > "${stage}/Dockerfile" <<'DOCKERFILE'
FROM alpine:3.21 AS collect
RUN --mount=type=cache,target=/pnpm-store,sharing=locked \
    mkdir -p /out \
    && (tar -czf /out/pnpm-store.tar.gz -C /pnpm-store . 2>/dev/null || true)
FROM scratch
COPY --from=collect /out/pnpm-store.tar.gz /pnpm-store.tar.gz
DOCKERFILE
}

save_store() {
  local stage export_dir
  stage="$(bundle_stage_dir)" || die "无法创建 staging 目录"
  export_dir="${BUNDLE_STAGE_ROOT}/pnpm-store-export"
  rm -rf "${export_dir}"; mkdir -p "${export_dir}"
  write_store_export_dockerfile "${stage}"

  log "从 BuildKit cache mount /pnpm-store 导出（builder=${BUILDX_BUILDER}, context=${DOCKER_CONTEXT}）..."
  "${DOCKER_BIN}" --context "${DOCKER_CONTEXT}" \
    buildx build --builder "${BUILDX_BUILDER}" \
    -f "${stage}/Dockerfile" \
    --output "type=local,dest=${export_dir}" "${stage}" >/dev/null \
    || die "buildx 导出 store 失败"

  [[ -s "${export_dir}/pnpm-store.tar.gz" ]] || die "导出的 store 为空（cache mount 无内容）"
  rm -rf "${CACHE_DIR}/store"; mkdir -p "${CACHE_DIR}/store"
  tar -xzf "${export_dir}/pnpm-store.tar.gz" -C "${CACHE_DIR}/store"
  [[ -d "${CACHE_DIR}/store/v11/files" ]] || die "store 结构异常：缺少 v11/files"
  rm -rf "${stage}" "${export_dir}"
  log "store 就绪：$(find "${CACHE_DIR}/store" -type f | wc -l | tr -d ' ') 个文件，$(du -sh "${CACHE_DIR}/store" | cut -f1)"
}

# One native binary per target arch, downloaded on the HOST (no QEMU). These
# files are architecture-specific but tiny compared to the store, and reusing
# already-present binaries keeps `save` idempotent and offline-friendly.
save_cli() {
  local arch pkg tarball tmp url
  tmp="${BUNDLE_STAGE_ROOT}/pnpm-cli-unpack"
  mkdir -p "${CACHE_DIR}/pnpm-cli" "${tmp}"
  for arch in ${ARCH_LIST}; do
    [[ -x "${CACHE_DIR}/pnpm-cli/${arch}/pnpm" ]] && {
      log "pnpm CLI ${arch}: 已缓存，跳过"; continue
    }
    pkg="$(cli_package_for_arch "${arch}")"
    tarball="exe.${pkg}-${PNPM_VERSION}.tgz"
    url="${NPM_REGISTRY}/@pnpm/exe.${pkg}/-/exe.${pkg}-${PNPM_VERSION}.tgz"
    if [[ -n "${PNPM_CLI_TGZ_DIR:-}" && -s "${PNPM_CLI_TGZ_DIR}/${tarball}" ]]; then
      log "pnpm CLI ${arch}: 复用 ${PNPM_CLI_TGZ_DIR}/${tarball}"
      cp -f "${PNPM_CLI_TGZ_DIR}/${tarball}" "${tmp}/${tarball}"
    elif [[ -n "${PNPM_CLI_TGZ_DIR:-}" && -s "${PNPM_CLI_TGZ_DIR}/exe.${pkg}.tgz" ]]; then
      log "pnpm CLI ${arch}: 复用 ${PNPM_CLI_TGZ_DIR}/exe.${pkg}.tgz"
      cp -f "${PNPM_CLI_TGZ_DIR}/exe.${pkg}.tgz" "${tmp}/${tarball}"
    else
      log "pnpm CLI ${arch}: 下载 ${url}"
      curl -fsSL --retry 3 --connect-timeout 20 -o "${tmp}/${tarball}" "${url}" \
        || die "下载失败: ${url}"
    fi
    rm -rf "${tmp}/unpack"; mkdir -p "${tmp}/unpack"
    tar -xzf "${tmp}/${tarball}" -C "${tmp}/unpack" package/pnpm \
      || die "tarball 中缺少 package/pnpm: ${tarball}"
    mkdir -p "${CACHE_DIR}/pnpm-cli/${arch}"
    install -m 0755 "${tmp}/unpack/package/pnpm" "${CACHE_DIR}/pnpm-cli/${arch}/pnpm"
    log "pnpm CLI ${arch}: $(du -h "${CACHE_DIR}/pnpm-cli/${arch}/pnpm" | cut -f1) 已就绪"
  done
  rm -rf "${tmp}"
}

write_manifest() {
  local source="${1:-buildkit-cache-mount:/pnpm-store}"
  {
    printf 'pnpm-store offline bundle\n'
    printf 'pnpm_version=%s\n' "${PNPM_VERSION}"
    printf 'store_source=%s\n' "${source}"
    printf 'cli_arches=%s\n' "$(echo "${ARCH_LIST}" | tr ' ' ',')"
    printf 'generated=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    printf 'store_files=%s\n' "$(find "${CACHE_DIR}/store/v11/files" -type f | wc -l | tr -d ' ')"
    if command -v sqlite3 >/dev/null 2>&1 && [[ -f "${CACHE_DIR}/store/v11/index.db" ]]; then
      printf 'store_index_rows=%s\n' "$(sqlite3 "${CACHE_DIR}/store/v11/index.db" 'select count(*) from package_index;' 2>/dev/null)"
    fi
  } > "${CACHE_DIR}/manifest.txt"
}

current_manifest_source() {
  sed -n 's/^store_source=//p' "${CACHE_DIR}/manifest.txt" 2>/dev/null | head -1
}

# Refresh only the CLI binaries. Useful after adding an architecture without
# rebuilding the (expensive, complete) store.
refresh_cli() {
  save_cli
  write_manifest "$(current_manifest_source)"
  log "CLI 就绪；store 未改动"
}

save() {
  if [[ "$(current_manifest_source)" == pnpm-fetch:* ]]; then
    log "WARN: 当前 store 由 fetch 生成（完备多架构）；save 会用 BuildKit cache mount 覆盖它。仅刷新 CLI 请用 '$0 cli'"
  fi
  save_store
  save_cli
  write_manifest
  log "缓存就绪：${CACHE_DIR}"
}

# Rebuild the store from the committed lockfiles ON THE HOST. The build
# containers are frequently offline (that is why this bundle exists), while
# the host has registry access. `supportedArchitectures` makes one `pnpm
# fetch` pass pull every platform variant, so a single store covers native
# arm64 dev builds and QEMU-emulated amd64 builds. The old implementation ran
# `pnpm fetch` inside a linux/<arch> container and could not work offline.
fetch() {
  local svc src stage store_abs name
  store_abs="${ROOT_DIR}/${CACHE_DIR}/store"
  mkdir -p "${store_abs}"
  command -v pnpm >/dev/null 2>&1 \
    || die "宿主机未找到 pnpm（fetch 在宿主机运行，需要可联网的 pnpm ${PNPM_VERSION}）"

  # pnpm reads npm_config_* proxy settings; HTTP(S)_PROXY alone is not always
  # picked up. Pass them explicitly so a proxied host works out of the box.
  local -a proxy_env=()
  if [[ -n "${HTTPS_PROXY:-${https_proxy:-}}" ]]; then
    proxy_env+=( "npm_config_https_proxy=${HTTPS_PROXY:-${https_proxy}}" )
  fi
  if [[ -n "${HTTP_PROXY:-${http_proxy:-}}" ]]; then
    proxy_env+=( "npm_config_proxy=${HTTP_PROXY:-${http_proxy}}" )
  fi

  for svc in "${CONTEXTS[@]}"; do
    src="${ROOT_DIR}/${svc}"
    [[ -f "${src}/pnpm-lock.yaml" ]] || die "缺少 lockfile: ${svc}"
    name="$(printf '%s' "${svc}" | tr '/' '-')"
    stage="${BUNDLE_STAGE_ROOT}/fetch-${name}"
    rm -rf "${stage}"; mkdir -p "${stage}"
    cp -f "${src}/package.json" "${src}/pnpm-lock.yaml" "${stage}/"
    if [[ -f "${src}/pnpm-workspace.yaml" ]]; then
      cp -f "${src}/pnpm-workspace.yaml" "${stage}/"
    fi
    cat >> "${stage}/pnpm-workspace.yaml" <<'YAML'

supportedArchitectures:
  os:
    - current
    - linux
  cpu:
    - current
    - x64
    - arm64
  libc:
    - current
    - glibc
YAML
    log "fetch: ${svc}（全量依赖，linux/amd64 + linux/arm64）"
    env "${proxy_env[@]}" pnpm fetch --store-dir "${store_abs}" --dir "${stage}" \
      || die "fetch 失败: ${svc}"
  done
  write_manifest 'pnpm-fetch:multiarch(linux/amd64+linux/arm64)'
  log "fetch 完成，请运行 pack"
}

pack() {
  [[ -d "${CACHE_DIR}/store/v11/files" ]] || die "缓存不存在，先运行 save 或 fetch"
  [[ -f "${CACHE_DIR}/manifest.txt" ]] || die "manifest.txt 缺失"

  local stage fp rc ctx out arch
  stage="$(bundle_stage_dir)" || die "无法创建 staging 目录"
  mkdir -p "${stage}/bundle/store/v11" "${stage}/bundle/pnpm-cli"
  # A host-generated store also carries links/ (a hardlink cache that can be
  # ~2GB) and projects/. pnpm recreates both inside the container, so ship
  # only the content-addressed files and the package index. tar through a pipe
  # is much faster than `cp -a` for ~60k small files on APFS.
  tar -cf - -C "${CACHE_DIR}/store/v11" files index.db \
    | tar -xf - -C "${stage}/bundle/store/v11"
  for arch in ${ARCH_LIST}; do
    [[ -x "${CACHE_DIR}/pnpm-cli/${arch}/pnpm" ]] || die "缺少 pnpm CLI: ${arch}"
    mkdir -p "${stage}/bundle/pnpm-cli/${arch}"
    cp -a "${CACHE_DIR}/pnpm-cli/${arch}/pnpm" "${stage}/bundle/pnpm-cli/${arch}/pnpm"
  done
  cp -a "${CACHE_DIR}/manifest.txt" "${stage}/bundle/manifest.txt"

  fp="$(bundle_fingerprint "${CACHE_DIR}/store/v11/files" "${CACHE_DIR}/store/v11/index.db" "${CACHE_DIR}/pnpm-cli" "${CACHE_DIR}/manifest.txt")"
  for ctx in "${CONTEXTS[@]}"; do
    out="${ctx}/${BUNDLE_NAME}"
    rc=0
    bundle_pack "${out}" "${stage}/bundle" "${fp}" || rc=$?
    case "${rc}" in
      0) log "  ${out} -> repacked ($(du -h "${out}" | cut -f1))" ;;
      1) log "  ${out} -> unchanged" ;;
      *) die "打包失败: ${out}" ;;
    esac
  done
  rm -rf "${stage}"
  log "pack 完成"
}

status() {
  local ctx out arch
  log "cache: ${CACHE_DIR}"
  if [[ -f "${CACHE_DIR}/manifest.txt" ]]; then
    sed 's/^/  /' "${CACHE_DIR}/manifest.txt"
    printf '  store_files_now=%s\n' "$(find "${CACHE_DIR}/store/v11/files" -type f 2>/dev/null | wc -l | tr -d ' ')"
  else
    log "  (无缓存)"
  fi
  for arch in ${ARCH_LIST}; do
    if [[ -x "${CACHE_DIR}/pnpm-cli/${arch}/pnpm" ]]; then
      log "  cli/${arch}: $(du -h "${CACHE_DIR}/pnpm-cli/${arch}/pnpm" | cut -f1)"
    else
      log "  cli/${arch}: MISSING"
    fi
  done
  for ctx in "${CONTEXTS[@]}"; do
    out="${ctx}/${BUNDLE_NAME}"
    if [[ -f "${out}" ]]; then
      log "  ${out}: $(du -h "${out}" | cut -f1)"
    else
      log "  ${out}: MISSING"
    fi
  done
}

case "${1:-}" in
  save)   save ;;
  fetch)  fetch ;;
  cli)    refresh_cli ;;
  pack)   pack ;;
  status) status ;;
  -h|--help|"") usage ;;
  *) die "未知子命令: $1（可用: save / fetch / cli / pack / status）" ;;
esac
