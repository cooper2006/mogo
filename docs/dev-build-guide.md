# 本地开发环境：离线加速构建与重启服务

> 状态：**现行指南**（2026-11-08 从 Kiri 迁移后生效）
> 文件名沿革：原名 `docs/dory-dev-build-guide.md`（迁移到 Dory 引擎时命名）；2026-11-08 运行端切回 kiri 后更名为 `docs/dev-build-guide.md`，内容仍为同一份指南。
> 版本基线：**由 `./mogo` CLI 自动取 `git rev-parse --short HEAD`，不需要显式传 `MOGO_VERSION`**（2026-11-08 11:00 重建时 HEAD = `17f3348b`；之后每次提交都会变，请以命令实际输出为准，见 §3 / §11）
> 前代文档：`docs/kiri-dev-build-guide.md`（Kiri 时代，**已停用**，仅作历史）
> 离线 bundle 体系：`docs/offline-bundle-system.md`（权威）
>
> **当前运行状态（2026-11-08 11:00）**：服务跑在 **kiri**（11 个业务容器 healthy、HTTP 200），已在 kiri 用离线 bundle 增量重建 `17f3348b` 镜像并重启；**全局默认 docker context 为 `kiri`**；**dory 引擎已下线**（`dorydctl engine stop` → `stopped`，`dory mode manual`，`~/.dory/dory.sock` 已消失）。
>
> ⚠️ **本文档中所有 `--context dory` / `DOCKER_CONTEXT=dory` 命令当前都会失败**（`connect: no such file or directory`）。要按 dory 流程操作，先恢复引擎：
> ```bash
> ~/.dory/bin/dorydctl engine start        # 或 ~/.dory/bin/dory engine wake
> ~/.dory/bin/dory mode always-on          # 可选：恢复原来的「始终在线」模式
> /opt/homebrew/bin/docker --context dory info   # 验证 29.6.1 / aarch64
> ```
> dory 的 12 个容器 / 10 个卷 / 14 个镜像**全部保留**（清单见 `backups/kiri-to-dory-20261108/dory-*-at-offline.txt`），恢复后数据原样可用。日常开发请直接用 kiri，构建须固定 `BUILDX_BUILDER=kiri-bk2`（2026-11-10 起唯一可用 builder；旧文档写的 `kiri` 已停用），见 §7.1 / §10.8。本文其余章节（bundle、基础镜像、离线开关、排障、CLI 速查）两端都适用。

本文档记录**本地开发栈**的「离线 bundle → 加载基础镜像 → 启动 / 离线构建 → 健康确认」完整流程，面向大陆内网 / 离线环境下跑 mogo 自托管开发环境的工程师。本指南不绑定具体 docker 引擎（原名带 Dory 是迁移期的历史命名，现已更名）；两端流程已实测等价，差异集中在 context 与 buildx builder，见 §0 / §7.1。

**已实测**（2026-11-08）：
- dory：① `./mogo up`（不构建）11 容器 healthy / HTTP 200；② `./mogo up --build` 离线全量重建 7 个业务镜像 **3 分 09 秒**，四类 bundle 全命中、零联网回退（§7）。
- kiri：③ `./mogo up --build` 离线全量重建 7 个业务镜像 **3 分 46 秒**，同样四类 bundle 全命中、零联网回退，基础镜像解析全部 `CACHED`（§7.1）。

---

## 0. 与 Kiri 版的关键差异

2026-11-08 把 kiri 上的 9 个 `mogo_*` 数据卷与 14 个镜像迁到 dory，服务随之切换。迁移与校验明细见 `backups/kiri-to-dory-20261108/manifest.json`。

> 下表整体是 **2026-11-08 迁移时刻快照**；其中 `buildx builder` / `buildx 缓存卷` 两行已按 **2026-11-10 现状** 更新（旧值及变迁见 §7.1），因为照旧值操作现在已经跑不通。

| 项 | Kiri（当前运行） | Dory（迁移目标 / 已停服） |
|---|---|---|
| Docker context | `kiri`（**当前全局默认**，也是服务运行端） | `dory`（**引擎已下线**，须先 `dorydctl engine start` 才可用） |
| 引擎 | Kiri 0.1.18，OCI image store | Docker 29.6.1，经典 image store |
| socket | `~/.kiri/run/docker.sock` | `~/.dory/dory.sock` |
| buildx builder | **`kiri-bk2`**（docker-container, v0.34.2，**当前唯一可用**；`kiri` / `kiri-build` 已停用） | `dory`（docker driver, v0.31.1） |
| buildx 缓存卷 | `buildx_buildkit_kiri-bk20_state` ≈ 5.0 GB（11-08 的 `kiri-cn0` 16.9 GB 已清空并清理） | **无**，首次全量构建需重新暖缓存 |
| local registry | `mogo-local-reg` 容器 | **无**（CLI 并不硬依赖它） |
| 基础镜像来源 | 镜像站别名需手工补规范名 tag（旧文档 §5.4） | `base-images/images/arm64/*.tar` **已是干净名**，直接 `docker load` |
| 业务镜像来源 | 2026-11-08 09:33 已在 kiri 用离线 bundle 重建（tag 不变） | 先由 kiri `save/load` 迁入 `9a916043`；09:05 已在 dory 用离线 bundle 重建（tag 不变） |
| 服务状态 | 11 个业务容器 `Up (healthy)` + 4 个非业务容器 | 11 个业务容器 `Exited`，9 卷 / 14 镜像保留，可随时切回 |

> **两端都发布 `3000` / `8443`，不能同时运行。** 切换前必须先停另一端（§10.4 / §10.6）。

> 跨运行时注意：Kiri 用 OCI image store，`docker save` → dory `docker load` 后镜像 ID 与 `RootFS.Layers` 的 diff_id 都会变（层被重序列化），**不代表内容丢失**。校验应以层数、Config 元数据、镜像内文件抽查、可启动性为准，不要比 Image ID。

