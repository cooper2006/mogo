FROM node:24-bookworm-slim AS build

WORKDIR /app

ARG VITE_BASE_PATH=/admin/
ARG VITE_ADMIN_API_BASE_URL=/admin-api
ARG MOGO_NPM_REGISTRY=https://registry.npmmirror.com
# Same pin as .github/workflows/quality-gate.yml (frontend-quality). The
# lockfile is a pnpm lockfile, so the image must use the project's pnpm, not npm.
ARG PNPM_VERSION=12.14.0
ENV VITE_BASE_PATH=${VITE_BASE_PATH} \
    VITE_ADMIN_API_BASE_URL=${VITE_ADMIN_API_BASE_URL} \
    MOGO_NPM_REGISTRY=${MOGO_NPM_REGISTRY}

COPY package.json pnpm*.yaml* ./

# The official Node image ships npm plus a dormant corepack — `pnpm` is NOT on
# PATH, so it has to be installed explicitly or the build dies at
# `pnpm: not found` (exit 127).
#
# pnpm's store is a BuildKit cache mount rather than a layer: it survives a
# change to package.json (which invalidates this layer) so a rebuild reuses the
# tarballs instead of re-downloading them. This dependency tree measured ~7
# minutes against npmmirror.
# Offline pnpm bundle (see scripts/pnpm_store_bundle.sh): carries BOTH the
# content-addressable store (project tarballs) and the pnpm native CLI per
# TARGETARCH. pnpm >=11 is a platform-specific @pnpm/exe binary, so a
# store-only bundle would still need `npm install -g pnpm` (722s under QEMU).
# A missing/placeholder bundle, or an incomplete store, falls back online.
# pnpm >=12 verifies the lockfile against supply-chain policies and needs
# registry metadata for it; --offline cannot fetch that
# (ERR_PNPM_NO_OFFLINE_META), so offline installs pass --trust-lockfile. The
# lockfile is committed and reviewed, and the online fallback keeps pnpm's
# default verification.
ARG PNPM_OFFLINE_INSTALL=true
ARG TARGETARCH
RUN --mount=type=cache,target=/pnpm-store,sharing=locked \
    --mount=type=bind,source=pnpm-store-bundle.tar.gz,target=/tmp/pnpm-store-bundle.tar.gz \
    set -eux; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    case "${arch}" in x86_64) arch=amd64;; aarch64) arch=arm64;; esac; \
    offline=""; cli_restored=""; \
    if [ "${PNPM_OFFLINE_INSTALL}" = "true" ] \
       && [ "$(du -sb /tmp/pnpm-store-bundle.tar.gz | cut -f1)" -gt 1024 ]; then \
        rm -rf /tmp/pnpm-offline; mkdir -p /tmp/pnpm-offline /pnpm-store; \
        tar -xzf /tmp/pnpm-store-bundle.tar.gz -C /tmp/pnpm-offline; \
        if [ -d /tmp/pnpm-offline/store ]; then \
            cp -a /tmp/pnpm-offline/store/. /pnpm-store/; \
            offline="--offline"; \
            echo "Using offline pnpm store from bundle (${arch})"; \
            if [ -s "/tmp/pnpm-offline/pnpm-cli/${arch}/pnpm" ]; then \
                install -m 0755 "/tmp/pnpm-offline/pnpm-cli/${arch}/pnpm" /usr/local/bin/pnpm; \
                echo "pnpm CLI restored from offline bundle (${arch})"; \
                cli_restored="yes"; \
            fi; \
        fi; \
    fi; \
    if [ -z "${cli_restored}" ]; then \
        npm install --global "pnpm@${PNPM_VERSION}" --registry="${MOGO_NPM_REGISTRY:-https://registry.npmmirror.com}"; \
    fi; \
    pnpm config set store-dir /pnpm-store; \
    pnpm config set registry "${MOGO_NPM_REGISTRY:-https://registry.npmmirror.com}"; \
    trust=""; if [ -n "${offline}" ]; then trust="--trust-lockfile"; fi; \
    if ! pnpm install ${offline} --frozen-lockfile ${trust}; then \
        if [ -n "${offline}" ]; then \
            echo "Offline install incomplete; retrying against the registry"; \
            pnpm install --frozen-lockfile; \
        else \
            exit 1; \
        fi; \
    fi

