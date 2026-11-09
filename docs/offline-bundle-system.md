# 离线构建 Bundle 体系说明

> 目的：把构建时"需要从互联网（尽量国内源）下载的文件"缓存到 `base-images/` 目录，**按 `amd64` / `arm64` 分架构保存**，再按架构生成 tar 文件，构建时离线使用，避免重复下载、加速本地/CI 构建。
>
> 环境说明（2026-11-08 09:45）：本地开发栈当日曾迁到 `dory`，随后**切回 `kiri` 运行**；**全局默认 docker context 已改回 `kiri`**，**dory 引擎已下线**（`dorydctl engine stop` / `dory mode manual` / socket 消失，卷与镜像保留）。本文的 bundle 路径是宿主机共享文件，**两端通用、不需要迁移**；当前裸 `docker load` / `docker compose build` 走 kiri，无需 context 参数；若要用 dory，须先 `~/.dory/bin/dorydctl engine start` 再显式 `--context dory`。完整流程见 **`docs/dev-build-guide.md`**，其中 §7.1 / §10.8 专讲 kiri 构建必须固定 `BUILDX_BUILDER=kiri` 的坑。

## 目录结构

```
base-images/
├── images/<arch>/*.tar           # 基础镜像（python/node/nginx/redis/weaviate/alpine/panweidb …）
├── apt/<service>/<arch>/         # 各服务 apt 离线包（.deb + Packages 索引 + manifest.txt）
├── pip-wheels/<service>/<arch>/  # pip 离线 wheel 缓存
├── playwright/<arch>/            # playwright 浏览器
├── docling-models/               # docling 模型（刻意不分架构）
└── pnpm-store/                   # pnpm v11 内容寻址 store + 各架构 pnpm CLI
    ├── store/v11/files/...
    ├── pnpm-cli/<arch>/pnpm      # @pnpm/exe.<platform-arch> 原生二进制
    └── manifest.txt
```

- `docling-models` **不分架构**：模型目录只有 `safetensors`/`onnx`/`json`，没有 `.so`、没有可执行文件，纯数据跨架构通用。
- 各 `<arch>` 子目录：`amd64` / `arm64`。

## 基础镜像（`base-images/images`）

- 以 tar 形式保存，`arm64/` 与 `amd64/` 各一份（含 `manifest.txt` 记录平台与镜像清单）。
- **离线构建前必须先 `docker load`**：Docker daemon 无法从 docker.io 拉取缺失架构的镜像（本机网络只通代理/国内源）。加载后规范名标签（如 `node:24-bookworm-slim`）即变为对应架构，构建/运行原生进行。
- 生成（save）这些 tar 的脚本是 `scripts/export_base_images.sh`。

```bash
docker load -i base-images/images/arm64/node_24-bookworm-slim.tar
docker load -i base-images/images/arm64/nginx_1.31.5-alpine3.24-slim.tar
docker load -i base-images/images/arm64/python_3.13-slim-bookworm.tar
docker load -i base-images/images/arm64/redis_7.4.2-alpine.tar
docker load -i base-images/images/arm64/semitechnologies_weaviate_1.25.7.tar
```

## Bundle 脚本（`scripts/`）

| 脚本 | 作用 |
|---|---|
| `apt_packages_bundle.sh` | 各服务 apt `.deb` + 索引离线包 |
| `pip_wheels_bundle.sh` | pip wheel 离线缓存 |
| `playwright_browsers_bundle.sh` | playwright 浏览器 |
| `docling_models_bundle.sh` | docling 模型（不分架构） |
| `pnpm_store_bundle.sh` | pnpm store + 各架构 pnpm 原生 CLI |
| `export_base_images.sh` | 导出基础镜像 tar |

通用子命令（以 apt 为例）：

```bash
ARCH_LIST=arm64 scripts/apt_packages_bundle.sh save <service>   # fetch + pack 一步到位
scripts/apt_packages_bundle.sh fetch <service>                  # 仅下载到 base-images/apt/<svc>/<arch>/
scripts/apt_packages_bundle.sh pack <service>                   # 仅重新打包 tar.gz 到构建上下文
```

**fetch 原理**：在"目标架构的基础镜像容器"里在线 `apt-get update`（国内镜像）+ `--reinstall --download-only` 把 `.deb` 抓到 `base-images/apt/<svc>/<arch>/`，并拷贝 apt 索引（`Packages.lz4` + `InRelease`）。`pack` 再把该目录打成 `services/<svc>/apt-packages-bundle.tar.gz` 供 Dockerfile 挂载后离线安装（`apt-get install --no-download`）。