> 构建能力：**两端都能构建**。今早曾出现「kiri 构建卡死、切 dory 也一样卡」的现象，根因是**当时 agent 会话的沙箱层**阻断 buildkit 长 gRPC 流，不是 Kiri 引擎缺陷；本轮同一会话下两端 `FROM scratch` 均 0.2 秒成功（kiri 多步构建 1.1s / dory 0.6s）。两端真实的架构差异只影响**构建速度与缓存来源**，不影响能否构建，详见 §7。

> **2026-11-08 09:33 切回 kiri**：按「kiri 有 16.9 GB 暖 buildx 缓存 + 本地 registry mirror，更省资源」的判断，已停 dory、在 kiri 用同一套离线 bundle 重建并起服务。切回前把 dory 停服时刻的 9 个卷导到 `backups/kiri-to-dory-20261108/dory-volumes-at-switchback/`（44 MB，带 SHA256）；kiri 用迁移时刻的卷，两者只差 1 条 `position_role_audit_logs` 运行期审计日志，需要时用该快照补齐。
>
> **但 kiri 首次构建失败过一次**：compose bake 回退到 `default` builder（无 mirror、空缓存），解析 `FROM nginx` 直连 `registry-1.docker.io` 超时；当时固定 `BUILDX_BUILDER=kiri` 后成功（该 builder 现已停用，当前须用 `kiri-bk2`）。所以「kiri 更省资源」的前提是 **builder 选对**，否则反而会卡在联网解析上。见 §7.1 / §10.8。

---

## 1. 目标服务与架构

| 类别 | 服务 | 镜像 | 端口 / 入口 |
|---|---|---|---|
| API | `admin-api` | `ghcr.io/mogoai/admin-api:<HEAD 短哈希>` | 内部 |
| API | `chat-api` | `ghcr.io/mogoai/chat-api:<HEAD 短哈希>` | 内部 |
| API | `document-api` / `document-worker` | `ghcr.io/mogoai/document-parser:<HEAD 短哈希>`（同镜像，不同 CMD） | 内部 |
| Runtime | `dsh-runtime-host` | `ghcr.io/mogoai/dsh-runtime-host:<HEAD 短哈希>` | 内部 |
| Web | `admin-web` / `user-web` | `ghcr.io/mogoai/{admin-web,user-web}:<HEAD 短哈希>` | 内部 |
| Gateway | `gateway` | `ghcr.io/mogoai/gateway:<HEAD 短哈希>` | `localhost:3000` / `8443` |
| DB (dev) | `mongo` | `mongo:8.3.13` | 栈内 |
| DB (test) | `panweidb` | `panweidb:3.2.0` | 栈内（需 `docker load`） |
| Cache | `redis` | `redis:7.4.2-alpine` | 栈内 |
| Vector | `weaviate` | `semitechnologies/weaviate:1.25.7` | 栈内 |

业务镜像以 git 短哈希为 tag，与 HEAD 绑定，由 `./mogo` CLI 在每次 `up` / `build` 时自动注入（`mogo_default_version()` → `git rev-parse --short HEAD`），**命令行不用显式带 `MOGO_VERSION`**。2026-11-08 11:00 的 HEAD 为 `17f3348b`；要固定到某个 tag（复现旧版本、发布）时，显式 `MOGO_VERSION=<tag>` 仍然优先。本文 §0 / §7 中出现的 `9a916043` 是 11-08 上午迁移与两端全量构建时的**历史 tag**，不是当前值。

---

## 2. Profile 体系

`deploy/cli/env-profiles.sh` 维护三套 profile，由 `./mogo --profile <name>` 或 `MOGO_DATA_BACKEND` 触发。

| Profile | `MOGO_DATA_BACKEND` | `MOGO_PLATFORM` | 数据后端 | 用途 |
|---|---|---|---|---|
| `dev` | `mongo` | `linux/arm64` | 栈内 mongo | 本地开发（**当前 .env**） |
| `test` | `panweidb` | `linux/arm64` | 栈内 / 外部 PanWeiDB | 本地演练 |
| `prod` | `panweidb`（外部） | `linux/amd64` | 外部 PanWeiDB | 生产部署 |

推断优先级（无 `--profile`）：`MOGO_USE_EXTERNAL_DB=1` → prod；`MOGO_DATA_BACKEND=panweidb` → test；其余 → dev。

当前 `.env` 实际值：`MOGO_DATA_BACKEND=mongo`、`MOGO_USE_EXTERNAL_DB=0`、`MOGO_PLATFORM=linux/arm64`、`MOGO_PULL_POLICY=missing`、`MOGO_IMAGE_REGISTRY=ghcr.io/mogoai`。
**旧 Kiri 文档 §2 说「.env 默认 panweidb」已过时**，现在默认就是 dev，不需要为跑 dev 而额外覆盖后端。

切到 test 前需先加载 PanWeiDB 镜像：

```bash
docker --context dory load -i base-images/images/arm64/panweidb_3.2.0.tar
```

---

## 3. 前置检查清单（最关键）

以下代码块默认 `D=/opt/homebrew/bin/docker`。本机 docker CLI 实际就装在这个路径，显式写绝对路径可避开不同 shell 会话的 PATH 差异。文中其他零散出现的 `docker --context dory ...` 也请用同一路径理解；若你的 shell 能直接调用 `docker`，等价替换即可。

```bash
D=/opt/homebrew/bin/docker
cd /Users/cooper/mogo

# 1) 默认 context = kiri（服务运行端）；dory 引擎已下线，需先 start 才能用
"$D" context show                        # → kiri
"$D" --context dory info --format '{{.ServerVersion}} {{.Architecture}}'
#   → 当前报 "no such file or directory"（引擎已停，属预期）；恢复命令见本节末尾

# 2) 版本基线：./mogo 自动注入 git HEAD 短哈希，无需显式带 MOGO_VERSION
git rev-parse --short HEAD               # 例：17f3348b（每次提交都会变）
"$D" images --format '{{.Repository}}:{{.Tag}}' | grep 'ghcr.io/mogoai/admin-api' | head
#   → 应能看到与上面同 tag 的镜像；不一致就先 ./mogo up --build
# 注：.env 里残留的 MOGO_VERSION=60e8e90d 不参与 CLI 路径（CLI 先 export
#     git HEAD，mogo_configure_images 的 ${MOGO_VERSION:-...} 短路，不读 .env）。
#     只有绕过 CLI 直接 `docker compose` 时才会用到那个旧值，见 §10.2 / §11。

# 3) 离线 bundle 就绪
ls base-images/images/arm64/*.tar | wc -l    # 期望 7
du -sh base-images/                          # 约 4.8 GB

# 4) 端口未被 kiri 占用
lsof -nP -iTCP:3000 -iTCP:8443 -sTCP:LISTEN || echo "端口空闲"
```

