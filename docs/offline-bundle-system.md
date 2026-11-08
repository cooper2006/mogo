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
└── docling-models/               # docling 模型（刻意不分架构）
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
| `export_base_images.sh` | 导出基础镜像 tar |

通用子命令（以 apt 为例）：

```bash
ARCH_LIST=arm64 scripts/apt_packages_bundle.sh save <service>   # fetch + pack 一步到位
scripts/apt_packages_bundle.sh fetch <service>                  # 仅下载到 base-images/apt/<svc>/<arch>/
scripts/apt_packages_bundle.sh pack <service>                   # 仅重新打包 tar.gz 到构建上下文
```

**fetch 原理**：在"目标架构的基础镜像容器"里在线 `apt-get update`（国内镜像）+ `--reinstall --download-only` 把 `.deb` 抓到 `base-images/apt/<svc>/<arch>/`，并拷贝 apt 索引（`Packages.lz4` + `InRelease`）。`pack` 再把该目录打成 `services/<svc>/apt-packages-bundle.tar.gz` 供 Dockerfile 挂载后离线安装（`apt-get install --no-download`）。

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
