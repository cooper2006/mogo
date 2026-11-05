# mogo 生产环境部署：本机构建 → 远端推送（离线远端 / docker context 路线）

> 本手册固化「生产环境（离线远端服务器）镜像生成、推送、启动」的完整流程，
> 下次执行直接照本手册跑，无需重新摸索。
>
> ⚠️ **与 `README.md`（Portainer Stack 离线 tar 路线）是两套独立流程**，不要混用。
> 本路线适用：镜像在**本地 OrbStack 已构建好**，通过 **docker context over SSH**
> 把镜像直接 push 到离线远端并 `up -d`。无需走 `prepare-release.sh` 打包 tar，
> 也无需 Portainer。

---

## 0. 拓扑与适用场景

```
┌────────────────────┐         docker context over SSH        ┌───────────────────────────┐
│  本地 Mac (OrbStack) │  save | load  (镜像流)  +  scp 配置     │  生产远端 172.17.5.96:22    │
│  arm64 宿主          │ ─────────────────────────────────────▶ │  amd64 / Docker 26.1.3     │
│  构建源 = amd64 镜像 │                                         │  离线（无外网出口）          │
└────────────────────┘                                         └───────────────────────────┘
                                                                       │
                                                          ┌────────────┴────────────┐
                                                          │ 栈内：redis / weaviate   │
                                                          │ 外部：PanWeiDB           │
                                                          │   172.17.5.145:17700    │
                                                          │   (mogo / public)        │
                                                          └─────────────────────────┘
```

**何时用本路线**：远端是离线 amd64 Linux 服务器，镜像已（或将在）本地 Mac 上以
amd64 构建完成，希望一条命令把镜像推上去并拉起服务。

**不适用**：需要 Portainer 统一管理、或希望运维用 tar 包手动导入的场景 —— 那种走 `README.md`。

---

## 1. 关键连接信息（速查表）

> 凭据**不在此重复明文**。SSH 密码在 `deploy/production/remote.env`（已 `chmod 600`），
> PanWeiDB 密码在仓库根 `.env`；`deploy-remote-push.sh` 也已内置默认值，通常无需改动。

| 项 | 值 | 来源 |
| --- | --- | --- |
| 远端主机 | `172.17.5.96:22` | `remote.env` → `REMOTE_HOST` / `REMOTE_PORT` |
| 远端用户 | `bonc` | `remote.env` → `REMOTE_USER` |
| docker context 名 | `mogo-remote` | 脚本自动创建（`ssh://bonc@172.17.5.96:22`） |
| 远端部署目录（网关配置） | `/home/bonc/mogo-deploy/{docker,canary,tls}` | 脚本 `scp` 写入 |
| 外部 PanWeiDB | `172.17.5.145:17700` / user `boncuser` / db `mogo` / schema `public` | `.env` → `PANWEIDB_*` |
| 数据后端 | `panweidb`（外部），栈内 redis/weaviate 保留，mongo/panweidb 容器停用 | `docker-compose.prod-external-panweidb.yml` |
| 应用镜像（7 个） | `ghcr.io/mogoai/{chat-api,admin-api,document-parser,dsh-runtime-host,user-web,admin-web,gateway}:<版本>` | 本地构建 |
| 版本标签 | 默认 `latest`（`.env` → `MOGO_VERSION`） | — |

> 注：`document-parser` 一个镜像被 `document-api` 与 `document-worker` 两个容器共用
> （不同启动命令）。其余 6 个镜像各对应一个容器。

---

## 2. 前置条件（checklist）

- [ ] **本地 docker + compose 插件** 已安装（`docker compose version` 可用）。
- [ ] **sshpass** 已安装（`brew install hudochenkov/sshpass/sshpass` 或等价源），用于密码方式 SSH 登录远端。
- [ ] **本地 docker context `orbstack`** 指向本地构建源，且其中 7 个应用镜像为 **amd64**。
- [ ] **`base-images/` 离线依赖包已缓存**（见步骤 A），build 时离线取 apt/pip/playwright/docling。
- [ ] **`deploy/production/remote.env` 存在且 `chmod 600`**（含远端 SSH 密码）；已加 `.gitignore`，**禁止提交**。
- [ ] 仓库根 **`.env`** 关键变量就位：`MOGO_VERSION=latest`、`MOGO_DATA_BACKEND=panweidb`、`MOGO_PLATFORM=linux/amd64`、`MOGO_PULL_POLICY=never`、`PANWEIDB_*`（见 `.env`）。