**为什么必须显式指定 context**：`./mogo` 通过 `mogo_compose()` 调用 docker，**不硬编码 context**，会跟随当前默认 context（现为 `kiri`）。若忘记指定，`./mogo up` 会在 kiri 上重建服务，而且两边端口冲突。

**为什么不用 `docker context use dory`**：技术上可行，但它改的是全局默认值，会影响其他会话和 `deploy/production/*` 里那些显式 `--context kiri` 的生产推送脚本。需要 dory 时按命令注入 `DOCKER_CONTEXT=dory`；**当前全局默认已是 `kiri`**，日常开发不需要任何 context 参数。

> **dory 下线后的恢复步骤（2026-11-08 09:45 起）**：引擎已被 `dorydctl engine stop` 硬停，`dory mode` 置为 `manual`、`engineDesiredState=sleeping`，`~/.dory/dory.sock` 消失且**不会自动唤醒**（`docker --context dory info` 实测连接失败）。要回到 dory：
> ```bash
> ~/.dory/bin/dorydctl engine start
> ~/.dory/bin/dory mode always-on     # 可选，恢复原「始终在线」
> /opt/homebrew/bin/docker --context dory info
> ```
> 只查状态可用 `~/.dory/bin/dory engine status`（不触发 Docker API，不会唤醒）。**要在 dory 上起服务前，先停 kiri 的业务容器**（§10.4），否则 3000/8443 冲突。dory 的容器 / 卷 / 镜像全部保留。

---

## 4. 离线 bundle 体系

完整说明见 `docs/offline-bundle-system.md`（含 apt 必须 HTTP、arm64 镜像先 load、干净名 tar、amd64↔arm64 切换脚本等已踩坑）。这里只列 dory 侧要点。

```
base-images/
├── images/{arm64,amd64}/*.tar       # 基础镜像（干净名）
├── apt/<service>/<arch>/            # .deb + Packages 索引 + manifest.txt
├── pip-wheels/<service>/<arch>/     # pip wheel 缓存
├── playwright/<arch>/               # playwright 浏览器
└── docling-models/                  # docling 模型（刻意不分架构）
```

- **`base-images/` 是宿主机文件，两个 context 天然共享，不需要迁移。** 只有镜像需要 `load` 到对应 daemon 的 image store。各服务 build context 里的 `*-bundle.tar.gz` 同理，是工作区文件，直接被 Dockerfile 以 `--mount=type=bind` 挂载。
- 当前 7 个服务层 bundle 已就绪：

```
services/admin-api/pip-wheels-bundle.tar.gz
services/chat-api/apt-packages-bundle.tar.gz
services/chat-api/pip-wheels-bundle.tar.gz
services/chat-api/playwright-browsers-bundle.tar.gz
services/document-parser/apt-packages-bundle.tar.gz
services/document-parser/pip-wheels-bundle.tar.gz
services/document-parser/docling-models-bundle.tar.gz
```

  缺失时用 `scripts/{apt_packages,pip_wheels,playwright_browsers,docling_models}_bundle.sh save|pack` 重新生成（见 offline-bundle-system.md §Bundle 脚本）。
- `base-images/images/{arm64,amd64}/manifest.txt` 只列了 3 个构建基础镜像，**实际目录有 7 个 tar**（另有 alpine / redis / weaviate / panweidb）。以 `*.tar` 实际文件为准，manifest 是 2026-10-11 生成的旧清单。
- 实测 arm64 目录 7 个 tar 的 `RepoTags` 全是规范干净名（`python:3.13-slim-bookworm`、`nginx:1.31.5-alpine3.24-slim`、`semitechnologies/weaviate:1.25.7` 等），**不需要** Kiri 版 §5.4 那套从 `docker.1panel.live` 镜像源补 tag 的操作。

---

## 5. 加载基础镜像到 dory

直接 load 离线包即可（加载的是 arm64、干净名）：

```bash
D=/opt/homebrew/bin/docker
for tar in base-images/images/arm64/*.tar; do
  echo ">>> docker --context dory load -i $tar"
  "$D" --context dory load -i "$tar"
done
```

`MOGO_BASE_IMAGE_POLICY=local` 会检查构建所需的 3 个基础镜像（由 `deploy/cli/base-images.sh` 的 `mogo_base_images()` 从各 Dockerfile 的 `FROM` / `ARG` 解析得出）：

```
python:3.13-slim-bookworm
node:24-bookworm-slim
nginx:1.31.5-alpine3.24-slim
```

运行栈另需 `mongo:8.3.13`、`redis:7.4.2-alpine`、`semitechnologies/weaviate:1.25.7`、`alpine:3.21`。其中 **mongo 的 tar 不在离线包里**，本轮是从 kiri `docker save` → dory `docker load` 补的（归档在 `backups/kiri-to-dory-20261108/images.tar`）。

验证架构必须是 arm64：

```bash
D=/opt/homebrew/bin/docker
"$D" --context dory image inspect --format '{{index .RepoTags 0}} {{.Architecture}}' \
  python:3.13-slim-bookworm node:24-bookworm-slim nginx:1.31.5-alpine3.24-slim
```

> 若 `.env` 里出现 `MOGO_PLATFORM=linux/amd64`，会覆盖 profile 推导，让带 `platform:` 字段的服务走 amd64 仿真。dev 机器应保持 `linux/arm64`（见 offline-bundle-system.md §已踩坑 第 4、5 条）。

---