## pnpm bundle（第五类 bundle）

覆盖 `admin-web` / `user-web` / `dsh-runtime-host` 三个 Node 服务。此前它们每次构建都要从 `registry.npmmirror.com` 拉 600–1000 个包；在 Apple Silicon 上用 QEMU 仿真构建 linux/amd64 时实测 `npm install -g pnpm` **722.6s**、`admin-web` 整段安装 **1081.2s**（`backups/amd64-push-20261108/amd64-build.log` #49 / #50）。

**必须离线化的有两样，只做 store 不够：**

| 内容 | 来源 | 说明 |
|---|---|---|
| `store/v11/files/...` | BuildKit cache mount `/pnpm-store` | 项目依赖的内容寻址包，跨架构混存无副作用 |
| `pnpm-cli/<arch>/pnpm` | `@pnpm/exe.linux-x64` / `linux-arm64` | pnpm ≥ 11 的 CLI 是 **平台原生二进制**，不是 JS；`npm install -g pnpm` 本身就要下 ~24MB |

CLI 默认只打 `amd64`（QEMU 仿真目标，慢的就是它）；arm64 在 Apple Silicon 上是原生构建，`npm install -g pnpm` 秒级完成，缺 CLI 时自动走联网路径，但**离线 store 仍然生效**。需要给 amd64 宿主机打 arm64 镜像时用 `ARCH_LIST="amd64 arm64"` 覆盖。

```bash
# 一次性：从已有 BuildKit cache 导出 store + 拉 amd64 CLI（CLI 下载发生在宿主机，无 QEMU）
DOCKER_BIN=/opt/homebrew/bin/docker BUILDX_BUILDER=kiri MOGO_DOCKER_CONTEXT=kiri \
  scripts/pnpm_store_bundle.sh save
DOCKER_BIN=/opt/homebrew/bin/docker scripts/pnpm_store_bundle.sh pack
scripts/pnpm_store_bundle.sh status

# 可选：从 lockfile 在目标架构容器里重建 store（用于 CI / 换机）
ARCH_LIST=amd64 scripts/pnpm_store_bundle.sh fetch
```

`pack` 会写出三个同内容的构建上下文包（其内容指纹相同则跳过重打，复用 `scripts/bundle_pack_lib.sh` 的可复现打包）：

```
apps/admin-web/pnpm-store-bundle.tar.gz
apps/user-web/pnpm-store-bundle.tar.gz
services/chat-api/dsh/runtime-host/pnpm-store-bundle.tar.gz
```

Dockerfile 契约（`ARG PNPM_OFFLINE_INSTALL=true`，由 `docker-compose.build.yml` 显式传入）：

1. 通过 `--mount=type=bind,source=pnpm-store-bundle.tar.gz` 挂载，不产生镜像层；
2. 解出 `store/` 后 `cp -a` 进 cache mount `/pnpm-store`，`pnpm install --offline --frozen-lockfile --trust-lockfile`；`--trust-lockfile` 不可省——pnpm ≥ 12 默认会做 supply-chain 策略校验并索要 registry 元数据，纯离线时会报 `ERR_PNPM_NO_OFFLINE_META` 而退化成联网（实测每个元数据请求 10–47s）。联网回退分支不加该参数，保留 pnpm 默认校验；
3. 按 `TARGETARCH` 取 `pnpm-cli/${arch}/pnpm` 装到 `/usr/local/bin/pnpm`，命中即完全不联网；
4. 包缺失/占位（<1KB）、CLI 缺失或 `--offline` 安装失败时**自动回退联网**，不会把构建直接搞挂。

> **构建前必须先 `pack`**：与 pip/apt bundle 一样，这些 tar.gz 不入库（`.gitignore` 已列），而 Dockerfile 用 bind mount 引用它们，文件不存在会在计算缓存键时直接报 "not found"。

### QEMU 下的 vite / esbuild 崩溃（与 bundle 无关，但同属 amd64 离线构建）

即便依赖全离线，`pnpm run build` 仍可能在 QEMU 下 9 秒内崩掉：

```
fatal error: lfstack.push
Error: The service was stopped
```

根因是 Go runtime 的 `runtime/lfstack.go`：把指针与计数打包进一个 uint64 时，QEMU/binfmt 会把地址高位错误地符号扩展（实测 `0xffff6e99f240` → `0xffffffff6e99f240`），于是 `lfstack.push` 直接 fatal。这是**仿真层的硬缺陷，不是资源或并发问题**。