> 远端 daemon 连通性、context 创建、`.env` 部署变量注入、镜像架构校验等，
> 均由 `deploy-remote-push.sh` 在运行时自动完成，无需手动预处理。

---

## 3. 步骤 A：本地 amd64 镜像构建（仅代码更新 / 缺镜像时）

> **何时需要**：① 代码有改动要上线；② 本地缺某个 `:latest` 应用镜像；③ 镜像被清掉。
> 若 7 个 `:latest` 镜像都已在本地 OrbStack 且为 amd64，**跳过本步，直接进步骤 B**。

### 3.1 离线依赖包（base-images/）

`base-images/` 里缓存的是**构建用离线包**（不是成品镜像）：
`apt/`（.deb + 索引）、`pip-wheels/`（wheel）、`playwright/`（chromium）、`docling-models/`（模型）。
由 `scripts/*_bundle.sh` 生成，build 时通过 `APT_OFFLINE_INSTALL=true` / `PIP_OFFLINE_INSTALL=true`
（默认开）引用，fallback 到国内镜像站。

> ⚠️ **易错点**：`base-images/` 不是现成镜像，应用镜像必须**从源码 build** 生成。
> 之前踩过坑：误以为 base-images 里是成品镜像直接 load 即可，结果缺失应用层、跑不起来。

### 3.2 构建命令（必须 amd64）

`docker compose build` **不支持 `--platform`** 参数，改用环境变量强制架构：

```bash
cd /Users/cooper/mogo
DOCKER_DEFAULT_PLATFORM=linux/amd64 docker --context orbstack compose \
  -f docker-compose.yml -f docker-compose.build.yml \
  --profile single-host build \
  dsh-runtime-host chat-api admin-api document-api user-web admin-web gateway
```

**要点**：
- `--context orbstack`：构建发生在本地 OrbStack（避免误用远端 context）。
- `--profile single-host`：`dsh-runtime-host` 默认带 `single-host` profile，需显式启用；其他 6 个无 profile 服务不受影响。
- 构建 6 个**服务名**即产出 7 个**镜像**：`document-api` 构建后，`document-worker` 复用同一镜像，无需单独 build。
- 架构**硬约束**：远端是 amd64，本地 Mac 是 arm64。若不用 `DOCKER_DEFAULT_PLATFORM=linux/amd64`，
  产物会变成 arm64，灌入远端后**无法运行**。务必校验（见 3.3）。

### 3.3 校验架构（推送前必做）

```bash
for img in dsh-runtime-host admin-web user-web document-parser chat-api admin-api gateway; do
  full="ghcr.io/mogoai/${img}:latest"
  arch=$(docker --context orbstack inspect --format '{{.Architecture}}' "$full" 2>/dev/null || echo MISSING)
  echo "$full -> $arch"
done
```

输出必须全是 `amd64`。`MISSING` 表示没构建，回去跑 3.2；`arm64` 表示架构错，重跑 3.2。

> 基础镜像（`alpine:3.21` / `nginx:...` / `redis:...` / `semitechnologies/weaviate:1.25.7`）
> 也需是 amd64 且为**规范名**存在于本地 orbstack。脚本 `push_image` 会在推送时校验架构，
> 非 amd64 会跳过并告警。若缺失，用 `scripts/export_base_images.sh save/load --platform linux/amd64`
> 或 `docker pull --platform linux/amd64` + 手动 retag 补齐。

---

## 4. 步骤 B：远端推送 + 启动（一条命令）