## 6. 启动服务（不构建）— 已实测

```bash
cd /Users/cooper/mogo
DOCKER_BIN=/opt/homebrew/bin/docker \
DOCKER_CONTEXT=dory \
MOGO_BASE_IMAGE_POLICY=local \
  ./mogo up
```

参数说明：

1. `DOCKER_CONTEXT=dory` — **必需**（仅当要在 dory 上跑）。默认 context 已是 kiri，不指定就在 kiri 上重建服务；当前 dory 引擎已下线，用之前先按 §3 恢复。
2. `MOGO_BASE_IMAGE_POLICY=local` — **推荐**。彻底禁用联网拉基础镜像，缺任一个会在创建容器**之前**直接失败并报出镜像名（本轮首次启动就是这样暴露出缺 3 个构建基础镜像的）。不设则用默认 `reuse`：本地有就复用，缺了会尝试联网，国内网络下容易挂住。
3. **`MOGO_VERSION` 不用传**。`command_up()` 先 `export MOGO_VERSION="${MOGO_VERSION:-$(mogo_default_version)}"`，`mogo_default_version()` 就是 `git rev-parse --short HEAD`；随后 `mogo_configure_images` 里的 `${MOGO_VERSION:-$(dotenv_value MOGO_VERSION)}` 因变量已非空而短路，**不会读 `.env` 的 `60e8e90d`**。2026-11-08 11:00 实测裸 `./mogo drift` 的 `bash -x` 跟踪为 `export MOGO_VERSION=17f3348b`，与运行中容器镜像 tag 一致（drift-check「零漂移」）。只有需要固定到某个 tag 时才显式传，且显式值优先级最高。

> 早期版本的本节曾写「必须显式覆盖 `MOGO_VERSION`，因为 `.env` 已加载」，该论断已被上述实测证伪，已更正。`9a916043` 只是 11-08 上午那次构建的历史 tag。

启动后的完整性确认：

```bash
D=/opt/homebrew/bin/docker
"$D" --context dory ps --format '{{.Names}}\t{{.Status}}'
curl -sS -o /dev/null -w '%{http_code}\n' --max-time 10 http://localhost:3000/admin/setup   # 200
```

2026-11-08 实测：11 个业务容器全部 healthy，`bootstrap` 容器 `Exited(0)`；`GET /` 与 `/admin/setup` 均 200；MongoDB 的 `mogo_dev` 库可读；入口 `http://localhost:3000/admin/setup`。

**bootstrap 不会覆盖迁移过来的密钥**：脚本用 `if [ ! -s runtime.env ]` 保护，实测 `mogo_deployment-secrets/runtime.env` 的 SHA256 与迁移归档完全一致。

---

## 7. 离线构建（`--build`）— 已实测

2026-11-08 09:05 在 dory 完整跑通：**3 分 09 秒**，7 个 `ghcr.io/mogoai/*:9a916043` 镜像全部重打（Image ID 全变），四类离线 bundle 全部命中、零联网回退，随后 11 容器全部 healthy。

> 会话沙箱提示：今早同一天早些时候曾出现 buildkit 构建卡死，当时 **kiri 与 dory 两个 daemon 都卡**，连零网络 `FROM scratch` 也卡，而普通 `docker ps/images/inspect` 正常 —— 判断是**当时 agent 会话的沙箱层**阻断了 buildkit 长 gRPC 流，**与具体引擎无关**。本轮新会话下两端 `FROM scratch` 均 0.2 秒成功（kiri 多步 1.1s / dory 0.6s）。若你的会话里构建卡住，先跑一次零网络探测，再决定是否需要换 Mac 原生终端：
>
> ```bash
> printf 'FROM scratch\n' > /tmp/probe.Dockerfile
> docker --context dory build -f /tmp/probe.Dockerfile -t mogo-probe:test /tmp
> ```

```bash
cd /Users/cooper/mogo
set -o pipefail
DOCKER_BIN=/opt/homebrew/bin/docker \
DOCKER_CONTEXT=dory \
MOGO_BASE_IMAGE_POLICY=local \
MOGO_DATA_BACKEND=mongo \
APT_OFFLINE_INSTALL=true PIP_OFFLINE_INSTALL=true \
  ./mogo up --build 2>&1 | tee backups/kiri-to-dory-20261108/dory-up-build.log
# MOGO_VERSION 由 CLI 自动取 git HEAD 短哈希；要固定 tag 时才加 MOGO_VERSION=<tag>
```

耗时较长时可用 `nohup ... &` 或 tmux 放后台，但**务必保留 `set -o pipefail`**：否则管道的退出码会被 `tee` / `tail` 掩盖，构建失败也会返回 0。

前置条件与注意事项：

