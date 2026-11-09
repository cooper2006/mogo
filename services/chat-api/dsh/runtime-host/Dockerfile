# Pinnable base image so a build can be pointed at a registry mirror.
# Docker Hub is frequently unreachable from these networks; without this the
# only way past it was a daemon-wide registry-mirror setting, and a build could
# not proceed at all. Both stages share one ARG so they cannot drift apart.
ARG BASE_IMAGE=node:24-bookworm-slim
FROM ${BASE_IMAGE} AS dependencies

ARG MOGO_NPM_REGISTRY=https://registry.npmmirror.com
ENV MOGO_NPM_REGISTRY=${MOGO_NPM_REGISTRY}

ENV NODE_ENV=production \
    PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH

WORKDIR /app

# Offline pnpm CLI (see scripts/pnpm_store_bundle.sh). pnpm >=11 is a
# platform-specific @pnpm/exe native binary, so the bundle ships one per
# TARGETARCH. The same bundle carries the content-addressable store used by
# the install step below; a missing or placeholder bundle keeps the original
# online path working.
ARG PNPM_OFFLINE_INSTALL=true
ARG TARGETARCH
RUN --mount=type=bind,source=pnpm-store-bundle.tar.gz,target=/tmp/pnpm-store-bundle.tar.gz \
    set -eux; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    case "${arch}" in x86_64) arch=amd64;; aarch64) arch=arm64;; esac; \
    cli_restored=""; \
    if [ "${PNPM_OFFLINE_INSTALL}" = "true" ] \
       && [ "$(du -sb /tmp/pnpm-store-bundle.tar.gz | cut -f1)" -gt 1024 ]; then \
        rm -rf /tmp/pnpm-offline; mkdir -p /tmp/pnpm-offline; \
        tar -xzf /tmp/pnpm-store-bundle.tar.gz -C /tmp/pnpm-offline; \
        if [ -s "/tmp/pnpm-offline/pnpm-cli/${arch}/pnpm" ]; then \
            install -m 0755 "/tmp/pnpm-offline/pnpm-cli/${arch}/pnpm" /usr/local/bin/pnpm; \
            echo "pnpm CLI restored from offline bundle (${arch})"; \
            cli_restored="yes"; \
        fi; \
    fi; \
    if [ -z "${cli_restored}" ]; then \
        npm config set registry "${MOGO_NPM_REGISTRY:-https://registry.npmmirror.com}"; \
        npm install --global pnpm@12.14.0; \
    fi

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
# The pnpm store is mounted so it outlives lockfile changes (which invalidate
# this layer) and is reused across builds. This install measured ~6 minutes;
# note that `npm config set registry` above does reach pnpm (it reads the same
# user-level .npmrc), so the registry itself is already domestic.
# Offline installs also pass --trust-lockfile: pnpm >=12 otherwise verifies
# the lockfile against supply-chain policies and demands registry metadata
# (ERR_PNPM_NO_OFFLINE_META), which --offline cannot fetch.
RUN --mount=type=cache,target=/pnpm-store,sharing=locked \
    --mount=type=bind,source=pnpm-store-bundle.tar.gz,target=/tmp/pnpm-store-bundle.tar.gz \
    set -eux; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    case "${arch}" in x86_64) arch=amd64;; aarch64) arch=arm64;; esac; \
    offline=""; \
    if [ "${PNPM_OFFLINE_INSTALL}" = "true" ] \
       && [ "$(du -sb /tmp/pnpm-store-bundle.tar.gz | cut -f1)" -gt 1024 ]; then \
        rm -rf /tmp/pnpm-offline; mkdir -p /tmp/pnpm-offline /pnpm-store; \
        tar -xzf /tmp/pnpm-store-bundle.tar.gz -C /tmp/pnpm-offline; \
        if [ -d /tmp/pnpm-offline/store ]; then \
            cp -a /tmp/pnpm-offline/store/. /pnpm-store/; \
            echo "Using offline pnpm store from bundle (${arch})"; \
            offline="--offline"; \
        fi; \
    fi; \
    pnpm config set store-dir /pnpm-store; \
    pnpm config set registry "${MOGO_NPM_REGISTRY:-https://registry.npmmirror.com}"; \
    trust=""; if [ -n "${offline}" ]; then trust="--trust-lockfile"; fi; \
    if ! pnpm install ${offline} --frozen-lockfile --prod ${trust}; then \
        if [ -n "${offline}" ]; then \
            echo "Offline install incomplete; retrying against the registry"; \
            pnpm install --frozen-lockfile --prod; \
        else \
            exit 1; \
        fi; \
    fi
