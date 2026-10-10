FROM node:24-bookworm-slim AS build

WORKDIR /app

ARG VITE_BASE_PATH=/admin/
ARG VITE_ADMIN_API_BASE_URL=/admin-api
ARG MOVO_NPM_REGISTRY=https://registry.npmmirror.com
ENV VITE_BASE_PATH=${VITE_BASE_PATH} \
    VITE_ADMIN_API_BASE_URL=${VITE_ADMIN_API_BASE_URL} \
    MOVO_NPM_REGISTRY=${MOVO_NPM_REGISTRY}

COPY package*.json ./
# npm's cache is a BuildKit cache mount rather than a layer: it survives a
# change to package.json (which invalidates this layer) so a rebuild reuses the
# tarballs instead of re-downloading them. This dependency tree measured ~7
# minutes against npmmirror.
RUN --mount=type=cache,target=/root/.npm,sharing=locked \
    npm config set registry "${MOVO_NPM_REGISTRY:-https://registry.npmmirror.com}" \
    && npm ci --legacy-peer-deps

COPY . .
# `build` is plain `vite build`; type checking lives in the separate
# `typecheck` script, which CI runs (quality-gate.yml). Keeping it out of the
# image build avoids ~12 minutes of vue-tsc per build for a check that has
# already passed.
RUN npm run build

FROM nginx:1.31.6-alpine3.24-slim

# Opt-in: only apply Alpine security patches when MOVO_SECURITY_REFRESH is set
# (CI passes its run id). Skipping keeps this layer cacheable locally.
ARG MOVO_SECURITY_REFRESH=
RUN if [ -n "${MOVO_SECURITY_REFRESH}" ] && [ "${MOVO_SECURITY_REFRESH}" != "false" ]; then \
        apk upgrade --no-cache; \
    else \
        echo "Skip apk upgrade (set MOVO_SECURITY_REFRESH to apply security patches)"; \
    fi

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