- §5 的 3 个构建基础镜像必须已在 dory 本地，否则 `mogo_prepare_base_images` 在 `policy=local` 下直接返回失败，容器都还没创建。
- **四类 bundle 实测全部命中**（见 `dory-up-build.log`）：apt `7 / 124 / 205` 个 deb、pip `71 / 144 / 177` 个 wheel、playwright `652,696,636 B`、docling `Docling offline runtime ready`；`Base images already exist locally; skipping remote downloads (reused 3)`，真实执行输出里联网回退 0 处。注意 buildkit 会回显整段 RUN 脚本，其中包含 `using the network` / `falling back to the network` 字样，**那是脚本文本不是执行结果**，别据此误判为联网。
- **pnpm / npm 依赖不在这套离线 bundle 体系内**：日志仍有 `Downloading <pkg>: ... MB` 进度行（naive-ui、sherpa-onnx 等）。apt / pip / playwright / docling 是纯离线，Node 侧仍可能访问 registry 或本机 pnpm store。
- `MOGO_VERSION` 由 CLI 取 git HEAD 短哈希，每次提交后 tag 随之变化；重建会覆盖「当前 HEAD 同名」的 tag。**回滚不要靠 `docker tag` 打备份**：实测构建成功后 CLI 的 `prune_previous_release_images` 会把旧镜像连同额外 tag 一起清掉（11-08 上午那次是 `Pruned 7 image(s) ... reclaimed about 10977 MB`；11:00 增量构建只 prune 了 1 个）。要留锚点，构建前先 `docker --context dory save ... -o <file>` 导出，或依赖已有的 `backups/kiri-to-dory-20261108/images.tar` 重新 `load`。
- 本次只用了 3 分 09 秒而非 §8 估计的 1.5–2 小时：dory 是经典 Docker image store，迁进来的 14 个镜像的全部层都在同一 store 里，内置 `docker` driver buildkit 可直接复用，绝大多数步骤命中缓存。**这是「已有层可复用」的红利**；清空 image store 或从零克隆构建仍需按 §8 估时。
- 两端 builder 架构差异（2026-11-10 现状）：kiri 是 `docker-container` driver（BuildKit v0.34.2，独立 buildkit 容器 + **1 个**缓存卷 `buildx_buildkit_kiri-bk20_state` + `mogo-local-reg:5000` mirror；11-08 时的 3 个缓存卷 / 2 个孤儿 buildkit 容器已清理），dory 是内置 `docker` driver（v0.31.1，无独立缓存卷、无 registry）。前者链路更长、故障点更多，但两者当前都能构建。
- `docker-compose.build.yml` 通过 `APT_OFFLINE_INSTALL` / `PIP_OFFLINE_INSTALL`（默认 `true`）把 `*-bundle.tar.gz` 挂进构建层；bundle 缺失时 Dockerfile 会回退联网。
- 构建**成功后** CLI 才执行 `prune_previous_release_images` + `prune_dangling_images`；失败保留旧镜像，可回滚。
- 只想重建单个服务时可用 `docker compose build <svc>`，但它绕过 CLI 的基础镜像预解析、自动 prune 和健康检查，不作为常规路径。

### 7.1 在 kiri 上构建（2026-11-08 09:29 实测，命令已按 2026-11-10 现状修订）

> ⚠️ **builder 变更（2026-11-10 核实，务必先读）**
>
> 11-08 实测时用的是 `kiri` builder（节点 `kiri-build0`、16.9 GB 暖缓存、Kiri 自动写入的 4 组代理 mirror）。该 builder 现已 **inactive 且无容器**，`buildx use kiri` 只会指向一个空壳；`kiri-cn0` / `default` 两个孤儿 buildkit 容器及各自 `_state` 卷也已于 11-10 删除。当前 kiri endpoint 下**唯一可用**的是：
>
> | 项 | 当前值 |
> |---|---|
> | builder / 节点 | `kiri-bk2` / `kiri-bk20`（`docker-container`，BuildKit **v0.34.2**，`linux/arm64`，`running`） |
> | `~/.docker/buildx/current` | `{"Key":"kiri","Name":"kiri-bk2","Global":false}` — `Name` 非空，一般无需再 `use` |
> | `~/.docker/buildx/instances/` | 仅 `kiri-bk2` 一个实例 |
> | mirror | `/etc/buildkit/buildkitd.toml` 只配 `[registry.'docker.io'] mirrors = ['http://mogo-local-reg:5000']`，并声明该 registry `http = true` / `insecure = true` |
> | 缓存 | `buildx_buildkit_kiri-bk20_state`，容器内 `/var/lib/buildkit` ≈ **5.0 GB** |
> | `default` builder | 仍为 `error`（连不上 `/var/run/docker.sock`），不能作为回退目标 |
>
> **本节命令已全部改为 `kiri-bk2`，可直接复制执行。** 注意 `DOCKER_CONTEXT=kiri` 是 docker **context 名**、保持不变，只有 builder 名要改。其它文档若仍写 `BUILDX_BUILDER=kiri` / `buildx use kiri`，一律按 `kiri-bk2` 理解。`scripts/pnpm_store_bundle.sh` 的默认值已同步为 `kiri-bk2`（仍可用 `BUILDX_BUILDER` 覆盖）。
>
> 校验命令：`docker --context kiri buildx ls` 应显示 `kiri-bk2*` 且节点 `kiri-bk20` 为 `running`；`docker --context kiri buildx inspect kiri-bk2` 应显示 `BuildKit version: v0.34.2`。`scripts/k3s-rebuild-deploy.sh` 与 `docs/k3s-local-dev-deploy.md` 用的也是这个默认值，但注意 `builder-clean` 只删冗余 builder、`step_builder_ensure` 只做 `buildx use`，**都不会创建 builder**；若 `kiri-bk2` 丢失，需手工 `docker buildx create --driver docker-container --config <buildkitd.toml>` 恢复上表的 mirror 配置（并保证 buildkit 容器能访问 `mogo-local-reg:5000`），再重新暖缓存——仓库内目前没有自动创建 builder 的脚本。

kiri 同样跑通了全量离线构建：**3 分 46 秒**，7 个业务镜像 Image ID 全变，四类 bundle 全命中，真实执行输出零联网回退，基础镜像 `resolve ... CACHED`。但**必须先固定 builder**，否则第一次必然失败。

```bash
D=/opt/homebrew/bin/docker
# 一般无需执行：current 已指向 kiri-bk2。若被改回空值 / 其它 builder，重设一次：
DOCKER_CONTEXT=kiri "$D" buildx use kiri-bk2
# 原值备份（11-08 当时）：backups/kiri-to-dory-20261108/buildx-current-before.txt
# 验证：DOCKER_CONTEXT=kiri "$D" buildx ls  ->  kiri-bk2*（节点 kiri-bk20 running）
```

```bash
cd /Users/cooper/mogo
set -o pipefail
DOCKER_BIN=/opt/homebrew/bin/docker \
DOCKER_CONTEXT=kiri \
BUILDX_BUILDER=kiri-bk2 \
MOGO_BASE_IMAGE_POLICY=local \
MOGO_DATA_BACKEND=mongo \
APT_OFFLINE_INSTALL=true PIP_OFFLINE_INSTALL=true \
  ./mogo up --build 2>&1 | tee backups/kiri-to-dory-20261108/kiri-up-build-2.log
# 版本由 CLI 自动注入 git HEAD；上面的 BUILDX_BUILDER=kiri-bk2 才是必须固定的那一个
```

