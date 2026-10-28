# Base image by name, not digest: the digest form forces a registry manifest
# lookup even when the image is already present locally, which fails outright
# on an air-gapped or registry-restricted host. Pin by tag and let the local
# image win; override BASE_IMAGE to pin a digest when reproducible pulls matter.
ARG BASE_IMAGE=python:3.13-slim-bookworm
FROM ${BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_PROGRESS_BAR=off \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright

WORKDIR /app

ARG MOGO_APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG MOGO_APT_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security
# Point apt at a reachable mirror before any apt-get call so both the system
# dependency stage and playwright --with-deps pick it up.
RUN if [ -n "${MOGO_APT_MIRROR}" ]; then \
        for source_file in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources; do \
            if [ -f "${source_file}" ]; then \
                sed -i "s|http://deb.debian.org/debian|${MOGO_APT_MIRROR}|g; s|https://deb.debian.org/debian|${MOGO_APT_MIRROR}|g" "${source_file}"; \
                if [ -n "${MOGO_APT_SECURITY_MIRROR}" ]; then \
                    sed -i "s|http://deb.debian.org/debian-security|${MOGO_APT_SECURITY_MIRROR}|g; s|https://deb.debian.org/debian-security|${MOGO_APT_SECURITY_MIRROR}|g; s|http://security.debian.org/debian-security|${MOGO_APT_SECURITY_MIRROR}|g; s|https://security.debian.org/debian-security|${MOGO_APT_SECURITY_MIRROR}|g" "${source_file}"; \
                fi; \
            fi; \
        done; \
    fi

# Offline apt package bundle (see scripts/apt_packages_bundle.sh).
#
# The apt mirror serves .deb at ~555-895 kB/s here, far below the same mirror's
# PyPI endpoint, so a rebuild re-downloading these is pure waste. The bundle
# carries the .deb files plus the apt index, because `--no-download` still needs
# the index to map names to versions.
#
# Same contract as the docling / playwright / pip bundles: git ships a <1KB
# empty-tar placeholder (tracked via git add -f) so the mount always resolves,
# and `save` overwrites it in place. The RUN sizes it to decide offline vs
# network.
#
# Mounted rather than COPYed: a COPY layer keeps the whole tar in the image
# permanently, since removing it later only adds a whiteout. The mount is
# read-only, exists only for this RUN, and BuildKit still folds the file's
# digest into the cache key, so an unchanged bundle hits cache as before.
ARG APT_OFFLINE_INSTALL=true
ARG INSTALL_SYSTEM_DEPS_AT_BUILD=false
# Declared here as well as in the later playwright stage: this RUN block reads
# it to decide whether to install the chromium system libraries, and without a
# declaration in this stage `set -u` aborts the build with
# "INSTALL_PLAYWRIGHT_AT_BUILD: parameter not set".
ARG INSTALL_PLAYWRIGHT_AT_BUILD=false
RUN --mount=type=bind,source=apt-packages-bundle.tar.gz,target=/tmp/apt-packages-bundle.tar.gz \
    set -eux; \
    if [ "${INSTALL_SYSTEM_DEPS_AT_BUILD}" != "true" ]; then \
        echo "Skip apt system dependencies in build stage (INSTALL_SYSTEM_DEPS_AT_BUILD=false)"; \
        exit 0; \
    fi; \
    unset XZ_DEFAULTS XZ_OPT; \
    rm -f /etc/apt/apt.conf.d/docker-clean; \
    apt_arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    offline=false; \
    if [ "${APT_OFFLINE_INSTALL}" = "true" ] \
        && [ "$(du -sb /tmp/apt-packages-bundle.tar.gz | cut -f1)" -gt 1024 ]; then \
        mkdir -p /tmp/apt-offline \
        && { tar -xzf /tmp/apt-packages-bundle.tar.gz -C /tmp/apt-offline "./${apt_arch}" 2>/dev/null || true; } \
        && if [ -d "/tmp/apt-offline/${apt_arch}" ]; then \
               offline=true; \
               echo "Installing apt packages offline for ${apt_arch} ($(find /tmp/apt-offline/${apt_arch} -name '*.deb' | wc -l) deb files)"; \
               cp /tmp/apt-offline/${apt_arch}/*.deb /var/cache/apt/archives/ 2>/dev/null || true; \
               if [ -d "/tmp/apt-offline/${apt_arch}/Packages" ]; then \
                   cp /tmp/apt-offline/${apt_arch}/Packages/* /var/lib/apt/lists/ 2>/dev/null || true; \
               fi; \
           else \
               echo "Bundle has no ${apt_arch}/ directory; falling back to the network."; \
           fi; \
    else \
        echo "Skip offline apt bundle (placeholder or APT_OFFLINE_INSTALL=false); using the network."; \
    fi; \
    if [ "${offline}" != "true" ]; then \
        apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update; \
    fi; \
    apt_install() { \
        if [ "${offline}" = "true" ]; then \
            apt-get install -y --no-install-recommends --no-download "$@"; \
        else \
            apt-get install -y --no-install-recommends "$@"; \
        fi; \
    }; \
    apt_install \
        ca-certificates \
        curl \
        wget \
        unzip \
        fontconfig \
        fonts-wqy-zenhei \
        fonts-noto-color-emoji; \
    if [ "${INSTALL_PLAYWRIGHT_AT_BUILD}" = "true" ]; then \
        echo "Installing chromium system libraries (playwright install-deps set) from the apt bundle"; \
        apt_install \
            libasound2 \
            libatk-bridge2.0-0 \
            libatk1.0-0 \
            libatspi2.0-0 \
            libcairo2 \
            libcups2 \
            libdbus-1-3 \
            libdrm2 \
            libgbm1 \
            libglib2.0-0 \
            libnspr4 \
            libnss3 \
            libpango-1.0-0 \
            libx11-6 \
            libxcb1 \
            libxcomposite1 \
            libxdamage1 \
            libxext6 \
            libxfixes3 \
            libxkbcommon0 \
            libxrandr2 \
            xvfb \
            fonts-unifont \
            libfontconfig1 \
            libfreetype6 \
            xfonts-scalable \
            fonts-liberation \
            fonts-ipafont-gothic \
            fonts-tlwg-loma-otf \
            fonts-freefont-ttf; \
    fi; \
    rm -rf /var/lib/apt/lists/* /tmp/apt-offline

COPY requirements.txt /tmp/requirements.txt

# Offline pip wheel bundle (see scripts/pip_wheels_bundle.sh).
#
# The mirror serves PyPI at 13-18 MB/s, so this is not about bandwidth but about
# repetition: without a cache every rebuild re-downloads the whole 114-package
# closure. Measured on this image: 502s. Same contract as the other bundles
# (git ships a <1KB empty-tar placeholder so the mount always resolves; `save`
# overwrites it in place) — the RUN sizes it to decide offline vs network.
#
# Mounted rather than COPYed so the ~300MB tar does not stay in a layer.
ARG TARGETARCH
ARG PIP_OFFLINE_INSTALL=true
RUN --mount=type=bind,source=pip-wheels-bundle.tar.gz,target=/tmp/pip-wheels-bundle.tar.gz \
    set -eux; \
    wheel_arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    offline=false; \
    if [ "${PIP_OFFLINE_INSTALL}" = "true" ] \
        && [ "$(du -sb /tmp/pip-wheels-bundle.tar.gz | cut -f1)" -gt 1024 ]; then \
        mkdir -p /tmp/pip-wheels \
        && { tar -xzf /tmp/pip-wheels-bundle.tar.gz -C /tmp/pip-wheels "./${wheel_arch}" 2>/dev/null || true; } \
        && if [ -d "/tmp/pip-wheels/${wheel_arch}" ]; then \
               offline=true; \
               echo "Installing pip wheels offline for ${wheel_arch} ($(find /tmp/pip-wheels/${wheel_arch} -name '*.whl' | wc -l) wheels)"; \
           else \
               echo "Bundle has no ${wheel_arch}/ directory; falling back to the network."; \
           fi; \
    else \
        echo "Skip offline wheel bundle (placeholder or PIP_OFFLINE_INSTALL=false); using the network."; \
    fi; \
    offline_args=""; \
    if [ "${offline}" = "true" ]; then \
        offline_args="--no-index --find-links=/tmp/pip-wheels/${wheel_arch}"; \
    fi; \
    python -m pip install --progress-bar off ${offline_args} --upgrade pip setuptools wheel \
    && python -m pip install --progress-bar off ${offline_args} --require-hashes -r /tmp/requirements.txt \
    && python -m pip uninstall --yes pip wheel \
    && find /usr/local/lib/python3.13/ensurepip/_bundled -type f -delete \
    && rm -rf /tmp/pip-wheels

# Chromium for the browser tool.
#
# Three paths, in order of preference:
#   1. offline bundle (playwright-browsers-bundle.tar.gz in the build context,
#      produced by scripts/playwright_browsers_bundle.sh save) — no network,
#      deterministic bytes, and the layer stays cached while the bundle is
#      unchanged. Tracked in git as a <1KB placeholder, so this mount always
#      resolves.
#   2. online download from PLAYWRIGHT_DOWNLOAD_HOST (npmmirror).
#   3. skip entirely (INSTALL_PLAYWRIGHT_AT_BUILD=false).
#
# System libraries are a separate concern: `--with-deps` shells out to apt,
# which fails whenever a distro mirror hiccups and would otherwise take the
# whole browser step down with it. So deps are installed on their own and a
# failure there is a warning, not a build failure — the bundle path above is
# what makes browser provisioning reproducible.
ARG TARGETARCH
ARG INSTALL_PLAYWRIGHT_AT_BUILD=false
ARG PLAYWRIGHT_WITH_DEPS=false
RUN --mount=type=bind,source=playwright-browsers-bundle.tar.gz,target=/tmp/playwright-browsers-bundle.tar.gz \
    if [ "${INSTALL_PLAYWRIGHT_AT_BUILD}" != "true" ]; then \
        echo "Skip playwright browser install in build stage (INSTALL_PLAYWRIGHT_AT_BUILD=false)"; \
    else \
        bundle_bytes="$(du -sb /tmp/playwright-browsers-bundle.tar.gz | cut -f1)"; \
        pw_arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
        mkdir -p "${PLAYWRIGHT_BROWSERS_PATH}"; \
        # The bundle holds one top-level <arch>/ tree per architecture (same
        # contract as the pip and apt bundles), so only this build's tree is
        # extracted. Extraction goes through a scratch dir instead of
        # `--strip-components`: stripping the <arch>/ prefix is the one tar
        # option whose behaviour differs between tar implementations, and a
        # silent no-op would leave the browsers at /ms-playwright/<arch>/ --
        # where playwright never looks. Scratch dir is created and removed in
        # this same RUN, so it leaves no layer behind. A bundle without this
        # arch is not an error: the network path below covers it.
        if [ "${bundle_bytes}" -gt 1024 ]; then \
            echo "Installing playwright browsers for ${pw_arch} from the offline bundle (${bundle_bytes} bytes)"; \
            pw_tmp="$(mktemp -d)"; \
            tar -xzf /tmp/playwright-browsers-bundle.tar.gz -C "${pw_tmp}" "./${pw_arch}" 2>/dev/null || true; \
            if [ -d "${pw_tmp}/${pw_arch}" ]; then \
                cp -R "${pw_tmp}/${pw_arch}/." "${PLAYWRIGHT_BROWSERS_PATH}/"; \
            fi; \
            rm -rf "${pw_tmp}"; \
        fi; \
        if ls -d "${PLAYWRIGHT_BROWSERS_PATH}"/chromium*-* >/dev/null 2>&1; then \
            echo "Browsers installed from the offline bundle"; \
        else \
            echo "Bundle has no ${pw_arch}/ tree (or no bundle); downloading from ${PLAYWRIGHT_DOWNLOAD_HOST}"; \
            if [ "${PLAYWRIGHT_WITH_DEPS}" = "true" ]; then \
                PLAYWRIGHT_SKIP_BROWSER_GC=1 playwright install chromium \
                && (playwright install-deps chromium \
                    || echo "WARNING: playwright install-deps failed (apt mirror unreachable); continuing with browsers only"); \
            else \
                PLAYWRIGHT_SKIP_BROWSER_GC=1 playwright install chromium; \
            fi; \
        fi; \
        # `playwright install-deps chromium` installs ~32 system packages
        # unconditionally, even when the browser came from the offline bundle:
        # measured at ~11 minutes against a slow apt mirror, on every rebuild.
        # Those same packages are already in the apt bundle and were installed
        # by the apt step above (scripts/apt_packages_bundle.sh discovers them
        # from playwright's own install-deps declaration), so re-running it is
        # pure waste. Skipped only when that step actually ran.
        if [ "${PLAYWRIGHT_WITH_DEPS}" = "true" ]; then \
            if [ "${INSTALL_SYSTEM_DEPS_AT_BUILD}" = "true" ]; then \
                echo "Skipping 'playwright install-deps': the apt bundle step already installed chromium's system libraries from the local .deb set."; \
            else \
                playwright install-deps chromium \
                || echo "WARNING: playwright install-deps failed (apt mirror unreachable); continuing with browsers only"; \
            fi; \
        fi; \
        ls -d "${PLAYWRIGHT_BROWSERS_PATH}"/chromium*-* >/dev/null 2>&1 \
            || { echo "ERROR: no chromium directory under ${PLAYWRIGHT_BROWSERS_PATH} after provisioning"; exit 1; }; \
        echo "chromium provisioned: $(ls -d "${PLAYWRIGHT_BROWSERS_PATH}"/chromium*-* | tr '\n' ' ')"; \
        if python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(); b.close(); p.stop()" 2>/dev/null; then \
            echo "playwright chromium launch OK"; \
        else \
            echo "ERROR: chromium is installed but does not launch." >&2; \
            echo "  Usual causes, in order of likelihood:" >&2; \
            echo "    1. bundle is for another architecture (an arm64 chromium in an amd64 image" >&2; \
            echo "       fails exec with ENOENT, and the files still look 'executable')" >&2; \
            echo "    2. missing shared libraries (build with PLAYWRIGHT_WITH_DEPS=true)" >&2; \
            echo "  Diagnose with: file \$(ls -d ${PLAYWRIGHT_BROWSERS_PATH}/chromium*-*/chrome-linux/headless_shell | head -1)" >&2; \
            echo "  Regenerate the bundle for this architecture:" >&2; \
            echo "    ARCH=<arm64|amd64> scripts/playwright_browsers_bundle.sh save" >&2; \
            exit 1; \
        fi; \
    fi

