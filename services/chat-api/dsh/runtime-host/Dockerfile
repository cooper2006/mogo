# Pinnable base image so a build can be pointed at a registry mirror.
# Docker Hub is frequently unreachable from these networks; without this the
# only way past it was a daemon-wide registry-mirror setting, and a build could
# not proceed at all. Both stages share one ARG so they cannot drift apart.
ARG BASE_IMAGE=node:24-bookworm-slim
FROM ${BASE_IMAGE} AS dependencies

ARG MOVO_NPM_REGISTRY=https://registry.npmmirror.com

ENV NODE_ENV=production \
    PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH

WORKDIR /app

RUN if [ -n "${MOVO_NPM_REGISTRY}" ]; then npm config set registry "${MOVO_NPM_REGISTRY}"; fi \
    && npm install --global pnpm@10.34.4

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
# The pnpm store is mounted so it outlives lockfile changes (which invalidate
# this layer) and is reused across builds. This install measured ~6 minutes;
# note that `npm config set registry` above does reach pnpm (it reads the same
# user-level .npmrc), so the registry itself is already domestic.
RUN --mount=type=cache,target=/pnpm-store,sharing=locked \
    pnpm config set store-dir /pnpm-store \
    && pnpm install --frozen-lockfile --prod
RUN node -e "const declared=require('./package.json').dependencies['@deepseek-ai/dsh']; const installed=require('@deepseek-ai/dsh/package.json').version; if (declared !== installed) throw new Error('DSH version mismatch: declared='+declared+' installed='+installed); console.log('DSH Runtime installed version: '+installed)"

FROM ${BASE_IMAGE}

ARG MOVO_APT_MIRROR=http://mirrors.tuna.tsinghua.edu.cn/debian
ARG MOVO_APT_SECURITY_MIRROR=http://mirrors.tuna.tsinghua.edu.cn/debian-security
# Security refresh is opt-in. A non-empty value (CI passes its run id) also
# applies the latest distro security patches. ca-certificates and gosu are
# functional dependencies, so they are always installed regardless.
ARG MOVO_SECURITY_REFRESH=

ENV NODE_ENV=production

WORKDIR /app

# Offline apt package bundle (see scripts/apt_packages_bundle.sh): the apt mirror
# serves .deb at ~600 kB/s here, so re-downloading ca-certificates/gosu's
# dependency set on every rebuild is pure waste. The bundle carries the .deb
# files plus the apt index, because --no-download still needs the index to map
# names to versions. Same contract as the other bundles: git ships a <1KB
# empty-tar placeholder so COPY never fails.
COPY apt-packages-bundle.tar.gz /tmp/apt-packages-bundle.tar.gz

ARG TARGETARCH
ARG APT_OFFLINE_INSTALL=true
RUN set -eux; \
    unset XZ_DEFAULTS XZ_OPT; \
    rm -f /etc/apt/apt.conf.d/docker-clean; \
    apt_arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    offline=false; \
    if [ "${APT_OFFLINE_INSTALL}" = "true" ] \
        && [ "$(du -sb /tmp/apt-packages-bundle.tar.gz | cut -f1)" -gt 1024 ]; then \
        mkdir -p /tmp/apt-offline \
        && tar -xzf /tmp/apt-packages-bundle.tar.gz -C /tmp/apt-offline \
        && if [ -d "/tmp/apt-offline/${apt_arch}" ]; then \
               offline=true; \
               echo "Installing apt packages offline for ${apt_arch} ($(find /tmp/apt-offline/${apt_arch} -name '*.deb' | wc -l) deb files)"; \
               cp /tmp/apt-offline/${apt_arch}/*.deb /var/cache/apt/archives/ 2>/dev/null || true; \
               if [ -d "/tmp/apt-offline/${apt_arch}/Packages" ]; then \
                   cp /tmp/apt-offline/${apt_arch}/Packages/* /var/lib/apt/lists/ 2>/dev/null || true; \
               fi; \
           else \
               echo "Bundle has no ${apt_arch}/ directory; falling back to the network."; \
           fi; \
    else \
        echo "Skip offline apt bundle (placeholder or APT_OFFLINE_INSTALL=false); using the network."; \
    fi; \
    rm -f /tmp/apt-packages-bundle.tar.gz; \
    if [ -n "${MOVO_APT_MIRROR}" ]; then \
        for source_file in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources; do \
            if [ -f "${source_file}" ]; then \
                sed -i "s|http://deb.debian.org/debian|${MOVO_APT_MIRROR}|g; s|https://deb.debian.org/debian|${MOVO_APT_MIRROR}|g" "${source_file}"; \
                if [ -n "${MOVO_APT_SECURITY_MIRROR}" ]; then \
                    sed -i "s|http://deb.debian.org/debian-security|${MOVO_APT_SECURITY_MIRROR}|g; s|https://deb.debian.org/debian-security|${MOVO_APT_SECURITY_MIRROR}|g; s|http://security.debian.org/debian-security|${MOVO_APT_SECURITY_MIRROR}|g; s|https://security.debian.org/debian-security|${MOVO_APT_SECURITY_MIRROR}|g" "${source_file}"; \
                fi; \
            fi; \
        done; \
    fi; \
    if [ "${offline}" = "true" ]; then \
        apt-get update >/dev/null 2>&1 || true; \
    else \
        apt-get update; \
    fi; \
    if [ -n "${MOVO_SECURITY_REFRESH}" ] && [ "${MOVO_SECURITY_REFRESH}" != "false" ]; then \
        apt-get upgrade -y; \
    else \
        echo "Skip apt upgrade (set MOVO_SECURITY_REFRESH to apply security patches)"; \
    fi; \
    if [ "${offline}" = "true" ]; then \
        apt-get install -y --no-install-recommends --no-download ca-certificates gosu; \
    else \
        apt-get install -y --no-install-recommends ca-certificates gosu; \
    fi; \
    rm -rf /var/lib/apt/lists/* /tmp/apt-offline; \
    npm uninstall --global npm

COPY --from=dependencies /app/node_modules ./node_modules
COPY --from=dependencies /app/package.json ./package.json

COPY src ./src
COPY config ./config
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod -R a+rX /app \
    && chmod +x /app/entrypoint.sh \
    && mkdir -p /app/host-profile-home \
    && chown -R node:node /app/host-profile-home \
    && mkdir -p /data/dsh-runtime \
    && chown -R node:node /data/dsh-runtime

EXPOSE 8101

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["node", "src/host.mjs", "--host", "0.0.0.0", "--port", "8101", "--storage-root", "/data/dsh-runtime"]