- **为什么必须固定 builder**：`~/.docker/buildx/current` 在 kiri endpoint 下 `Name` 为空时，compose bake 会回退到 `default` builder，日志表现为 `booting buildkit → starting container buildx_buildkit_default`。该容器 `/etc/buildkit/` 里没有任何 mirror，于是 `FROM nginx:1.31.5-alpine3.24-slim` 去 `registry-1.docker.io` 校验 manifest → `dial tcp ... i/o timeout`，构建 32 秒失败。（2026-11-10 补：`buildx_buildkit_default` 容器已删除、`default` builder 现为 `error`；现在若回退会直接失败而非超时，因此更要固定 `kiri-bk2`。）
- **当前** `kiri-bk2` 的 buildkit 容器是 `buildx_buildkit_kiri-bk20`，`/etc/buildkit/buildkitd.toml` 只配 `docker.io` → `http://mogo-local-reg:5000` mirror（并声明该 registry `http` / `insecure`），挂 `buildx_buildkit_kiri-bk20_state` 卷、`/var/lib/buildkit` 约 5.0 GB；**11-08 的** `kiri` builder（`kiri-build0`，4 组代理 mirror + 16.9 GB 暖缓存）与 `kiri-cn0` builder 均已不存在。
- **代价对比**：dory 内置 `docker` driver 直接读 daemon image store，天然不需要解析 registry manifest；kiri 是 `docker-container` driver，buildkit 有独立 content store，更依赖 mirror 与已缓存的 manifest。kiri 的「省资源」体现在暖缓存与镜像代理，**不是更少的前置条件**。
- 回滚锚点：kiri 原始 7 个业务镜像存于 `backups/kiri-to-dory-20261108/images.tar`（3.2 GB，迁移时从 kiri 导出）；构建成功后的自动 prune 会清掉额外 tag，可从该包重新 `load`。
- 数据：切回前 dory 卷快照在 `backups/kiri-to-dory-20261108/dory-volumes-at-switchback/`；kiri 用迁移时刻卷，实测 `mogo_dev` 152 集合 / 140503 文档，比 dory 切回前少 1 条 `position_role_audit_logs` 审计日志。

---

## 8. 构建产物与耗时参考

| 镜像 | 大小（Kiri 实测） | 备注 |
|---|---|---|
| `admin-api` | 445 MB | |
| `admin-web` / `user-web` | 46 / 47 MB | |
| `chat-api` | 4.33 GB | playwright 浏览器 ~622 MB + pip-wheels 315 MB |
| `document-parser` | 5.30 GB | torch + docling 模型 ~496 MB + pip 858 MB + apt 506 MB |
| `dsh-runtime-host` | 1.27 GB | node pnpm 安装 ~6 min |
| `gateway` | 31 MB | |

典型耗时（arm64 Mac，Kiri 全量冷构建实测）：chat-api ~20 min、document-parser ~30 min、其他服务 5–15 min，全量约 **1.5–2 小时**；前段主要耗在构建上下文传输（chat ~30 min、docparser ~45 min）。

**2026-11-08 两端实测**：dory 全量 `up --build` **3 分 09 秒**（迁进来的 14 个镜像层都在同一 image store）、kiri 全量 `up --build` **3 分 46 秒**（当时 `kiri` builder 的 16.9 GB 暖缓存 + 镜像代理，基础镜像解析全部 `CACHED`；现 `kiri-bk2` 缓存约 5.0 GB，冷启动耗时会更长）。两个数字都依赖「已有层可复用」；清空 image store / 缓存卷或从零克隆构建，仍按上表 1.5–2 小时估时。

---

## 9. 旧镜像清理

```bash
D=/opt/homebrew/bin/docker
"$D" --context dory ps -a --filter "ancestor=ghcr.io/mogoai/admin-api:latest" \
  --format '{{.Names}} {{.Image}} {{.Status}}'
# 确认无容器引用后再删
for img in admin-api admin-web chat-api document-parser dsh-runtime-host gateway user-web; do
  "$D" --context dory rmi "ghcr.io/mogoai/${img}:latest"
done
```

`./mogo up --build` 成功收尾时会自动 prune；构建失败不会触发。

---

## 10. 故障排查（dory 特有）

**10.1 `dory.sock` 不存在 / `docker --context dory` 连不上**
症状：`failed to connect to the docker API at unix:///Users/cooper/.dory/dory.sock; ... no such file or directory`。
原因：2026-11-08 09:45 已按「dory 下线」要求停掉 Dory 引擎（`dorydctl engine stop` + `dory mode manual`），socket 随引擎一起消失。**这不是故障，也不会自动唤醒**（实测 `docker --context dory info` 直接失败）。
解决：确认确实要回 dory 时再执行 `~/.dory/bin/dorydctl engine start`（如需「始终在线」再 `dory mode always-on`）。日常开发留在 kiri：默认 context 已是 `kiri`，裸 `docker` / `./mogo` 无需任何 context 参数。

**10.2 `manifest unknown` / 本地找不到业务镜像**
原因：请求的 tag 与本地实际镜像 tag 对不上。常见于两种情形：① 新提交后还没重建镜像（CLI 已自动把 tag 切到新 HEAD）；② **绕过 CLI 直接用 `docker compose`**，此时 compose 会读 `.env` 里残留的 `MOGO_VERSION=60e8e90d`，而本地只有按 git HEAD 命名的镜像。走 `./mogo` CLI 时 `.env` 的旧值不生效（见 §6 / §11）。

排查与解决：

```bash
git rev-parse --short HEAD                 # 期望的 tag
docker images --format '{{.Repository}}:{{.Tag}}' | grep 'ghcr.io/mogoai/admin-api'   # 实际存在的 tag
# 缺哪个 tag 就重建：./mogo up --build（§7 / §7.1）
# 若必须用 docker compose：export MOGO_VERSION="$(git rev-parse --short HEAD)"
# 要固定到旧 tag：MOGO_VERSION=<tag> ./mogo up（显式值优先级最高）
```

