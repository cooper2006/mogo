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

ARG MOVO_APT_MIRROR=http://mirrors.tuna.tsinghua.edu.cn/debian
ARG MOVO_APT_SECURITY_MIRROR=http://mirrors.tuna.tsinghua.edu.cn/debian-security
# Point apt at a reachable mirror before any apt-get call so both the system
# dependency stage and playwright --with-deps pick it up.
RUN if [ -n "${MOVO_APT_MIRROR}" ]; then \
        for source_file in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources; do \
            if [ -f "${source_file}" ]; then \
                sed -i "s|http://deb.debian.org/debian|${MOVO_APT_MIRROR}|g; s|https://deb.debian.org/debian|${MOVO_APT_MIRROR}|g" "${source_file}"; \
                if [ -n "${MOVO_APT_SECURITY_MIRROR}" ]; then \
                    sed -i "s|http://deb.debian.org/debian-security|${MOVO_APT_SECURITY_MIRROR}|g; s|https://deb.debian.org/debian-security|${MOVO_APT_SECURITY_MIRROR}|g; s|http://security.debian.org/debian-security|${MOVO_APT_SECURITY_MIRROR}|g; s|https://security.debian.org/debian-security|${MOVO_APT_SECURITY_MIRROR}|g" "${source_file}"; \
                fi; \
            fi; \
        done; \
    fi

ARG INSTALL_SYSTEM_DEPS_AT_BUILD=false
RUN if [ "${INSTALL_SYSTEM_DEPS_AT_BUILD}" = "true" ]; then \
        unset XZ_DEFAULTS XZ_OPT \
        && rm -f /etc/apt/apt.conf.d/docker-clean \
        && apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update \
        && apt-get install -y --no-install-recommends \
            ca-certificates \
            curl \
            wget \
            unzip \
            fontconfig \
            fonts-wqy-zenhei \
            fonts-noto-color-emoji \
        && rm -rf /var/lib/apt/lists/*; \
    else \
        echo "Skip apt system dependencies in build stage (INSTALL_SYSTEM_DEPS_AT_BUILD=false)"; \
    fi

COPY requirements.txt /tmp/requirements.txt

RUN python -m pip install --progress-bar off --upgrade pip setuptools wheel \
    && python -m pip install --progress-bar off --require-hashes -r /tmp/requirements.txt \
    && python -m pip uninstall --yes pip wheel \
    && find /usr/local/lib/python3.13/ensurepip/_bundled -type f -delete

# Chromium for the browser tool.
#
# Three paths, in order of preference:
#   1. offline bundle (playwright-browsers-bundle.tar.gz in the build context,
#      produced by scripts/playwright_browsers_bundle.sh save) — no network,
#      deterministic bytes, and the layer stays cached while the bundle is
#      unchanged. Tracked in git as a <1KB placeholder, so this COPY never fails.
#   2. online download from PLAYWRIGHT_DOWNLOAD_HOST (npmmirror).
#   3. skip entirely (INSTALL_PLAYWRIGHT_AT_BUILD=false).
#
# System libraries are a separate concern: `--with-deps` shells out to apt,
# which fails whenever a distro mirror hiccups and would otherwise take the
# whole browser step down with it. So deps are installed on their own and a
# failure there is a warning, not a build failure — the bundle path above is
# what makes browser provisioning reproducible.
ARG INSTALL_PLAYWRIGHT_AT_BUILD=false
ARG PLAYWRIGHT_WITH_DEPS=false
COPY playwright-browsers-bundle.tar.gz /tmp/playwright-browsers-bundle.tar.gz
RUN if [ "${INSTALL_PLAYWRIGHT_AT_BUILD}" != "true" ]; then \
        echo "Skip playwright browser install in build stage (INSTALL_PLAYWRIGHT_AT_BUILD=false)"; \
    else \
        bundle_bytes="$(du -sb /tmp/playwright-browsers-bundle.tar.gz | cut -f1)"; \
        if [ "${bundle_bytes}" -gt 1024 ]; then \
            echo "Installing playwright browsers from offline bundle (${bundle_bytes} bytes)"; \
            mkdir -p "${PLAYWRIGHT_BROWSERS_PATH}" \
            && tar -xzf /tmp/playwright-browsers-bundle.tar.gz -C "${PLAYWRIGHT_BROWSERS_PATH}" \
            && rm -f /tmp/playwright-browsers-bundle.tar.gz; \
        else \
            echo "No offline browser bundle; downloading from ${PLAYWRIGHT_DOWNLOAD_HOST}"; \
            if [ "${PLAYWRIGHT_WITH_DEPS}" = "true" ]; then \
                PLAYWRIGHT_SKIP_BROWSER_GC=1 playwright install chromium \
                && (playwright install-deps chromium \
                    || echo "WARNING: playwright install-deps failed (apt mirror unreachable); continuing with browsers only"); \
            else \
                PLAYWRIGHT_SKIP_BROWSER_GC=1 playwright install chromium; \
            fi; \
        fi; \
        if [ "${PLAYWRIGHT_WITH_DEPS}" = "true" ] && [ "${bundle_bytes}" -gt 1024 ]; then \
            playwright install-deps chromium \
            || echo "WARNING: playwright install-deps failed (apt mirror unreachable); continuing with browsers only"; \
        fi; \
        rm -f /tmp/playwright-browsers-bundle.tar.gz; \
        ls -d "${PLAYWRIGHT_BROWSERS_PATH}"/chromium*-* >/dev/null 2>&1 \
            || { echo "ERROR: no chromium directory under ${PLAYWRIGHT_BROWSERS_PATH} after provisioning"; exit 1; }; \
        echo "chromium provisioned: $(ls -d "${PLAYWRIGHT_BROWSERS_PATH}"/chromium*-* | tr '\n' ' ')"; \
        if python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(); b.close(); p.stop()" 2>/dev/null; then \
            echo "playwright chromium launch OK"; \
        else \
            echo "WARNING: chromium is installed but failed to launch (missing system libraries are the usual cause; install them or build with PLAYWRIGHT_WITH_DEPS=true)"; \
        fi; \
    fi

# Security refresh is opt-in. A non-empty value (CI passes its run id) applies
# the latest distro security patches; an empty or "false" value skips the
# upgrade, which keeps this layer cacheable so a local rebuild does not
# re-download every package.
ARG MOVO_SECURITY_REFRESH=
RUN if [ -n "${MOVO_SECURITY_REFRESH}" ] && [ "${MOVO_SECURITY_REFRESH}" != "false" ]; then \
        apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update \
        && apt-get upgrade -y \
        && rm -rf /var/lib/apt/lists/*; \
    else \
        echo "Skip apt upgrade (set MOVO_SECURITY_REFRESH to apply security patches)"; \
    fi

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

COPY app /app/app
COPY .env.example /app/.env.example
# Ensure in-container permissions do not depend on host file modes, so the
# COPY layer stays cacheable across host permission churn.
RUN chmod -R a+rX /app

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
