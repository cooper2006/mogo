# 生产部署（Portainer Stack，无外网）

面向**无外网的生产环境**：镜像靠离线导入，栈用 Portainer 的 Stack 拉起。
目标主机为「无外网 + x86_64 + Docker 26.1.3」的 Linux 服务器（部署时替换为实际主机名），
Portainer CE 2.21.0 位于 `http://<PORTAINER_HOST>:<PORTAINER_PORT>`。

主机侧完全无法出网（github.com、registry-1.docker.io、各镜像站、内网 artifactory 与 DNS 全部不通），
所以**镜像必须在本机交叉构建、打包成 tar，再离线导入**。

## 一条命令产出发布包

```bash
cd deploy/production
./prepare-release.sh                 # 版本号自动取 git short hash
./prepare-release.sh --skip-build    # 复用本地已有镜像，只打包
nohup ./prepare-release.sh > /tmp/prepare-release.log 2>&1 &   # 建议后台跑（构建 1h+）
```

`./prepare-release.sh -h` 看全部选项。脚本按顺序做九件事：

1. **确定版本号** —— `git rev-parse --short HEAD`（也可显式传 TAG，但会警告与 commit 不一致）；
   同时记录完整 commit / 分支 / 提交标题，并在工作区不干净时警告
   （若改动落在 `services/`、`apps/`、`deploy/docker/` 会直接影响镜像内容，会重点提醒）
2. 前置检查（docker、python3、`.env` 里的 `*_IMAGE` 污染）
3. 固定 compose 变量（见下方"两个必须屏蔽的坑"）
4. 从 `docker-compose.yml` 推导出镜像清单，自动区分应用镜像与基础镜像
5. 交叉构建 7 个应用镜像
6. 校验应用镜像架构必须是 amd64
7. 生成基础镜像的 amd64 变体（buildx staging）
8. 打包成 4 个 tar
9. 渲染 Stack 清单 + 校验镜像包 + 生成部署单

产出目录 `prod-images-<TAG>/`（已 gitignore）：

| 文件 | 说明 |
| --- | --- |
| `01-base.tar` … `04-document-parser.tar` | 4 个镜像包，按先小后大排列 |
| `docker-compose.portainer.yml` | 已渲染（含 tag/commit 来源标注）、可直接上传的 Stack 清单 |
| `DEPLOY.md` | **自包含的部署单**：实测体积、sha256、导入顺序、Stack 步骤、验证命令 |
| `bundle.json` | 元数据：tag / commit / 分支 / 各包体积与 sha256 |

把这个目录整体交给运维即可。**具体的操作步骤看 `DEPLOY.md`**，它每次随发布重新生成，
带的是当次的真实体积与 sha256，不需要在这里重复维护。

## 目录内各文件

| 文件 | 作用 |
| --- | --- |
| `prepare-release.sh` | 主脚本，一条命令产出整个发布包 |
| `docker-compose.portainer.yml.tpl` | Stack 清单**模板**（`__MOGO_TAG__` 为版本占位符，不能直接上传） |
| `merge_images.py` | 把多个镜像合并成一个 tar，并按映射改写 `RepoTags` |
| `verify_bundle.py` | 校验镜像包：标签、架构、层数一致性，算 sha256 |
| `render_deploy_doc.py` | 由 `bundle.json` 生成 `DEPLOY.md` |

## 为什么清单要单独做一份

仓库根目录的 `docker-compose.yml` 直接丢进 Portainer Stack 会踩三个坑：

| 问题 | 根因 | 本清单的处理 |
| --- | --- | --- |
| gateway 起不来 | `./deploy/docker/nginx.conf` 是**相对路径** bind mount，Portainer 会把它解析到自己的 stack 目录，文件必然不存在 | 把 nginx.conf 以 base64 放进 `MOGO_GATEWAY_NGINX_CONF_B64`，容器启动时解码落盘 |
| nginx 配置被破坏 | compose 会对 `$VAR` 做插值，而 nginx 配置里全是 `$http_upgrade` / `$connection_upgrade` | 同上：base64 规避插值 |
| 启动即报拉取失败 | 生产无外网，`${MOGO_VERSION}` 之类未定义变量会被插值成空串，镜像名不成立 | 所有 `${VAR}` 已解析为字面量，镜像名写死，并加 `pull_policy: never` |

另外省略了 `runtime-pool` profile 下的 `dsh-runtime-host-1/2/3` 与 `dsh-runtime-host-lb`
（默认不启动，且 LB 依赖 `nginx` 基础镜像，生产上不需要）；去掉了顶层 `name:`，
项目名由 Portainer 的 Stack 名决定。

> 已验证：Portainer 的 **Docker Standalone** Stack 走 Docker Compose，支持
> `depends_on` 健康条件、YAML 锚点与 `x-` 扩展字段（Swarm 栈才不支持）。

## 需要导入的 11 个镜像

| 镜像 | 用途 |
| --- | --- |
| `alpine:3.21` | bootstrap（生成密钥后退出，一次性） |
| `mongo:6.0.20` | 数据库 |
| `redis:7.4.2-alpine` | 缓存 / 队列 |
| `semitechnologies/weaviate:1.25.7` | 向量库 |
| `ghcr.io/himovo/chat-api:<TAG>` | 用户侧 API |
| `ghcr.io/himovo/admin-api:<TAG>` | 管理侧 API |
| `ghcr.io/himovo/document-parser:<TAG>` | 文档解析（`document-api` 与 `document-worker` 共用） |
| `ghcr.io/himovo/dsh-runtime-host:<TAG>` | Agent 运行时 |
| `ghcr.io/himovo/user-web:<TAG>` | 用户前端 |
| `ghcr.io/himovo/admin-web:<TAG>` | 管理前端 |
| `ghcr.io/himovo/gateway:<TAG>` | 网关（nginx） |

全部为 `linux/amd64`，由 arm64 Mac 交叉构建后导出。

## 两个必须屏蔽的坑

**1. 仓库根 `.env` 会污染构建产物名。** `.env` 被 compose 自动加载，里面的
`MOVO_CHAT_API_IMAGE=chat-api:92a0c98` 这类覆盖会让镜像被打成别的名字
（实测踩过）。脚本的做法是显式导出 `MOGO_*_IMAGE`——shell 环境优先于 `.env`，
所以无需你去改 `.env`。

**2. `docker pull --platform` / `docker save --platform` 在 OrbStack 上不可靠。**
前者对平台选择是**空操作**（拉下来仍是宿主平台）；后者在本地只有 arm64 内容时会报
`no suitable export target found`。可靠路径是 **buildx staging 构建**
（`FROM <镜像站>/<image>` + `--platform linux/amd64 --load`），脚本里已封装。

## 已知限制

- **无外网**：在线模型、外部搜索源、文档解析的外部依赖均不可用。
- **打包耗时**：交叉构建实测 1 小时以上，瓶颈是外网带宽（约 0.1～1 MB/s，
  两个大镜像并发构建时会互相抢占）。
- **`document-parser` 包最大**（约 2GB），网页上传耗时最长。
- **端口**：gateway 占用宿主 `3000`。
- **架构**：所有产物均为 amd64，不要导回 arm64 机器使用。