```bash
cd /Users/cooper/mogo
# 常规重部署（镜像内容未变时跳过推送；内容变了只告警）
bash deploy/production/deploy-remote-push.sh --check

# 代码有更新、需要把本地新镜像覆盖到远端同名 tag 时（关键！）
bash deploy/production/deploy-remote-push.sh --force-push --check
```

> ⚠️ **代码更新只跑不带 `--force-push` 的命令，代码不会上线**：用 `MOGO_VERSION=latest`
> 时远端早就存在同名 tag，旧版脚本直接跳过；现在改为按**镜像 ID** 比对后**只告警不推送**，
> 并打印「远端与本地内容不同但本次未推送」的镜像清单。看到该告警必须重跑 `--force-push`，
> 或改用版本化 tag（见 4.2）。2026-11-05 的时区修复部署就踩过这个坑。

### 脚本内部做了什么（按顺序）

1. **载入连接信息**：读 `remote.env`（远端 SSH 凭据、context 名）。
2. **创建/复用 docker context** `mogo-remote` → `ssh://bonc@172.17.5.96:22`；`context use` 切过去。
3. **连通性校验**：`docker --context mogo-remote ps` 探活，失败直接报错退出。
4. **注入 `.env` 部署变量**：`MOGO_PROFILE=prod`、`MOGO_PLATFORM=linux/amd64`、
   `MOGO_PULL_POLICY=never`、`MOGO_DATA_BACKEND=panweidb`、`MOGO_VERSION`、`PANWEIDB_*`、
   `MOGO_REDIS_URL` 等。这样 `up -d` 不会去 registry 拉取（离线安全）。
5. **推送镜像**（按镜像 ID 比对，不再只看 tag 是否存在）：
   - 基础镜像 4 个（alpine/nginx/redis/weaviate）、应用镜像 7 个 `:${MOGO_VERSION}`，均带**架构安全网**（非 amd64 跳过）。
   - `本地 ID == 远端 ID` → 跳过；`本地无镜像` → 告警并保留远端；`仅远端缺失` → 直接推送。
   - `两端都有但 ID 不同` → **默认只告警**（记入 stale 清单，不推送）；加 `--force-push` 才覆盖远端 tag。
   - 传输方式：≤ `PUSH_STREAM_MAX_MB`（默认 200）走 `save|load` 管道；更大的镜像走
     **本地导出 tar → scp → 远端本地 `docker load`**，并校验远端镜像 ID 与本地一致。
6. **同步网关配置到远端**：把 `deploy/docker/nginx.conf`、`deploy/canary/nginx-canary.conf`、
   `deploy/tls/*.pem` **scp** 到远端 `/home/bonc/mogo-deploy/`，并以**远端绝对路径**
   注入 `MOGO_NGINX_CONF` 等变量（覆盖 `.env` 里的相对路径，仅本次 compose 调用生效，**不污染 `.env`**）。
7. **远端启动**：`docker --context mogo-remote compose -f docker-compose.yml -f docker-compose.prod-external-panweidb.yml up -d`
   （停用 mongo/panweidb 容器，保留栈内 redis/weaviate，连外部 PanWeiDB）。
8. **`--check` 模式**：`up -d` 后轮询 `compose ps`，等待容器就绪（约 120s 上限），打印最终状态，
   并逐个校验**运行容器绑定的镜像 ID** 是否等于远端当前 tag 的 ID（防止 `up -d` 没换镜像）。
9. **部署后清理**：自动调用 `prune-old-app-images.sh` 清理远端旧版本应用镜像，只留 `:${MOGO_VERSION}`。

> **不带 `--check`**：跳过第 8 步的等待与镜像校验，推送+启动后立即返回。日常重部署建议带 `--check`。
> **`--dry-run`**：打印将执行的操作但不真正执行（不推送、不 scp、不写 `.env`、不启动、不清理），用于预演；
> 除 `--dry-run --check` 会做只读的 `compose ps` 查询外，不访问远端。
> 密码等敏感值在 dry-run 日志里以 `<hidden>` 显示。