# Security refresh is opt-in. A non-empty value (CI passes its run id) applies
# the latest distro security patches; an empty or "false" value skips the
# upgrade, which keeps this layer cacheable so a local rebuild does not
# re-download every package.
ARG MOGO_SECURITY_REFRESH=
RUN if [ -n "${MOGO_SECURITY_REFRESH}" ] && [ "${MOGO_SECURITY_REFRESH}" != "false" ]; then \
        apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update \
        && apt-get upgrade -y \
        && rm -rf /var/lib/apt/lists/*; \
    else \
        echo "Skip apt upgrade (set MOGO_SECURITY_REFRESH to apply security patches)"; \
    fi

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

COPY app /app/app
COPY .env.example /app/.env.example
# Ensure in-container permissions do not depend on host file modes, so the
# COPY layer stays cacheable across host permission churn.
RUN chmod -R a+rX /app

# ── Non-root runtime (022 FR-26 / T024) ──────────────────────────────────
# App containers run as an unprivileged user so a container escape cannot land
# with root in the host namespace, and a compromised process cannot overwrite
# its own binary layer. UID/GID 10001 is the repo-wide convention.
#
# Writable paths are created *here* on purpose: when Compose mounts a named
# volume over them, Docker seeds the volume from this image directory, so the
# volume inherits appuser ownership. Skip this and the volume is root-owned
# and the service dies on its first write.
RUN groupadd --gid 10001 --system appuser \
    && useradd --uid 10001 --gid appuser --home-dir /home/appuser \
        --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/storage /data/knowledge-documents /ms-playwright \
    && chown -R appuser:appuser /app/storage /data/knowledge-documents /ms-playwright /app /home/appuser \
    && chmod -R a+rX /app

USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
