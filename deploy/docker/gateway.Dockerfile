FROM nginx:1.31.5-alpine3.24-slim

# Point apk at a domestic mirror before any package operation:
# dl-cdn.alpinelinux.org is slow or unreachable from CN networks, and
# rewriting the repositories is harmless when the upgrade below is skipped.
ARG MOVO_APK_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/alpine
RUN if [ -n "${MOVO_APK_MIRROR}" ]; then \
        for source_file in /etc/apk/repositories /etc/apk/repositories.d/*.repositories; do \
            if [ -f "${source_file}" ]; then \
                sed -i "s|https\?://dl-cdn.alpinelinux.org/alpine|${MOVO_APK_MIRROR}|g" "${source_file}"; \
            fi; \
        done; \
    fi

# Opt-in: only apply Alpine security patches when MOVO_SECURITY_REFRESH is set
# (CI passes its run id). Skipping keeps this layer cacheable locally.
ARG MOVO_SECURITY_REFRESH=
RUN if [ -n "${MOVO_SECURITY_REFRESH}" ] && [ "${MOVO_SECURITY_REFRESH}" != "false" ]; then \
        apk upgrade --no-cache; \
    else \
        echo "Skip apk upgrade (set MOVO_SECURITY_REFRESH to apply security patches)"; \
    fi