RUN node -e "const declared=require('./package.json').dependencies['@deepseek-ai/dsh']; const installed=require('@deepseek-ai/dsh/package.json').version; if (declared !== installed) throw new Error('DSH version mismatch: declared='+declared+' installed='+installed); console.log('DSH Runtime installed version: '+installed)"

FROM ${BASE_IMAGE}

ARG MOGO_APT_MIRROR=http://mirrors.tuna.tsinghua.edu.cn/debian
ARG MOGO_APT_SECURITY_MIRROR=http://mirrors.tuna.tsinghua.edu.cn/debian-security
# Security refresh is opt-in. A non-empty value (CI passes its run id) also
# applies the latest distro security patches. ca-certificates and gosu are
# functional dependencies, so they are always installed regardless.
ARG MOGO_SECURITY_REFRESH=

ENV NODE_ENV=production

WORKDIR /app

# Offline apt package bundle (see scripts/apt_packages_bundle.sh): the apt mirror
# serves .deb at ~600 kB/s here, so re-downloading ca-certificates/gosu's
# dependency set on every rebuild is pure waste. The bundle carries the .deb
# files plus the apt index, because --no-download still needs the index to map
# names to versions. Same contract as the other bundles: git ships a <1KB
# empty-tar placeholder so the mount always resolves.
#
# Mounted rather than COPYed: a COPY layer would keep the whole tar in the image
# permanently, since removing it later only adds a whiteout. The mount is
# read-only, exists only for this RUN, and BuildKit still folds the file's
# digest into the cache key.
ARG TARGETARCH
ARG APT_OFFLINE_INSTALL=true
RUN --mount=type=bind,source=apt-packages-bundle.tar.gz,target=/tmp/apt-packages-bundle.tar.gz \
    set -eux; \
    unset XZ_DEFAULTS XZ_OPT; \
    rm -f /etc/apt/apt.conf.d/docker-clean; \
    apt_arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    offline=false; \
    if [ "${APT_OFFLINE_INSTALL}" = "true" ] \
        && [ "$(du -sb /tmp/apt-packages-bundle.tar.gz | cut -f1)" -gt 1024 ]; then \
        mkdir -p /tmp/apt-offline \
        && { tar -xzf /tmp/apt-packages-bundle.tar.gz -C /tmp/apt-offline "./${apt_arch}" 2>/dev/null || true; } \
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
    if [ -n "${MOGO_APT_MIRROR}" ]; then \
        for source_file in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources; do \
            if [ -f "${source_file}" ]; then \
                sed -i "s|http://deb.debian.org/debian|${MOGO_APT_MIRROR}|g; s|https://deb.debian.org/debian|${MOGO_APT_MIRROR}|g" "${source_file}"; \
                if [ -n "${MOGO_APT_SECURITY_MIRROR}" ]; then \
                    sed -i "s|http://deb.debian.org/debian-security|${MOGO_APT_SECURITY_MIRROR}|g; s|https://deb.debian.org/debian-security|${MOGO_APT_SECURITY_MIRROR}|g; s|http://security.debian.org/debian-security|${MOGO_APT_SECURITY_MIRROR}|g; s|https://security.debian.org/debian-security|${MOGO_APT_SECURITY_MIRROR}|g" "${source_file}"; \
                fi; \
            fi; \
        done; \
    fi; \
    if [ "${offline}" != "true" ]; then \
        apt-get update; \
    fi; \
    if [ "${offline}" = "true" ]; then \
        echo "Skip apt upgrade in offline mode (no network to fetch security patches)"; \
    elif [ -n "${MOGO_SECURITY_REFRESH}" ] && [ "${MOGO_SECURITY_REFRESH}" != "false" ]; then \
        apt-get upgrade -y; \
    else \
        echo "Skip apt upgrade (set MOGO_SECURITY_REFRESH to apply security patches)"; \
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
    && chown -R node:node /data/dsh-runtime \
    # 官方 dsh web 模式（DSH_WEB_MODE=1 时由 entrypoint.sh 启用）依赖
    # @deepseek-ai/dsh-web-frontend 的构建产物；它只在 pnpm 虚拟仓库里，
    # 不在顶层 node_modules。按「包名@版本」前缀探测：0.2.2-rc.1 起该包
    # 带 cordis peer，pnpm 会在目录名后追加 peer 后缀，精确目录名会失效。
    && node -e "const fs=require('fs'),path=require('path');const store=path.join(process.cwd(),'node_modules','.pnpm');const prefix='@deepseek-ai+dsh-web-frontend@0.2.2-rc.1';const hit=fs.readdirSync(store).filter(d=>d.startsWith(prefix)).find(d=>fs.existsSync(path.join(store,d,'node_modules','@deepseek-ai','dsh-web-frontend','dist','index.html')));if(!hit)throw new Error('dsh-web-frontend dist/index.html not found under '+prefix+'*');console.log('DSH web frontend dist verified at '+path.join(store,hit));const dshBin=path.join(store,'.bin','dsh');if(!fs.existsSync(path.join(process.cwd(),'node_modules','.bin','dsh')))throw new Error('dsh CLI binary not linked in node_modules/.bin');console.log('dsh CLI verified in node_modules/.bin');"

