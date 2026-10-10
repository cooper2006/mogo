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
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt

# Offline pip wheel bundle (see scripts/pip_wheels_bundle.sh): same contract as
# the other bundles — git ships a <1KB empty-tar placeholder so COPY never
# fails, and `save` overwrites it in place. The RUN sizes it to decide whether
# to install from it (--no-index) or fall back to the network.
COPY pip-wheels-bundle.tar.gz /tmp/pip-wheels-bundle.tar.gz

ARG TARGETARCH
ARG PIP_OFFLINE_INSTALL=true
RUN set -eux; \
    wheel_arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    offline=false; \
    if [ "${PIP_OFFLINE_INSTALL}" = "true" ] \
        && [ "$(du -sb /tmp/pip-wheels-bundle.tar.gz | cut -f1)" -gt 1024 ]; then \
        mkdir -p /tmp/pip-wheels \
        && tar -xzf /tmp/pip-wheels-bundle.tar.gz -C /tmp/pip-wheels \
        && if [ -d "/tmp/pip-wheels/${wheel_arch}" ]; then \
               offline=true; \
               echo "Installing pip wheels offline for ${wheel_arch} ($(find /tmp/pip-wheels/${wheel_arch} -name '*.whl' | wc -l) wheels)"; \
           else \
               echo "Bundle has no ${wheel_arch}/ directory; falling back to the network."; \
           fi; \
    else \
        echo "Skip offline wheel bundle (placeholder or PIP_OFFLINE_INSTALL=false); using the network."; \
    fi; \
    rm -f /tmp/pip-wheels-bundle.tar.gz; \
    offline_args=""; \
    if [ "${offline}" = "true" ]; then \
        offline_args="--no-index --find-links=/tmp/pip-wheels/${wheel_arch}"; \
    fi; \
    python -m pip install ${offline_args} --upgrade pip setuptools wheel \
    && python -m pip install ${offline_args} --require-hashes -r /tmp/requirements.txt \
    && python -m pip uninstall --yes pip wheel \
    && find /usr/local/lib/python3.13/ensurepip/_bundled -type f -delete \
    && rm -rf /tmp/pip-wheels

# Security refresh is opt-in. A non-empty value (CI passes its run id) applies
# the latest distro security patches; an empty or "false" value skips the
# upgrade, which keeps this layer cacheable so a local rebuild does not
# re-download every package.
#
# Point apt at a domestic mirror before the update: the default deb.debian.org
# is slow or unreachable from CN networks, and the mirror is harmless when the
# refresh is skipped.
ARG MOVO_APT_MIRROR=http://mirrors.tuna.tsinghua.edu.cn/debian
ARG MOVO_APT_SECURITY_MIRROR=http://mirrors.tuna.tsinghua.edu.cn/debian-security
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

ARG MOVO_SECURITY_REFRESH=
RUN if [ -n "${MOVO_SECURITY_REFRESH}" ] && [ "${MOVO_SECURITY_REFRESH}" != "false" ]; then \
        apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update \
        && apt-get upgrade -y \
        && rm -rf /var/lib/apt/lists/*; \
    else \
        echo "Skip apt upgrade (set MOVO_SECURITY_REFRESH to apply security patches)"; \
    fi

COPY app /app/app
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod -R a+rX /app && chmod +x /app/entrypoint.sh

EXPOSE 8100

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100", "--proxy-headers"]
