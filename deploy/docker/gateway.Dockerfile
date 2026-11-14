FROM nginx:1.31.5-alpine3.24-slim

# Point apk at a domestic mirror before any package operation:
# dl-cdn.alpinelinux.org is slow or unreachable from CN networks, and
# rewriting the repositories is harmless when the upgrade below is skipped.
ARG MOGO_APK_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/alpine
RUN if [ -n "${MOGO_APK_MIRROR}" ]; then \
        for source_file in /etc/apk/repositories /etc/apk/repositories.d/*.repositories; do \
            if [ -f "${source_file}" ]; then \
                sed -i "s|https\?://dl-cdn.alpinelinux.org/alpine|${MOGO_APK_MIRROR}|g" "${source_file}"; \
            fi; \
        done; \
    fi

# Opt-in: only apply Alpine security patches when MOGO_SECURITY_REFRESH is set
# (CI passes its run id). Skipping keeps this layer cacheable locally.
ARG MOGO_SECURITY_REFRESH=
RUN if [ -n "${MOGO_SECURITY_REFRESH}" ] && [ "${MOGO_SECURITY_REFRESH}" != "false" ]; then \
        apk upgrade --no-cache; \
    else \
        echo "Skip apk upgrade (set MOGO_SECURITY_REFRESH to apply security patches)"; \
    fi

# Non-root master: the stock main config runs `user nginx;` and writes its pid
# file to /var/run, both of which need root — and root + `cap_drop: ALL`
# (see the gateway service in docker-compose.yml) cannot even `chown` its own
# cache directories, so nginx would crash-loop. Use the trimmed variant.
COPY nginx-main.conf /etc/nginx/nginx.conf
# Normalise the mode in-container so it does not depend on host umask or editor
# defaults: a 0600 main config makes the non-root master unable to read its own
# config and nginx refuses to start.
RUN chmod 0644 /etc/nginx/nginx.conf

# ── Non-root runtime (022 FR-26 / T026) ───────────────────────────────────
# nginx runs as appuser (UID 10001) so a compromised worker cannot land with
# root in the host namespace. Binding the low ports still needs
# NET_BIND_SERVICE, which the Compose file grants explicitly (see `cap_add` on
# gateway) rather than granting root.
#
# /var/cache/nginx and /var/log/nginx stay on their stock paths; chowning them
# to appuser is what lets the non-root master write them without root. Compose
# also mounts both as tmpfs because the container rootfs is read-only.
#
# Alpine/BusyBox ships `addgroup`/`adduser` instead of Debian's
# `groupadd`/`useradd`, so the flags are spelled out explicitly.
RUN addgroup -g 10001 -S appuser \
    && adduser -S -H -D -G appuser -g "" -h /home/appuser -s /sbin/nologin -u 10001 appuser \
    && chown -R appuser:appuser /var/log/nginx /var/cache/nginx

USER appuser

EXPOSE 80
EXPOSE 443