### 4.1 镜像推送的可调参数

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `PUSH_STREAM_MAX_MB` | `200` | 镜像大于该值就改用 tar + scp + 远端 load，避免 `save|load` 长管道断裂 |
| `PUSH_TMP_DIR` | 自动 `mktemp -d` | 本地 tar 存放目录；显式指定后可跨次复用 |
| `PUSH_KEEP_TARS` | `0` | 设为 `1` 保留已导出的 tar，传输中断后重跑可直接复用（tar 文件名含镜像 ID，不会误用旧内容） |

慢链路断点续传示例（实测 VPN 仅约 0.8MB/s，4GB 镜像全量传输不现实）：

```bash
PUSH_KEEP_TARS=1 PUSH_TMP_DIR=/Users/cooper/.workbuddy/tmp/mogo-push-images \
  bash deploy/production/deploy-remote-push.sh --force-push --check
```

若链路实在太慢，可走**增量层发布**：只把改动过的文件 scp 到远端，基于远端现有镜像
`FROM ghcr.io/mogoai/<svc>:latest` + `COPY` 一层重建同名 tag，再跑不带 `--force-push` 的
`--check`（此时远端 tag 与容器一致、无需推全量镜像）。此为非标准应急路径，
网络恢复后应重灌本地标准镜像，避免远端 `:latest` 长期由补丁层构成。

> ⚠️ 采用增量层发布后，远端 `:latest` 与本地标准镜像的 **ID 会长期不一致**（功能等价但层不同），
> 每次不带 `--force-push` 的部署都会打印 stale 告警。这是**预期**行为，不要为此误跑
> `--force-push`（会触发数小时的全量传输）；链路条件好时重灌标准镜像即可消除告警。
> 可先用 `--check` 的容器镜像 ID 校验确认线上跑的就是远端当前 tag 的镜像。

### 4.2 版本化 tag（根治同名 tag 问题）

生产建议把 `.env` 的 `MOGO_VERSION` 从 `latest` 改成具体 commit tag（如 `8e17ab15`）：
每次构建新 tag → 远端本来就没有该 tag → 脚本必然推送，`up -d` 必然换镜像，不再依赖
`--force-push`，回滚也只需改回旧 tag。注意同步更新各服务的 `MOGO_*_IMAGE` 覆盖变量
与 `prune-old-app-images.sh` 的保留版本。

---

## 5. 步骤 C：验证 & 日常运维命令

所有远端命令都显式带 `--context mogo-remote`（本机 OrbStack 的 `default` context 可能被脚本切到 `mogo-remote`，显式指定最稳）：

```bash
# 服务状态（含依赖顺序）
docker --context mogo-remote compose -f docker-compose.yml -f docker-compose.prod-external-panweidb.yml ps

# 应用镜像（应只剩 :latest）
docker --context mogo-remote images --format '{{.Repository}}:{{.Tag}}' | grep 'mogoai'

# 日志
docker --context mogo-remote logs -f mogo-chat-api-1
docker --context mogo-remote compose -f docker-compose.yml -f docker-compose.prod-external-panweidb.yml logs -f

# 重启某个服务（用新镜像）
docker --context mogo-remote compose -f docker-compose.yml -f docker-compose.prod-external-panweidb.yml up -d --force-recreate chat-api

# 完整重建（改了网关配置或网络异常时用；会重建所有容器+网络，不删 volume）
docker --context mogo-remote compose -f docker-compose.yml -f docker-compose.prod-external-panweidb.yml down
MOGO_NGINX_CONF=/home/bonc/mogo-deploy/docker/nginx.conf \
MOGO_CANARY_NGINX_CONF=/home/bonc/mogo-deploy/canary/nginx-canary.conf \
MOGO_TLS_CERTS_DIR=/home/bonc/mogo-deploy/tls \
docker --context mogo-remote compose -f docker-compose.yml -f docker-compose.prod-external-panweidb.yml up -d
```

> ⚠️ **`down` 会删 compose 网络**，导致尚在运行的同栈其他容器短暂掉网。
> 若要重建，务必 `down` 紧接着 `up`，不要只 `down` 一半。

