ARG BASE_IMAGE=docker.m.daocloud.io/library/python:3.13-slim-bookworm
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
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --require-hashes -r /tmp/requirements.txt \
    && python -m pip uninstall --yes pip wheel \
    && find /usr/local/lib/python3.13/ensurepip/_bundled -type f -delete

# Security refresh is opt-in. A non-empty value (CI passes its run id) applies
# the latest distro security patches; an empty or "false" value skips the
# upgrade, which keeps this layer cacheable so a local rebuild does not
# re-download every package.
ARG MOVO_SECURITY_REFRESH=
RUN if [ -n "${MOVO_SECURITY_REFRESH}" ] && [ "${MOVO_SECURITY_REFRESH}" != "false" ]; then \
        apt-get update \
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
