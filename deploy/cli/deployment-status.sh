#!/usr/bin/env bash

movo_prepare_deployment_record() {
  mkdir -p "${ROOT_DIR}/.movo-runtime"
}

movo_record_deployment() {
  local state_dir="${ROOT_DIR}/.movo-runtime"
  local fingerprint_file="${state_dir}/image-fingerprint.txt"
  local images_file="${state_dir}/image-ids.txt"
  local record_file="${state_dir}/deployment.json"
  local fingerprint version images
  local -a containers=()
  mapfile -t containers < <(movo_compose ps -q)
  if [[ ${#containers[@]} -eq 0 ]]; then
    return 1
  fi
  images="$("${DOCKER_BIN}" inspect --format '{{index .Config.Labels "com.docker.compose.service"}} {{.Image}}' "${containers[@]}" | LC_ALL=C sort)"
  fingerprint="$(printf '%s\n' "${images}" | cksum)"
  if [[ -f "${record_file}" && -f "${images_file}" && -f "${fingerprint_file}" && "$(cat "${fingerprint_file}")" == "${fingerprint}" ]]; then
    return 0
  fi
  version="${MOVO_VERSION:-latest}"
  if [[ ! "${version}" =~ ^[a-zA-Z0-9._-]+$ ]]; then
    version="unknown"
  fi
  # 源码版本：优先用当前仓库 HEAD；镜像若带 OCI revision label 会在读取侧覆盖，
  # 但本地构建通常没有该 label，这里保证「代码版本」页至少有可追溯的 commit。
  commit="$("${GIT_BIN:-git}" -C "${ROOT_DIR}" rev-parse --short=12 HEAD 2>/dev/null || true)"
  if [[ ! "${commit}" =~ ^[0-9a-f]{7,40}$ ]]; then
    commit="unknown"
  fi
  umask 077
  printf '%s\n' "${images}" > "${images_file}.tmp"
  mv "${images_file}.tmp" "${images_file}"
  printf '{"upgradedAt":"%s","version":"%s","commit":"%s"}\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "${version}" "${commit}" > "${record_file}.tmp"
  mv "${record_file}.tmp" "${record_file}"
  printf '%s\n' "${fingerprint}" > "${fingerprint_file}"
}