---

## 6. 步骤 D：清理旧镜像（只留最新一份）

**自动**：`deploy-remote-push.sh` 末尾已自动调用清理（远端），每次部署后只留 `:latest`。

**手动**（需要时）：

```bash
# 清理远端旧版本应用镜像（默认行为）
bash deploy/production/prune-old-app-images.sh

# 预览将删除哪些（不真正删）
bash deploy/production/prune-old-app-images.sh --dry-run

# 同时清理本地 orbstack 旧 commit tag（⚠️ 见下方注意）
bash deploy/production/prune-old-app-images.sh --local
```

`prune-old-app-images.sh` 只清理 `ghcr.io/mogoai/<7 应用>` 下 tag ≠ 当前 `MOGO_VERSION`（默认 `latest`）
的镜像；**绝不动**基础镜像、`mesc-*`、其他命名空间。被运行中容器引用的会**跳过并告警**，
被已停止容器引用的先移除容器再删 —— 不会破坏在跑服务。

> ⚠️ **`--local` 注意**：本机 OrbStack 若正跑着 dev 栈且引用了旧 tag（如 `:8e17ab15`），
> `--local` 会因"被运行容器引用"而跳过删除，实际清不掉。需先停本机 dev 栈
> （`docker compose down`）再清，或先把本机栈改用 `:latest` 重启释放引用。

---

## 7. 排错 / 踩坑记录（最重要：避免下次重蹈覆辙）

| # | 现象 | 根因 | 处理 / 现状 |
| --- | --- | --- | --- |
| 1 | 远端容器起不来，gateway 报 `failed to mount ... not a directory: directory onto file` | gateway 的 nginx 配置用**本机相对路径** `./deploy/docker/nginx.conf` 做 bind mount；远端 Linux 不存在该 Mac 路径，docker 自动建成**目录**，于是"目录挂文件"失败 | **已固化进脚本**：先 `scp` 配置到远端 `/home/bonc/mogo-deploy/`，再用**远端绝对路径**注入 `MOGO_NGINX_CONF` 覆盖 `.env` 的相对路径。不要再改回相对路径。 |
| 2 | 应用镜像灌入远端后跑不起来 / 架构不匹配 | 本地 Mac 是 arm64，未强制 amd64 构建，产物为 arm64，远端 amd64 无法运行 | **必须** `DOCKER_DEFAULT_PLATFORM=linux/amd64` 构建；脚本推送前校验架构，非 amd64 跳过。 |
| 3 | `up -d` 离线环境仍去拉镜像失败 | 未注入 `MOGO_PULL_POLICY=never` / `MOGO_PLATFORM` | 脚本已注入 `.env`；主 compose 用 `${MOGO_PULL_POLICY:-missing}` 和 `${MOGO_PLATFORM:-}` 接收。 |
| 4 | `docker compose build --platform` 报错不支持 | compose build 不支持该参数 | 改用环境变量 `DOCKER_DEFAULT_PLATFORM=linux/amd64`。 |
| 5 | 误以为 `base-images/` 是成品镜像可直接 load | 实际是离线依赖包（apt/pip/playwright/docling），应用镜像需从源码 build | 见步骤 A.1。 |
| 6 | `down` 后同栈其他容器掉网 | `down` 删除 compose 网络，引用旧网络 ID 的容器失联 | 重建必须 `down` 紧接着 `up` 一起做（见步骤 C）。 |
| 7 | 早期 `deploy-remote.sh` 报 `ref: unbound variable` | bash `set -u` 在命令替换+失败 if 后误报局部变量未绑定 | 已用 `${var:-}` 兜底修复（脚本已稳定）。 |
| 8 | `no such service: document-parser` | build 服务名是 `document-api`（`document-worker` 复用其镜像） | 构建用 `document-api`，见步骤 A.2。 |
| 9 | 部署脚本一路 `✓`、容器也 healthy，但**新代码没上线** | 旧版 `push_image` 只看远端有没有同名 tag；`:latest` 一直存在就永远跳过，本地重构建的镜像从未推送，`up -d` 自然换不了镜像 | **已修**：改为按镜像 ID 比对，内容不同默认醒目告警并列出 stale 清单；上线改动必须加 `--force-push`（或改版本化 tag，见 4.2）。`--check` 还会校验运行容器绑定的镜像 ID。回归测试见 `deploy/tests/test_deploy_push_guard.py`。 |
| 10 | 大镜像 `save\|load` 推送到一半 `broken pipe`，甚至打断 VPN | 4GB 镜像经 SSH 管道长时间传输，链路抖动即断；实测该 VPN 仅约 0.8MB/s，全量 9.6GB 需数小时 | **已修**：超过 `PUSH_STREAM_MAX_MB` 自动改 tar + scp + 远端本地 `docker load`，并校验镜像 ID；配合 `PUSH_KEEP_TARS=1` 可断点续传，或用 4.1 的增量层发布。 |

