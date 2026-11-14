#!/usr/bin/env bash
set -euo pipefail

load_runtime_secrets() {
  local secret_file="${ASKAI_RUNTIME_SECRETS_FILE:-/run/askai-secrets/runtime.env}"
  if [[ -r "${secret_file}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${secret_file}"
    set +a
    
    # Write critical tokens to a readable temp file for Python processes.
    # Docker security profiles may filter os.environ and clear /proc/1/environ,
    # so we write secrets to /tmp where the process has write access.
    # Write ALL secrets to a temp file for Python processes that can't read from os.environ
    # due to Docker security profiles filtering /proc/1/environ
    if command -v cat >/dev/null 2>&1; then
      cp "${secret_file}" "/tmp/mogo-secrets-full.env" 2>/dev/null || true
      chmod 644 "/tmp/mogo-secrets-full.env" 2>/dev/null || true
      # Also write the filtered subset for backwards compatibility
      grep -E "^(ADMIN_BACKEND_SERVICE_TOKEN|ASKAI_ADMIN_BACKEND_SERVICE_TOKEN)=" "${secret_file}" > "/tmp/mogo-secrets.env" 2>/dev/null || true
      chmod 644 "/tmp/mogo-secrets.env" 2>/dev/null || true
    fi
  fi
}

# 系统依赖（fontconfig / wqy 字体 / noto emoji）与 Chromium 已在构建阶段装进镜像
# （Dockerfile 的 apt bundle 与 `playwright install chromium`），运行时安装属于可选的
# 覆盖手段：镜像以非 root（appuser/uid 10001）运行，apt 需要 root，默认开启必然失败。
# 因此默认关闭；确需在启动期补装时显式传 AUTO_INSTALL_*_ON_START=true 并以 root 运行。
#
# `--read-only` 容器（022 T029 硬化基线）无法在启动时改写 /etc 或安装系统包。
# 探测根挂载点是否为 ro：与「权限不足」区分开——前者应跳过，后者仍按
# REQUIRE_RUNTIME_PREPARE_SUCCESS 的约定硬失败。
rootfs_is_read_only() {
  local opts
  opts="$(awk '$2 == "/" { print $4; exit }' /proc/mounts 2>/dev/null || true)"
  [[ ",${opts}," == *,ro,* ]]
}

prepare_apt_mirror() {
  if [[ -f /etc/apt/sources.list ]]; then
    sed -i 's|http://deb.debian.org/debian|https://mirrors.aliyun.com/debian|g; s|http://security.debian.org/debian-security|https://mirrors.aliyun.com/debian-security|g' /etc/apt/sources.list || true
  fi
  if [[ -f /etc/apt/sources.list.d/debian.sources ]]; then
    sed -i 's|http://deb.debian.org/debian|https://mirrors.aliyun.com/debian|g; s|http://security.debian.org/debian-security|https://mirrors.aliyun.com/debian-security|g' /etc/apt/sources.list.d/debian.sources || true
  fi
  unset XZ_DEFAULTS XZ_OPT || true
  rm -f /etc/apt/apt.conf.d/docker-clean || true
}

install_system_deps_on_start() {
  if rootfs_is_read_only; then
    echo "[entrypoint] Skip system deps install (read-only root filesystem)"
    return 0
  fi

  if [[ "${AUTO_INSTALL_SYSTEM_DEPS_ON_START:-false}" != "true" ]]; then
    echo "[entrypoint] Skip system deps install (AUTO_INSTALL_SYSTEM_DEPS_ON_START != true)"
    return 0
  fi

  if command -v fc-list >/dev/null 2>&1 && fc-list | grep -qiE "WenQuanYi|Noto Color Emoji"; then
    echo "[entrypoint] Fonts already present"
  fi

  if command -v curl >/dev/null 2>&1 && command -v wget >/dev/null 2>&1 && command -v unzip >/dev/null 2>&1; then
    echo "[entrypoint] Base system tools already present"
  fi

  echo "[entrypoint] Installing system dependencies at container startup..."
  prepare_apt_mirror

  apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update
  apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    wget \
    unzip \
    fontconfig \
    fonts-wqy-zenhei \
    fonts-noto-color-emoji
  rm -rf /var/lib/apt/lists/*

  echo "[entrypoint] System dependencies installed"
}

install_playwright_on_start() {
  if rootfs_is_read_only; then
    echo "[entrypoint] Skip playwright install (read-only root filesystem)"
    return 0
  fi

  if [[ "${AUTO_INSTALL_PLAYWRIGHT_ON_START:-false}" != "true" ]]; then
    echo "[entrypoint] Skip playwright install (AUTO_INSTALL_PLAYWRIGHT_ON_START != true)"
    return 0
  fi

  echo "[entrypoint] Installing Playwright Chromium at container startup..."
  if [[ "${PLAYWRIGHT_INSTALL_WITH_DEPS_ON_START:-true}" = "true" ]]; then
    playwright install --with-deps chromium
  else
    playwright install chromium
  fi
  echo "[entrypoint] Playwright Chromium installed"
}

main() {
  load_runtime_secrets
  if [[ "${REQUIRE_RUNTIME_PREPARE_SUCCESS:-true}" = "true" ]]; then
    install_system_deps_on_start
    install_playwright_on_start
  else
    install_system_deps_on_start || echo "[entrypoint] WARNING: system deps install failed"
    install_playwright_on_start || echo "[entrypoint] WARNING: playwright install failed"
  fi

  exec "$@"
}

main "$@"