> 已验证无效：`GOMAXPROCS=1 GODEBUG=asyncpreemptoff=1 pnpm run build` 仍在 10.6s 崩在 `lfstack.push`、19.9s 报 `The service was stopped`（`backups/amd64-push-20261108/amd64-build-retry2.log` #36）。环境变量绕不过去。

**现行解法：前端产物预置（opt-in `MOGO_PREBUILT_DIST`）**。前端 `dist` 是纯 HTML/JS/CSS，与架构无关，因此在宿主机原生 arm64 上构建，镜像只负责 COPY，彻底不在 QEMU 下跑 vite/esbuild：

```bash
# 1) 宿主机原生产出 dist（必须与 Dockerfile 的 Vite 变量一致）
(cd apps/admin-web && VITE_BASE_PATH=/admin/ VITE_ADMIN_API_BASE_URL=/admin-api pnpm run build)
(cd apps/user-web  && VITE_ADMIN_WEB_URL=/admin/ pnpm run build)

# 2) 跨架构构建时显式开启；.dockerignore 已放开 dist/ 让产物进入 context
MOGO_PREBUILT_DIST=true MOGO_VERSION=latest MOGO_PLATFORM=linux/amd64 \
  ./mogo build admin-web user-web
```

- `apps/admin-web/Dockerfile`、`apps/user-web/Dockerfile.prod` 的 build 阶段：开启时校验 `dist/index.html` 存在并直接使用；关闭时先 `rm -rf dist` 再照常 `pnpm run build`，所以本地残留 dist 不会影响常规构建。
- `docker-compose.build.yml` 把 `MOGO_PREBUILT_DIST` 透传给两个前端服务，默认 `false`（本地 arm64 dev 行为完全不变）。
- 宿主机需要 pnpm 12.14.0 与已安装的 `node_modules`；Vite 变量漏设会导致产物里的 API base 路径错误，务必按上面命令注入。

## 已踩坑（务必注意）

1. **apt 镜像必须用 HTTP，不是 HTTPS**：fetch 容器是 `node:24-bookworm-slim` 等 slim 镜像，**没有 `ca-certificates`**，HTTPS 校验失败 → apt 把 `InRelease` 标 `Ign`（忽略）→ 索引拿不到 → 离线安装报 `Unable to locate package` / `Package … has no installation candidate`。脚本默认 `MOGO_APT_MIRROR` 是 HTTP（清华源），**不要覆盖成 HTTPS**。

2. **arm64 基础镜像要先 `docker load`**：daemon 无法从 docker.io 拉取缺失架构镜像。arm64 构建前务必先 `docker load -i base-images/images/arm64/<img>.tar`，否则 fetch 容器起不来、构建退化为 amd64 或直接失败。

3. **dsh-runtime-host 的 arm64 apt bundle 曾不完整**：原 bundle 缺 `ca-certificates`/`gosu` 的有效索引条目，离线安装失败。已用 `ARCH_LIST=arm64 scripts/apt_packages_bundle.sh save dsh-runtime-host`（HTTP 镜像）重新生成，得到完整 7 个 `.deb` + 索引并重打包。

4. **`.env` 的 `MOGO_PLATFORM` 必须是 `linux/arm64`**：原 `.env` 残留 `linux/amd64`，会让带 `platform:` 字段的服务（`dsh-runtime-host`，来自 `x-dsh-runtime-host-template`）被强制 amd64 仿真。在 Apple Silicon 上做 dev 应设为 `linux/arm64`。

5. **gateway / admin-web / user-web 的 `platform:` 字段已补到 `docker-compose.yml`**：此前这三个服务没有 `platform:` 字段，会按 daemon 默认架构构建（Kiri 下曾被当成 amd64），必须用临时 override 才能强制 arm64。现已为它们加上 `platform: ${MOGO_PLATFORM:-}`（与 `dsh-runtime-host` 模板一致），由 `deploy/cli/env-profiles.sh` 按 profile 推导：dev/test → `linux/arm64`，prod → `linux/amd64`。**因此不再需要 `/tmp/platform-override.yml`，未来 `build` 会确定性地走正确架构。**

   > 注：`.env` 里**不要**再硬编码 `MOGO_PLATFORM=linux/amd64`——它会作为"显式值"原样覆盖 profile 推导（见 `mogo_profile_configure_platform`）。dev 开发机直接让它从 profile 推导（或显式写 `linux/arm64`）即可。