---

## 8. 关键文件清单

| 文件 | 作用 |
| --- | --- |
| `deploy/production/deploy-remote-push.sh` | **主脚本**：建 context → 按镜像 ID 比对推送（架构校验 + `--force-push` + 大镜像稳定传输）→ 同步网关配置 → 远端 `up -d` → 自动清理。 |
| `deploy/tests/test_deploy_push_guard.py` | 推送守卫回归测试：`bash -n`、`--help`、静态契约、mock 分支行为、`--dry-run` 无副作用。 |
| `deploy/production/prune-old-app-images.sh` | 旧版本清理（远端默认；`--local` 清本机；`--dry-run` 预览）。 |
| `deploy/production/remote.env` | 远端 SSH 连接信息（密码，`chmod 600`，已 gitignore）。 |
| `docker-compose.prod-external-panweidb.yml` | 覆盖文件（仓库根）：停用 mongo/panweidb，保留栈内 redis/weaviate，钉 `platform/pull_policy`。 |
| `docker-compose.build.yml` | 7 个应用的 build 上下文定义（与 `docker-compose.yml` 组合使用）。 |
| `docker-compose.yml` | 主 compose（服务定义、`pull_policy`/`platform` 变量接收）。 |
| `base-images/` | 离线依赖包缓存（apt/pip/playwright/docling）；build 时离线取用。 |
| `.env` | 仓库根部署变量（含 `PANWEIDB_*`、`MOGO_VERSION`、`MOGO_PLATFORM` 等）；已被 gitignore。 |

---

## 9. 回滚 / 完全重来

- **回滚应用版本**：把 `.env` 的 `MOGO_VERSION` 改回旧 tag，重跑步骤 B（脚本会推送旧镜像并 `up -d` 替换）。
  > ⚠️ `.env` 当前用 `latest`：同名 tag 无法区分版本，**回滚/上线都必须显式 `--force-push`**，
  > 否则远端旧镜像会一直被保留（见排错 #9）。生产强烈建议改为具体 commit tag，见 4.2。
- **完全重来**：远端 `docker --context mogo-remote compose ... down -v`（⚠️ `-v` 删 volume，会丢数据，确认备份后再用），
  再重跑步骤 B。
- **数据备份**：详见 `docs/backup-recovery.md` 与 `./mogo backup`（本路线未封装备份，需运维另配）。

---

## 10. 安全 & 注意事项

- `remote.env` 含远端 SSH 密码、`.env` 含 PanWeiDB 密码，二者均已 gitignore，**禁止提交**到仓库。
- 脚本自动把网关配置 scp 到远端 `bonc` HOME 下的 `mogo-deploy/`，请确保该目录权限合理。
- 远端是离线环境，所有镜像必须来自本地推送；不要指望 `up -d` 时联网拉取。
- 本机 OrbStack 作为构建源，可能同时跑着 dev 栈（用旧 commit tag）。清理本机旧镜像前先确认不影响本地开发（见步骤 D 注意）。
- Docker daemon 访问等同于宿主机 root，远端 `bonc` 用户需有 docker 执行权限。
