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
RUN --mount=type=cache,target=/pnpm-store,sharing=locked \
    npm install --global "pnpm@${PNPM_VERSION}" --registry="${MOGO_NPM_REGISTRY:-https://registry.npmmirror.com}" \
    && pnpm config set store-dir /pnpm-store \
    && pnpm config set registry "${MOGO_NPM_REGISTRY:-https://registry.npmmirror.com}" \
    && pnpm install --frozen-lockfile

COPY . .
# `build` is plain `vite build`; type checking lives in the separate
# `typecheck` script, which CI runs (quality-gate.yml). Keeping it out of the
# image build avoids ~12 minutes of vue-tsc per build for a check that has
# already passed.
RUN pnpm run build

FROM nginx:1.31.8-alpine3.24-slim

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