# 022 US3 (T027): container hardening, same shape as the other app images.
#
# The runtime host keeps every mutable byte outside the image filesystem:
#   * kernel sessions / workspaces -> the dsh-runtime-data volume
#   * $HOME/.dsh (anonymous user id) -> HOME points into that same volume
#   * the cordis host profile      -> tmpfs (regenerated on every boot)
#   * scratch space                -> tmpfs /tmp
# so the image rootfs can be mounted read-only.
#
# Running as the non-root `node` user (UID 1000) is what makes `cap_drop: ALL`
# safe: the process starts unprivileged, so no CAP_SETUID/CAP_SETGID is needed
# for a privilege drop. The entrypoint still supports a forced uid 0 (gosu).
#
# HOME is set here rather than in compose on purpose: the pool replicas each
# declare their own `environment`, and a YAML merge key (`<<:`) is a *shallow*
# merge — a replica's `environment` replaces the anchor's wholesale, so a HOME
# defined in the anchor would silently disappear for every replica.
#
# The DSH anonymous-user-id plugin persists under $HOME/.dsh, so keeping HOME
# inside the writable (and per-replica isolated) data volume makes that identity
# survive restarts without adding another volume per replica.
ENV HOME=/data/dsh-runtime/home

# @deepseek-ai/dsh-plugin-manager 在查询 registry / 安装插件时按名字 spawn
# `pnpm`（execa(options.command ?? "pnpm", ...)）。dependencies 阶段的全局
# pnpm 装在 /pnpm，不会进入 runtime 阶段；runtime 里只剩
# /app/node_modules/.bin/pnpm，若不在 PATH 会报 "spawn pnpm ENOENT"。
# 追加到末尾，系统命令优先，避免 node_modules/.bin 下的 shim 遮蔽。
ENV PATH=$PATH:/app/node_modules/.bin

USER node

# 8101 — mogo 自研 headless runtime host（默认 CMD）
# 3080 — 官方 `dsh --profile web` Web GUI（DSH_WEB_MODE=1 时启用，默认关闭）
EXPOSE 8101 3080

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["node", "src/host.mjs", "--host", "0.0.0.0", "--port", "8101", "--storage-root", "/data/dsh-runtime"]
