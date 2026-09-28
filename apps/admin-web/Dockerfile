FROM node:20-slim AS build

WORKDIR /app

ARG VITE_BASE_PATH=/admin/
ARG VITE_ADMIN_API_BASE_URL=/admin-api
ARG MOVO_NPM_REGISTRY=https://registry.npmmirror.com
ENV VITE_BASE_PATH=${VITE_BASE_PATH} \
    VITE_ADMIN_API_BASE_URL=${VITE_ADMIN_API_BASE_URL}

COPY package*.json ./
RUN if [ -n "${MOVO_NPM_REGISTRY}" ]; then npm config set registry "${MOVO_NPM_REGISTRY}"; fi \
    && npm ci --legacy-peer-deps

COPY . .
RUN npm run build

FROM nginx:1.29.8-alpine

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