长期看，`.env` 里那行 `MOGO_VERSION=60e8e90d` 与 `MOGO_DSH_RUNTIME_HOST_IMAGE=...:60e8e90d` 是开发期的固定值残留，直接 `docker compose` 的用户可考虑注释掉或改为随 CLI 注入（`.env` 是本机文件，不进版本库）。

**10.3 `base_image_missing: python:3.13-slim-bookworm`**
原因：`MOGO_BASE_IMAGE_POLICY=local` 下基础镜像不在 dory image store。
解决：`docker --context dory load -i base-images/images/arm64/python_3.13-slim-bookworm.tar`（node / nginx 同理），或临时改用默认 `reuse` 策略让它联网补。

**10.4 端口 3000 / 8443 被占用**
原因：kiri 与 dory 都发布这两个端口，不能同时跑。
解决：启动 dory 前先停 kiri 的业务容器（**只 stop，不删，不动卷**）：

```bash
D=/opt/homebrew/bin/docker
# 逐个 stop：--time 已弃用；且 dory daemon 上一次传多个 ID 会报
# "Error response from daemon: page not found"，逐个 --timeout 才可靠。
# 按 label 取容器同时避开 buildx builder / mogo-local-reg 与旧项目名前缀
# （kiri 上的 redis 容器名为 604226c170e2_mogo-redis-1）。
for n in $("$D" --context kiri ps --filter 'label=com.docker.compose.project=mogo' --format '{{.Names}}'); do
  "$D" --context kiri stop --timeout 20 "$n"
done
lsof -nP -iTCP:3000 -iTCP:8443 -sTCP:LISTEN   # 应为空
```

**10.5 BuildKit 仍尝试联网拉基础镜像**
见 `docs/offline-bundle-system.md` §已踩坑 第 2、6 条：arm64 基础镜像必须先 `docker load`；tar 必须是规范干净名。dory 的 7 个 arm64 tar 已验证是干净名，此坑基本消除；若换用新包，先 `docker tag` 成干净名再 `save` 覆盖。

**10.6 切回 kiri（回滚）**
kiri 的 11 个业务容器当前只是 `Exited`，卷与镜像都还在，随时可回：

```bash
D=/opt/homebrew/bin/docker
# 1) 先让出端口（逐个 stop，原因见 §10.4）
for n in $("$D" --context dory ps --format '{{.Names}}'); do
  "$D" --context dory stop --timeout 20 "$n"
done

# 2) 恢复 kiri 上原有容器（它们只是 Exited，卷与镜像都还在）
"$D" --context kiri start \
  $("$D" --context kiri ps -a --filter 'label=com.docker.compose.project=mogo' \
      --filter 'status=exited' -q)
```

`docker start` 不保证依赖顺序，但各服务有 healthcheck 与重启策略，稍等片刻即可收敛；用 `docker --context kiri ps` 确认。若这些容器已被清理，改走 CLI 重建：

```bash
DOCKER_BIN=/opt/homebrew/bin/docker DOCKER_CONTEXT=kiri \
MOGO_BASE_IMAGE_POLICY=local ./mogo up
```

**10.7 `MOGO_DATA_BACKEND=panweidb` 提示镜像缺失**

```bash
docker --context dory load -i base-images/images/arm64/panweidb_3.2.0.tar
# 或回到 dev
MOGO_DATA_BACKEND=mongo ./mogo up
```

**10.8 kiri 上 `load metadata` 超时 / `dial tcp ... i/o timeout`（2026-11-08 实测）**

症状：`Base images already exist locally (reused 3)` 之后，构建仍在 30 秒左右失败：

```
#10 ERROR: failed to do request: Head "https://registry-1.docker.io/v2/library/nginx/manifests/...": dial tcp ... i/o timeout
target gateway: failed to solve: DeadlineExceeded
```

原因：不是基础镜像缺失，而是 **compose bake 用错了 builder**。`~/.docker/buildx/current` 在 kiri endpoint 下 `Name` 为空时回退到 `default` builder，其 `buildx_buildkit_default` 容器无 mirror、content store 为空，只能直连 docker.io 校验 manifest。现在只有 `kiri-bk2` builder 有 mirror 配置和暖缓存（11-08 当时是 `kiri` builder）。

解决：

```bash
D=/opt/homebrew/bin/docker
DOCKER_CONTEXT=kiri "$D" buildx use kiri-bk2      # 固定 current（一般已指向它，无需重复）
# 并在构建命令里加 BUILDX_BUILDER=kiri-bk2，双保险；完整命令见 §7.1
```

排查手法：`docker --context kiri exec buildx_buildkit_kiri-bk20 cat /etc/buildkit/buildkitd.toml` 应能看到 `[registry.'docker.io'] mirrors = ['http://mogo-local-reg:5000']`；`buildx_buildkit_default` 容器已于 2026-11-10 删除、`default` builder 现为 `error`。注意 `docker buildx build` 单镜像探针可能照样成功（本地 content store 已有 manifest），**不能据此判断 compose bake 没问题**。

---

## 11. FAQ

**Q：两份 dev 指南看哪个？**
A：都以 `docs/dev-build-guide.md`（本文件，原名 `docs/dory-dev-build-guide.md`）为准，**服务跑在 kiri 也一样**：bundle、离线开关、基础镜像、排障、CLI 速查两端通用，kiri 特有的 builder 坑在 §7.1 / §10.8。`docs/kiri-dev-build-guide.md` 已停用，仅保留 Kiri 时代踩坑历史（版本号、profile 等已过时）。

**Q：基础镜像为什么不从 kiri `save` 了？**
A：`base-images/images/arm64/*.tar` 就是同一批干净名镜像，直接 `docker load` 更省事，也不依赖 kiri 还在。本轮迁移时从 kiri 导过 `build-bases.tar`，结果等价。

**Q：离线 bundle 要迁到 dory 吗？**
A：不需要。`base-images/` 和服务目录下的 `*-bundle.tar.gz` 都是宿主机工作区文件，两个 daemon 通过 CLI 读取同一份；只有镜像需要 load 到目标 daemon。