COPY . .
# `build` is plain `vite build`; type checking lives in the separate
# `typecheck` script, which CI runs (quality-gate.yml). Keeping it out of the
# image build avoids ~12 minutes of vue-tsc per build for a check that has
# already passed.
# Cross-arch linux/amd64 builds on Apple Silicon run through QEMU, where
# esbuild's Go runtime dies in runtime/lfstack.go with
# `fatal error: lfstack.push` (a tagged pointer is sign-extended incorrectly
# by binfmt). GOMAXPROCS=1 / GODEBUG=asyncpreemptoff=1 were measured NOT to
# fix it. The reliable path is to build `dist` natively on the host and let
# the image just COPY it -- dist is plain HTML/JS/CSS, architecture-neutral.
# Opt in with MOGO_PREBUILT_DIST=true (see docs/offline-bundle-system.md).
# The default keeps the normal in-container `vite build` unchanged.
ARG MOGO_PREBUILT_DIST=false
RUN if [ "${MOGO_PREBUILT_DIST}" = "true" ]; then \
        test -f /app/dist/index.html || { echo "MOGO_PREBUILT_DIST=true but /app/dist/index.html is missing" >&2; exit 1; }; \
        echo "Using host-built dist (native build, no vite/esbuild under QEMU)"; \
    else \
        rm -rf /app/dist; \
        pnpm run build; \
    fi

FROM nginx:1.31.5-alpine3.24-slim

# Opt-in: only apply Alpine security patches when MOGO_SECURITY_REFRESH is set
# (CI passes its run id). Skipping keeps this layer cacheable locally.
ARG MOGO_SECURITY_REFRESH=
RUN if [ -n "${MOGO_SECURITY_REFRESH}" ] && [ "${MOGO_SECURITY_REFRESH}" != "false" ]; then \
        apk upgrade --no-cache; \
    else \
        echo "Skip apk upgrade (set MOGO_SECURITY_REFRESH to apply security patches)"; \
    fi

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
# Non-root master: the stock main config runs `user nginx;` and writes its pid
# file to /var/run, both of which need root. Use the trimmed variant instead.
COPY nginx-main.conf /etc/nginx/nginx.conf
# Normalise config modes in-container so they do not depend on host umask or
# editor defaults (the same pattern the Python images use on /app). Without
# this a 0600 nginx-main.conf makes the non-root master unable to read its own
# config and nginx refuses to start.
RUN chmod 0644 /etc/nginx/nginx.conf /etc/nginx/conf.d/default.conf

# ── Non-root runtime (022 FR-26 / T026) ───────────────────────────────────
# nginx runs as appuser (UID 10001) so a compromised worker cannot land with
# root in the host namespace. Binding port 80 still needs the NET_BIND_SERVICE
# capability, which the Compose file grants explicitly (see `cap_add` on
# admin-web) rather than granting root.
#
# Logs and temp dirs stay on their stock paths; chowning them to appuser is
# what lets the non-root master write them without root.
#
# Alpine/BusyBox ships `addgroup`/`adduser` instead of Debian's `groupadd`/
# `-u` flag order differs, so the flags are spelled out explicitly.
RUN addgroup -g 10001 -S appuser \
    && adduser -S -H -D -G appuser -g "" -h /home/appuser -s /sbin/nologin -u 10001 appuser \
    && chown -R appuser:appuser /var/log/nginx /var/cache/nginx /usr/share/nginx/html \
    && chmod -R a+rX /usr/share/nginx/html

USER appuser

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
