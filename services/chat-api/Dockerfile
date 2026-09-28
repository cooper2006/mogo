FROM python:3.10-slim-bookworm

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
    && python -m pip install --progress-bar off -r /tmp/requirements.txt \
    && python -m pip uninstall --yes pip wheel \
    && find /usr/local/lib/python3.10/ensurepip/_bundled -type f -delete

ARG INSTALL_PLAYWRIGHT_AT_BUILD=false
ARG PLAYWRIGHT_WITH_DEPS=false
RUN if [ "${INSTALL_PLAYWRIGHT_AT_BUILD}" = "true" ]; then \
        if [ "${PLAYWRIGHT_WITH_DEPS}" = "true" ]; then \
            playwright install --with-deps chromium; \
        else \
            playwright install chromium; \
        fi; \
    else \
        echo "Skip playwright browser install in build stage (INSTALL_PLAYWRIGHT_AT_BUILD=false)"; \
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