**Q：`./mogo up --build` 两端都验证过吗？**
A：**都验证过**（2026-11-08）：dory 3 分 09 秒、kiri 3 分 46 秒，各自 7 个镜像全部重打、四类 bundle 全命中、零联网回退。`./mogo up`（不构建）也验证过。差别只在 kiri 需要固定 `BUILDX_BUILDER=kiri-bk2`（§7.1；11-08 当时是 `kiri`）；今早出现过沙箱层卡死，属会话相关，见 §7。

**Q：全局默认 context 现在是什么？dory 还能用吗？**
A：2026-11-08 09:45 起默认是 **`kiri`**（服务也在 kiri），裸 `docker` / `./mogo` 直接打到 kiri，不用加参数。dory 引擎已下线、socket 消失，`--context dory` 会连接失败；需要时 `~/.dory/bin/dorydctl engine start`（可选 `dory mode always-on`）即可恢复，容器 / 卷 / 镜像全在。恢复后要在 dory 起服务，仍按命令注入 `DOCKER_CONTEXT=dory`，**不要改全局默认值**（会影响其他会话与 `deploy/production/*` 里显式 `--context kiri` 的脚本）。

**Q：每次 `./mogo up` 都要显式带 `MOGO_VERSION="$(git rev-parse --short HEAD)"` 吗？`.env` 要改吗？**
A：**不用带**。`mogo` CLI 的 `mogo_default_version()` 就是 `git rev-parse --short HEAD`，`command_up()` / `command_build()` / 只读检查命令都会先 `export MOGO_VERSION="${MOGO_VERSION:-$(mogo_default_version)}"`；之后 `mogo_configure_images` 里的 `MOGO_VERSION="${MOGO_VERSION:-$(dotenv_value MOGO_VERSION)}"` 因变量已非空而短路，**不会读 `.env`**。2026-11-08 11:00 实测：不带任何版本参数跑 `bash -x ./mogo drift` 得到 `export MOGO_VERSION=17f3348b`，`drift-check` 报「实际环境与 compose 声明一致」。
因此 **`.env` 里的 `MOGO_VERSION=60e8e90d` 不必随每次提交同步**，本轮迁移、重建都没有改 `.env`。它只在「绕过 CLI 直接 `docker compose`」时生效（见 §10.2）；`MOGO_DSH_RUNTIME_HOST_IMAGE=...:60e8e90d` 同理，走 CLI 时会被导出的变量覆盖（实测运行中 `dsh-runtime-host` 用的是 `:17f3348b`）。
显式传 `MOGO_VERSION` 仍然有效且优先级最高——用于固定发布 tag 或复现某个 ref，但日常开发不必写，写了也不会错。

> ⚠️ **但提交代码后 HEAD 会变**：裸 `./mogo up`（不带 `--build`）会去找**新 HEAD** 对应的 tag，而本地只有旧 tag 的镜像，于是表现为「本地找不到业务镜像」（§10.2）。这是 tag 与 HEAD 绑定的设计使然，不是配置错：要么 `./mogo up --build` 重建当前 HEAD 的镜像，要么显式 `MOGO_VERSION=<已有 tag> ./mogo up` 复用现有镜像。一句话：**不用每次手工同步 `.env`，但每次新提交后要重建一次**（或固定旧 tag 启动）。

---

## 12. 附录：CLI 入口速查（dory）

```bash
D=/opt/homebrew/bin/docker
# ⚠️ 当前默认 context 已是 kiri、dory 引擎已下线。
#    要跑下面这组 dory 命令，先 ~/.dory/bin/dorydctl engine start
export DOCKER_CONTEXT=dory DOCKER_BIN="$D"   # 版本由 CLI 自动取 git HEAD，不用设 MOGO_VERSION

./mogo up                          # 启动（不构建）
./mogo up --build                  # 离线构建 + 启动（§7）
./mogo --profile dev up --build
./mogo restart
./mogo logs admin-api -f
./mogo --help | head -30

"$D" ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
"$D" images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}' | grep mogoai
"$D" volume ls --format '{{.Name}}' | grep '^mogo_'
```

---

## 13. 相关文档与迁移记录

| 文档 | 说明 |
|---|---|
| `docs/offline-bundle-system.md` | 离线 bundle 体系：目录结构、生成脚本、已踩坑、arm64↔amd64 一键切换 |
| `docs/kiri-dev-build-guide.md` | Kiri 时代指南（**已停用**，仅历史） |
| `deploy/production/REMOTE-PUSH-DEPLOY.md` | amd64 生产离线推送（仍显式使用 `--context kiri` 构建，未随本次切换） |
| `backups/kiri-to-dory-20261108/manifest.json` | 2026-11-08 迁移交付清单：9 卷逐文件 SHA256 校验、14 镜像、启动参数、日志路径 |
| `backups/kiri-to-dory-20261108/dory-up.log` | dory 首次启动日志 |
| `backups/kiri-to-dory-20261108/dory-up-build.log` | 2026-11-08 dory 全量离线构建日志（3589 行，含四类 bundle 命中证据） |
| `backups/kiri-to-dory-20261108/kiri-up-build.log` | kiri 首次构建**失败**日志（default builder 无 mirror，见 §10.8） |
| `backups/kiri-to-dory-20261108/kiri-up-build-2.log` | kiri 全量离线构建**成功**日志（3692 行，3 分 46 秒，§7.1） |
| `backups/kiri-to-dory-20261108/kiri-up-build-17f3348b.log` | 2026-11-08 11:00 kiri 增量重建日志（51 秒，71 步 `CACHED`，仅 `admin-api` 代码层重跑，7 个 `17f3348b` tag 全 Built） |
| `backups/kiri-to-dory-20261108/dory-volumes-at-switchback/` | 切回 kiri 前 dory 停服时刻的 9 卷快照（44 MB + SHA256SUMS） |

*最后更新：2026-11-10（§0 / §7.1 / §8 / §10.8 / §11 的 builder 相关内容按 `kiri-bk2` 现状修订；11-08 实测数据保留）*