6. **基础镜像 tar 必须是「干净名」**：`base-images/images/<arch>/*.tar` 导出时镜像内的 `repo:tag` 必须是规范干净名（如 `nginx:1.31.5-alpine3.24-slim`），不能是镜像站别名（如 `docker.m.daocloud.io/library/nginx`）。否则 `docker load` 不会覆盖干净名标签，导致离线构建/切换时架构对不上。`nginx` 的 amd64 tar 早期曾带镜像站别名，已重新 `save` 为干净名修正；若其他 tar 也出现非干净名，先 `docker tag` 改成干净名再 `save` 覆盖即可。基础镜像干净名在 arm64(dev) 与 amd64(推远端) 之间的切换见文末脚本。

## 基础镜像干净名：arm64(dev) ↔ amd64(推离线远端) 一键切换

同一个 `repo:tag` 在同一 docker daemon 里不能同时是 arm64 又是 amd64。本地 dev 全 arm64 原生，而 `deploy/production/deploy-remote-push.sh` 要求 `BASE_IMAGES`（alpine:3.21 / nginx:1.31.5-alpine3.24-slim / redis:7.4.2-alpine / semitechnologies/weaviate:1.25.7）是 amd64 才能推送离线 amd64 远端（其第 328–334 行有架构安全网，非 amd64 会被拦截）。

为免去手工 retag，提供一键脚本：

```bash
deploy/production/switch-base-image-arch.sh amd64   # 干净名切到 amd64（推远端前执行）
deploy/production/switch-base-image-arch.sh arm64   # 恢复 arm64（本地 dev 原生运行）
deploy/production/switch-base-image-arch.sh status  # 查看 4 个干净名当前架构
```

- **amd64 来源**：优先用离线 bundle 刻意保留的 `mogo-staging/<suffix>:amd64` 标签直接 `tag`；nginx 没有该 staging 标签，故从其 `base-images/images/amd64/nginx_*.tar`（已修正为干净名）`load` 后 retag。
- **arm64 来源**：统一从 `base-images/images/arm64/*.tar` `load`（arm64 无 staging 标签）。
- 脚本只改 `repo:tag` 指向的镜像 ID，被运行中容器引用的原镜像层不受影响，**对运行中的 dev 栈安全**；但切到 amd64 后请勿执行 `mogo up --build`（否则 dev 会构建出 amd64 应用），应直接跑 `deploy-remote-push.sh`。
- 切换产生的冗余镜像站别名会被脚本自动清理，`mogo-staging/*:amd64` bundle 标签始终保留（给 CI/远端用）。

## 在当前 Apple Silicon 机器上把业务镜像重建为 arm64 的步骤

（gateway / admin-web / user-web / dsh-runtime-host 原本是 amd64）：

```bash
# 1) 加载 arm64 基础镜像
docker load -i base-images/images/arm64/node_24-bookworm-slim.tar
docker load -i base-images/images/arm64/nginx_1.31.5-alpine3.24-slim.tar
docker load -i base-images/images/arm64/python_3.13-slim-bookworm.tar   # 仅在未缓存时

# 2) 重建 arm64 apt bundle（dsh-runtime-host）
ARCH_LIST=arm64 scripts/apt_packages_bundle.sh save dsh-runtime-host

# 3) 离线构建（走 bundle）。platform 已由 docker-compose.yml 的
#    `platform: ${MOGO_PLATFORM:-}` 按 profile 推导，无需临时 override。
docker compose -f docker-compose.yml -f docker-compose.build.yml \
  build gateway admin-web user-web dsh-runtime-host

# 4) 重启 dev 栈（--no-build 复用镜像；镜像 digest 变化会自动重建对应容器）
#    ./mogo CLI 会自动把 MOGO_VERSION 注入为 git HEAD 短哈希，不用显式传；
#    .env 里残留的 60e8e90d 不参与 CLI 路径（见 dev-build-guide.md §11）。
#    DOCKER_CONTEXT 按当前运行端选择；上一步 build 也要带同一个 context。
DOCKER_CONTEXT=kiri ./mogo --profile dev up --no-build
```

> 注：依赖镜像 `weaviate` / `redis`（非项目构建）同样用 `base-images/images/arm64/` 下的 tar `docker load` 后重启即可切到 arm64；`mongo` 本地已是 arm64。
