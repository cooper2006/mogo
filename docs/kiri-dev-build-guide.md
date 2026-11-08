# Kiri 开发环境：离线加速构建与重启服务

> **已停用 / 仅作历史（2026-11-08 起）**
> 2026-11-08 曾迁移到 **Dory** context（9 个 `mogo_*` 数据卷 + 14 个镜像），当天 09:33 又按「复用 16.9 GB 暖 buildx 缓存 + 镜像代理」的判断**切回 kiri 运行**；dory 的容器与卷保留可回滚。两端都能用同一套离线 bundle 完成全量构建。
> 现行指南仍是 **[`docs/dev-build-guide.md`](dev-build-guide.md)**：kiri 上的构建见其 §7.1（必须固定 `BUILDX_BUILDER=kiri`）、对应排障见 §10.8。本文件仅保留 Kiri 时代的踩坑记录，命令与版本基线已过时，不要照抄。
> 离线 bundle 体系另见 [`docs/offline-bundle-system.md`](offline-bundle-system.md)。
> 本文件保留 Kiri 时代的构建踩坑记录（1panel 镜像源补 tag、BuildKit 元数据、context 误用等），但其中的命令**不要在 dory 上照抄**。当前全局默认 context 已改回 `kiri`（裸 `docker` / `./mogo` 直接可用）；dory 引擎已下线，要操作 dory 须先 `~/.dory/bin/dorydctl engine start` 并显式 `--context dory`。
> 迁移明细：`backups/kiri-to-dory-20261108/manifest.json`。

> 历史状态：已落地（2026-11-05 实测通过）
> 历史版本基线：`5b039422`（含 test profile 外部 PanWeiDB 支持、check_external_db.sh 修复）
> 历史执行入口：`./mogo up --build`（需先切换 docker context 到 Kiri）

本文档记录 **Kiri 本地开发栈**的"离线加速构建 → 重启服务"完整流程与踩坑要点。面向在大陆内网/离线环境下跑 mogo 自托管开发环境的工程师。

---

## 1. 目标服务与架构

| 类别 | 服务 | 镜像 | 端口/入口 |
|---|---|---|---|
| API | `admin-api` | `ghcr.io/mogoai/admin-api` | 内部 |
| API | `chat-api` | `ghcr.io/mogoai/chat-api` | 内部 |
| API | `document-api` / `document-worker` | `ghcr.io/mogoai/document-parser`（同镜像，不同 CMD） | 内部 |
| Runtime | `dsh-runtime-host` | `ghcr.io/mogoai/dsh-runtime-host` | 内部 |
| Web | `admin-web` | `ghcr.io/mogoai/admin-web` | 内部 |
| Web | `user-web` | `ghcr.io/mogoai/user-web` | 内部 |
| Gateway | `gateway` | `ghcr.io/mogoai/gateway` | `localhost:3000` |
| DB (dev) | `mongo` | `mongo:8.3.13` | 栈内 |
| DB (test) | `panweidb` | `panweidb:3.2.0` | 栈内（需 docker load） |
| Cache | `redis` | `redis:7.4.2-alpine` | 栈内 |
| Vector | `weaviate` | `semitechnologies/weaviate:1.25.7` | 栈内 |

所有业务镜像以短哈希为 tag（`ghcr.io/mogoai/<svc>:<commit>`），**与 git HEAD 绑定**。

---

## 2. Profile 体系（关键前置）

`deploy/cli/env-profiles.sh` 维护三套 profile，由 `./mogo --profile <name>` 或 `MOGO_DATA_BACKEND` 触发。

| Profile | `MOGO_DATA_BACKEND` | `MOGO_PLATFORM` | 数据后端 | 用途 |
|---|---|---|---|---|
| `dev` | `mongo` | `linux/arm64` | 栈内 mongo | 本地开发 |
| `test` | `panweidb` | `linux/arm64` | 栈内/外部 panweidb | 本地演练（外部 PanWeiDB 需 MOGO_USE_EXTERNAL_DB=1） |
| `prod` | `panweidb`（外部） | `linux/amd64` | 外部 PanWeiDB | 生产部署 |

**推断优先级**（无 `--profile` 时）：
1. `MOGO_USE_EXTERNAL_DB=1` → prod
2. `MOGO_DATA_BACKEND=panweidb` → test
3. 其余 → dev

**⚠️ 默认 .env 是 `MOGO_DATA_BACKEND=panweidb`（test profile）**，但本地 `base-images/images/arm64/panweidb_3.2.0.tar` 通常未加载。**跑 dev 时必须显式覆盖**（见 §5）。

---

## 3. 前置检查清单

```bash
cd /path/to/mogo

# 1) docker context 必须是 Kiri（本脚本走 unix socket，不是 ssh）
docker context show          # 期望：kiri
docker context ls            # 看到 * 在 kiri 行

# 2) MOGO_VERSION 默认会读 git short hash（mogo_default_version），
#    可显式覆盖：export MOGO_VERSION=<hash>
git log -1 --format='%h %s'  # 确认 HEAD

# 3) 离线 bundle 必须存在（base-images/images/arm64/*.tar）
ls base-images/images/arm64/ | wc -l   # 期望 7 个
```

常见 context 陷阱：

```bash
# 错误示例（mogo-remote 是 ssh://bonc@172.17.5.96 远端，非本地）
docker context show
# → mogo-remote   ⚠️ 这是另一套部署的主机

# 切回 Kiri
docker context use kiri
docker context show   # → kiri  ✓
```

---

## 4. 从零开始：首次拉取 bundle → 加载基础镜像 → 构建

以下面向**全新克隆仓库**或**`base-images/` 清空后**的完整链路。后续重建只需跳至 §6。

### 4.1 前置：获取离线 bundle

Bundle 来自仓库外的离线交付（U 盘、内网共享、CI 归档）。按来源分两类：

#### A. 完整 bundle（含 base-images/images + apt/pip-wheels/playwright/docling cache）

```bash
# 假设 bundle 已解压到 ~/Downloads/mogo-bundle-arm64/
# 1) 基础镜像 tar
rsync -a --ignore-existing ~/Downloads/mogo-bundle-arm64/images/arm64/ \
    base-images/images/arm64/

# 2) APT 包缓存（document-parser 最大，chat-api 次之，dsh-runtime-host 最小）
rsync -a --ignore-existing ~/Downloads/mogo-bundle-arm64/apt/ \
    base-images/apt/

# 3) pip wheel 缓存（document-parser 858MB，chat-api 315MB，admin-api 60MB）
rsync -a --ignore-existing ~/Downloads/mogo-bundle-arm64/pip-wheels/ \
    base-images/pip-wheels/

# 4) Playwright 浏览器（仅 chat-api 用）
rsync -a --ignore-existing ~/Downloads/mogo-bundle-arm64/playwright/ \
    base-images/playwright/

# 5) Docling 模型（仅 document-parser 用）
rsync -a --ignore-existing ~/Downloads/mogo-bundle-arm64/docling-models/ \
    base-images/docling-models/

echo "=== bundle 完整性校验 ==="
echo "base-images 总大小:" && du -sh base-images/
echo "基础镜像数量:" && ls base-images/images/arm64/*.tar 2>/dev/null | wc -l
echo "APT cache:" && ls base-images/apt/document-parser/arm64/*.deb 2>/dev/null | wc -l
```

#### B. 只有 base-images/images（无应用层包缓存）

部分交付只包含基础 OS 镜像，应用层 bundle（apt/pip-wheels/playwright/docling）需从已构建镜像提取或在线下载。**先走 §4.2 加载基础镜像，再执行 §4.3 的 bundle 生成步骤。**

### 4.2 加载基础镜像到 Kiri

**必须用 Kiri context**（当前激活的可能是 `mogo-remote`）：

```bash
cd /path/to/mogo
docker context use kiri
docker context show   # 确认返回 kiri
```

**第一步：从 tar 加载原始镜像**（arm64 Mac 本地栈用 arm64）：

```bash
for tar in base-images/images/arm64/*.tar; do
  echo ">>> docker load $tar"
  docker load -i "$tar"
done
```

**第二步：补规范名 tag（BuildKit 必须命中规范名，否则仍会联网重解析）**：

```bash
# 找出镜像源 ID（1panel 代理已拉过的那份，带完整 manifest 元数据）
PY_ID=$(docker image inspect docker.1panel.live/library/python:3.13-slim-bookworm \
          --format '{{.Id}}' 2>/dev/null | cut -c1-12)
NODE_ID=$(docker image inspect docker.1panel.live/library/node:24-bookworm-slim \
            --format '{{.Id}}' 2>/dev/null | cut -c1-12)
NGINX_ID=$(docker image inspect docker.1panel.live/library/nginx:1.31.5-alpine3.24-slim \
             --format '{{.Id}}' 2>/dev/null | cut -c1-12)

[[ -n "$PY_ID" ]] || { echo "ERROR: python 镜像源不存在"; exit 1; }
[[ -n "$NODE_ID" ]] || { echo "ERROR: node 镜像源不存在"; exit 1; }
[[ -n "$NGINX_ID" ]] || { echo "ERROR: nginx 镜像源不存在"; exit 1; }

echo "python -> $PY_ID"
echo "node   -> $NODE_ID"
echo "nginx  -> $NGINX_ID"

# 挂规范名
docker tag "docker.1panel.live/library/python:3.13-slim-bookworm" \
           python:3.13-slim-bookworm
docker tag "docker.1panel.live/library/python:3.13-slim-bookworm" \
           docker.io/library/python:3.13-slim-bookworm
docker tag "docker.1panel.live/library/node:24-bookworm-slim" \
           node:24-bookworm-slim
docker tag "docker.1panel.live/library/node:24-bookworm-slim" \
           docker.io/library/node:24-bookworm-slim
docker tag "docker.1panel.live/library/nginx:1.31.5-alpine3.24-slim" \
           nginx:1.31.5-alpine3.24-slim
docker tag "docker.1panel.live/library/nginx:1.31.5-alpine3.24-slim" \
           docker.io/library/nginx:1.31.5-alpine3.24-slim

# 验证：规范名必须指向镜像源 ID
for img in python:3.13-slim-bookworm node:24-bookworm-slim nginx:1.31.5-alpine3.24-slim; do
  got=$(docker image inspect "$img" --format '{{.Id}}' 2>/dev/null | cut -c1-12)
  case "$img" in
    python*) expected="$PY_ID" ;;
    node*)   expected="$NODE_ID" ;;
    nginx*)  expected="$NGINX_ID" ;;
  esac
  if [[ "$got" == "$expected" ]]; then
    echo "✓ $img -> $got"
  else
    echo "✗ $img -> $got (期望 $expected)"
    exit 1
  fi
done
echo "基础镜像补 tag 完成"
```

**附加依赖镜像**（mongo/redis/weaviate 通常由 compose pull 自动拉；离线交付有 tar 时手动加载）：

```bash
# 若 bundle 包含这三者
[ -f base-images/images/arm64/mongo_8.3.13.tar ] && docker load -i base-images/images/arm64/mongo_8.3.13.tar
[ -f base-images/images/arm64/redis_7.4.2-alpine.tar ] && docker load -i base-images/images/arm64/redis_7.4.2-alpine.tar
[ -f base-images/images/arm64/semitechnologies_weaviate_1.25.7.tar ] && docker load -i base-images/images/arm64/semitechnologies_weaviate_1.25.7.tar
```

### 4.3 生成服务层 bundle（仅缺时执行）

下面脚本把"base-images/ 的原始缓存"打包到各服务的 build context，供 Dockerfile 的 `COPY` 层使用。**首次运行 + bundle 丢失时需执行；已有 bundle 可跳过。**

#### 4.3.1 APT 包 bundle（每个服务独立）

```bash
# 用法：
scripts/apt_packages_bundle.sh save document-parser chat-api dsh-runtime-host
# 等价于先 fetch（从 base-images/apt/ 读 .deb）再 pack（产出 apt-packages-bundle.tar.gz 到各服务 build context）
# 仅 arm64：ARCH_LIST=arm64 scripts/apt_packages_bundle.sh save document-parser chat-api dsh-runtime-host
```

#### 4.3.2 pip wheel bundle（每个服务独立）

```bash
scripts/pip_wheels_bundle.sh save document-parser chat-api admin-api
# 等价于 fetch（从 base-images/pip-wheels/ 读 .whl）+ pack（产出 pip-wheels-bundle.tar.gz 到各服务 build context）
```

#### 4.3.3 Playwright 浏览器 bundle（仅 chat-api）

```bash
# playwright 是从已构建镜像提取（base-images/playwright/ 已存在时直接 pack；否则需先构建 chat-api）
scripts/playwright_browsers_bundle.sh list   # 看 base-images/playwright/ 缓存状态
scripts/playwright_browsers_bundle.sh pack   # 从缓存打包（若缓存存在）
# 若无缓存，需先构建一次 chat-api，再：
scripts/playwright_browsers_bundle.sh save ghcr.io/mogoai/chat-api:<version>
```

#### 4.3.4 Docling 模型 bundle（仅 document-parser）

```bash
scripts/docling_models_bundle.sh list   # 看 base-images/docling-models/ 缓存状态
scripts/docling_models_bundle.sh pack   # 从缓存打包
# 若无缓存，需先构建一次 document-parser，再：
scripts/docling_models_bundle.sh save ghcr.io/mogoai/document-parser:<version>
```

### 4.4 验证 bundle 就绪

```bash
echo "=== 基础镜像 ==="
for img in python:3.13-slim-bookworm node:24-bookworm-slim nginx:1.31.5-alpine3.24-slim; do
  echo -n "$img -> "; docker image inspect "$img" --format '{{.Id}}' 2>/dev/null | cut -c1-12 || echo MISSING
done

echo "=== 服务层 bundle ==="
for f in \
  services/admin-api/pip-wheels-bundle.tar.gz \
  services/chat-api/pip-wheels-bundle.tar.gz \
  services/chat-api/apt-packages-bundle.tar.gz \
  services/chat-api/dsh/runtime-host/apt-packages-bundle.tar.gz \
  services/chat-api/playwright-browsers-bundle.tar.gz \
  services/document-parser/pip-wheels-bundle.tar.gz \
  services/document-parser/apt-packages-bundle.tar.gz \
  services/document-parser/docling-models-bundle.tar.gz; do
  if [[ -f "$f" ]]; then
    echo "✓ $f ($(du -sh "$f" | cut -f1))"
  else
    echo "✗ MISSING: $f"
  fi
done
```

预期全部 ✓，无 MISSING。

### 4.5 执行构建

```bash
export MOGO_VERSION="$(git rev-parse --short HEAD)"
export MOGO_DATA_BACKEND=mongo           # dev profile（覆盖 .env 的 panweidb）
nohup ./mogo up --build > /tmp/mogo-up-build.log 2>&1 &
echo "PID=$!"
tail -f /tmp/mogo-up-build.log           # 实时查看进度
```

构建成功后自动 prune 旧镜像并打印健康状态。详见 §6。

---

## 5. 基础镜像管理（离线关键）

### 5.1 参与构建的基础镜像

```
python:3.13-slim-bookworm       # admin-api / chat-api / document-parser 公共
node:24-bookworm-slim           # user-web / admin-web / dsh-runtime-host
nginx:1.31.5-alpine3.24-slim    # gateway
```

### 5.2 本地已有的镜像源名称（1panel 代理）

```bash
docker images | grep -E 'python|node:24|nginx:1.31.5'
# 可能只看到：
# docker.1panel.live/library/python:3.13-slim-bookworm
# docker.1panel.live/library/node:24-bookworm-slim
# docker.1panel.live/library/nginx:1.31.5-alpine3.24-slim
```

### 5.3 离线 tar 来源（权威）

```bash
base-images/images/arm64/
├── python_3.13-slim-bookworm.tar      (46M)
├── node_24-bookworm-slim.tar          (79M)
├── nginx_1.31.5-alpine3.24-slim.tar   (9M)
├── redis_7.4.2-alpine.tar             (17M)
├── semitechnologies_weaviate_1.25.7.tar (65M)
├── alpine_3.21.tar                    (3.9M)
└── panweidb_3.2.0.tar                 (1.4G)   # 仅 test/prod
```

### 5.4 BuildKit 元数据坑（踩过的最贵一笔）

直接用 tar 加载的镜像 **会触发 BuildKit 联网重解析 manifest** → 外网被拦 → 构建失败：

```bash
# ❌ 错误：从 tar 直接加载（缺 pull-through 元数据）
docker load -i base-images/images/arm64/python_3.13-slim-bookworm.tar
docker images | grep python        # ID 不同于镜像源
```

正确做法——**用镜像源 ID 补规范名 tag**（保留完整 manifest 元数据）：

```bash
# ✅ 正确：把带元数据的镜像源 ID 挂到规范名上
docker tag docker.1panel.live/library/python:3.13-slim-bookworm python:3.13-slim-bookworm
docker tag docker.1panel.live/library/node:24-bookworm-slim     node:24-bookworm-slim
docker tag docker.1panel.live/library/nginx:1.31.5-alpine3.24-slim nginx:1.31.5-alpine3.24-slim
# 同时挂 docker.io/library/ 前缀（部分 build 场景需要）
docker tag docker.1panel.live/library/python:3.13-slim-bookworm docker.io/library/python:3.13-slim-bookworm
docker tag docker.1panel.live/library/node:24-bookworm-slim     docker.io/library/node:24-bookworm-slim
docker tag docker.1panel.live/library/nginx:1.31.5-alpine3.24-slim docker.io/library/nginx:1.31.5-alpine3.24-slim
```

验证：

```bash
for img in python:3.13-slim-bookworm node:24-bookworm-slim nginx:1.31.5-alpine3.24-slim; do
  echo -n "$img -> "; docker image inspect "$img" --format '{{.Id}}' 2>/dev/null || echo MISSING
done
# 全部应输出相同 ID（即 docker.1panel.live 源的那份）
```

### 5.5 MOGO_BASE_IMAGE_MIRROR 未设时的回退

未设时 CLI 回退 Docker Hub 直连，中国大陆普遍被拦。两种解法：
1. 补规范名 tag（本文推荐的 §5.4 做法）；
2. 或 `export MOGO_BASE_IMAGE_MIRROR=docker.m.daocloud.io`（走另一缓存）。

---

## 6. 构建命令

### 6.1 标准流程（dev profile / mongo）

```bash
cd /path/to/mogo
docker context use kiri                              # 切回本地
MOGO_VERSION="$(git rev-parse --short HEAD)"             # 显式固化（也可不写，由 CLI 自动取 short hash）
MOGO_DATA_BACKEND=mongo                                  # 覆盖 .env 的 panweidb，强制走 dev profile
./mogo up --build                                        # 离线构建 + 启动
```

**等价单行**：

```bash
cd /Users/cooper/mogo && MOGO_VERSION=8e17ab15 MOGO_DATA_BACKEND=mongo ./mogo up --build
```

### 6.2 MOGO_VERSION 来源

```bash
# mogo_default_version() 的逻辑
git -C "${ROOT_DIR}" rev-parse --short HEAD 2>/dev/null || printf 'latest'
# 未设置时默认 = HEAD 短 hash（8 位）
# 显式 env 覆盖优先级最高
```

### 6.3 构建产物大小参考

| 镜像 | 大小 | 备注 |
|---|---|---|
| `admin-api` | 445 MB | |
| `admin-web` | 46 MB | |
| `user-web` | 47 MB | |
| `chat-api` | 4.33 GB | playwright 浏览器 ~622MB + pip-wheels 315MB |
| `document-parser` | 5.30 GB | torch + docling 模型 ~496MB + pip 858MB + apt 506MB |
| `dsh-runtime-host` | 1.27 GB | node pnpm 安装耗时 ~6 min |
| `gateway` | 31 MB | |

---


### 6.4 使用外部 PanWeiDB（test profile）

当 `.env` 已配置外部 PanWeiDB（`PANWEIDB_HOST=172.17.5.145`），可通过设置 `MOGO_USE_EXTERNAL_DB=1` 停用栈内数据库容器：

```bash
# .env 配置（已注释 MongoDB URI）
MOGO_DATA_BACKEND=panweidb
MOGO_USE_EXTERNAL_DB=1
PANWEIDB_HOST=172.17.5.145
PANWEIDB_PORT=17700
PANWEIDB_USER=boncuser
PANWEIDB_PASSWORD=...
PANWEIDB_DB=mogo
PANWEIDB_SCHEMA=public

# 启动（自动使用 test profile）
./mogo --profile test up --build
```

**注意**：`check_external_db.sh` 会根据 `MOGO_DATA_BACKEND` 选择检查：
- `panweidb` 后端 → 只检查 `PANWEIDB_HOST`，跳过 MongoDB 检查
- `mongo` 后端 → 只检查 `MOGO_MONGODB_URI`

服务状态：
- 应用服务（8个）+ redis + weaviate = 10 个 healthy
- 若使用栈内 panweidb：+ panweidb 容器 = 11 个 healthy
- 若使用外部 panweidb：- mongo/panweidb 容器（被 external compose 排除）


## 7. 构建过程与耗时

### 7.1 关键步骤（后台输出顺序）

```
[1/5] 下载 APT 离线包   ... (apt 镜像)
[2/5] 下载 npm 离线包   ... (node_modules)
[3/5] 下载 pip 离线包   ... (pip wheel 闭包)
[4/5] 下载 playwright   ... (~622MB)
[5/5] 下载测试闭包      ... (pytest 等，B 方案)
基础镜像本地命中...     (0 联网)
=> 依次构建：admin-web → chat-api → document-api → gateway → admin-api → user-web → dsh-runtime-host
```

### 7.2 耗时分布（arm64 Mac）

| 阶段 | 典型耗时 |
|---|---|
| APT/npm/pip/playwright 传输 | 视上下文大小，chat ~30 min、docparser ~45 min |
| chat-api 实际构建 | ~20 min |
| document-parser 实际构建 | ~30 min（torch + docling 解包最重） |
| 其他服务 | 5–15 min |
| **全量合计** | **约 1.5–2 小时** |

### 7.3 后台运行建议

```bash
# 用 nohup 或 tmux/screen，避免终端断开导致 SIGTERM
MOGO_VERSION=$(git rev-parse --short HEAD) MOGO_DATA_BACKEND=mongo ./mogo up --build > /tmp/mogo-up-build.log 2>&1 &
# 查看进度
tail -f /tmp/mogo-up-build.log
```

---

## 8. 旧镜像清理

`./mogo up --build` 在**启动成功后**自动调用 `prune_previous_release_images` + `prune_dangling_images`，把未引用的旧镜像层一并清理。这是"构建完成后"才做的，**构建失败不会触发**——因为要保回滚能力。

手动清理残留（如 `:latest`）：

```bash
docker --context kiri ps -a --filter "ancestor=ghcr.io/mogoai/admin-api:latest" --format '{{.Names}} {{.Image}} {{.Status}}'
# 确认无容器引用后
for img in admin-api admin-web chat-api document-parser dsh-runtime-host gateway user-web; do
  docker --context kiri rmi "ghcr.io/mogoai/${img}:latest"
done
```

---

## 9. 健康确认

```bash
docker --context kiri ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | grep -E 'mogo-'
```

期望输出（8 个业务服务 + 3 个依赖，共 11 容器，全部 healthy）：

```
mogo-admin-api-1          ghcr.io/mogoai/admin-api:8e17ab15   Up 17 hours (healthy)
mogo-admin-web-1          ghcr.io/mogoai/admin-web:8e17ab15   Up 17 hours (healthy)
mogo-chat-api-1           ghcr.io/mogoai/chat-api:8e17ab15    Up 17 hours (healthy)
mogo-document-api-1       ghcr.io/mogoai/document-parser:8e17ab15   Up 17 hours (healthy)
mogo-document-worker-1    ghcr.io/mogoai/document-parser:8e17ab15   Up 17 hours (healthy)
mogo-dsh-runtime-host-1   ghcr.io/mogoai/dsh-runtime-host:8e17ab15  Up 17 hours (healthy)
mogo-gateway-1            ghcr.io/mogoai/gateway:8e17ab15     Up 17 hours (healthy)
mogo-user-web-1           ghcr.io/mogoai/user-web:8e17ab15    Up 17 hours (healthy)
mogo-mongo-1              mongo:8.3.13                        Up 43 hours (healthy)
mogo-redis-1              <sha>                                Up 43 hours (healthy)
mogo-weaviate-1           <sha>                                Up 43 hours (healthy)
```

入口：`http://localhost:3000/admin/setup`

---

## 10. 故障排查速查

### 10.1 admin-api 启动即 crash：`got '%+'`

**症状**：日志出现 `got '%+'`，SQL 里 `LIKE '%+00:00'` 裸 `%` 被 psycopg 当占位符。

**根因**：旧镜像 `pg_compat.py` 里的写法未替换掉 `LIKE '%+00:00'`。

**解决**：重建镜像即可（工作区代码已改为 `right(...)`），`./mogo up --build` 自动带入新代码。

### 10.2 BuildKit 仍尝试联网拉取基础镜像

**症状**：即便本地有镜像，build log 仍出现 `pulling from docker.io/library/python...` 并超时。

**原因**：本地只有镜像源 tag（`docker.1panel.live/...`），缺规范名 tag（`python:3.13-slim-bookworm`）。

**解决**：按 §5.4 补 tag，并确认规范名指向带完整 manifest 元数据的镜像源 ID。

### 10.3 `MOGO_DATA_BACKEND=panweidb` 提示镜像缺失

**症状**：
```
Error: MOGO_DATA_BACKEND=panweidb enables the PanWeiDB backend, but image panweidb:3.2.0 is not present locally.
```

**解决**：
```bash
# 加载离线 bundle
docker load -i base-images/images/arm64/panweidb_3.2.0.tar
# 或改用 dev profile
MOGO_DATA_BACKEND=mongo ./mogo up --build
```

### 10.4 外部 PanWeiDB 连接检查失败（MongoDB URI 未配置）

**症状**：
```
[FAIL] MongoDB(MOGO_MONGODB_URI): 连接信息未配置
```

**原因**：使用 PanWeiDB 后端时，`.env` 中 `MOGO_MONGODB_URI` 被注释掉，但 check 脚本仍尝试检查。

**解决**：脚本已修复（`5b039422`），根据 `MOGO_DATA_BACKEND` 智能选择检查项。若使用旧版本，手动注释 `.env` 中的 MongoDB URI。

### 10.5 构建发到远端而非 Kiri

**症状**：
```
Error: MOGO_DATA_BACKEND=panweidb enables the PanWeiDB backend, but image panweidb:3.2.0 is not present locally.
```

**解决**：
```bash
# 加载离线 bundle
docker load -i base-images/images/arm64/panweidb_3.2.0.tar
# 或改用 dev profile
MOGO_DATA_BACKEND=mongo ./mogo up --build
```

### 10.6 构建发到远端而非 Kiri

**症状**：上下文传输速率只有 ~0.8 MB/s（走 SSH），日志里出现 `ssh -l bonc -p 22 -- 172.17.5.96`。

**原因**：当前 docker context 是 `mogo-remote`（远端 172.17.5.96），不是 Kiri。

**解决**：
```bash
docker context use kiri
docker context show    # 确认返回 kiri
```

---

## 11. 常见问题 FAQ

**Q：能否跳过离线 bundle 直接联网构建？**
A：可以，但国内连 Docker Hub / PyPI / npm 都很慢且不稳定。建议始终准备 `base-images/` 离线 bundle，设置 `APT_OFFLINE_INSTALL=true PIP_OFFLINE_INSTALL=true`。

**Q：`MOGO_VERSION` 不传会怎样？**
A：CLI 会自动取 `git rev-parse --short HEAD`（8 位）。显式传则优先使用。不传时 tag 可能是 `latest`（旧行为，已废弃）。

**Q：构建中途失败会回滚吗？**
A：`./mogo up --build` 失败时**不会**删除旧镜像（保留回滚能力）。手动 `prune_dangling_images` 才会清理未引用层。

**Q：`docker compose build` vs `./mogo up --build` 差异？**
A：CLI 额外做了：① 自动 pre-resolve 基础镜像；② 自动 prune；③ 自动 health check + 打印初始化地址。不建议直接跑 `docker compose build`。

---

## 12. 附录：关键 CLI 入口

```bash
# 查看 profile
./mogo --help | head -30

# 强制 dev（mongo）
./mogo --profile dev up --build

# 强制 test（panweidb）
./mogo --profile test up --build

# 指定版本标签
MOGO_VERSION=v0.2.6 ./mogo --profile dev up --build

# 查看已建镜像
docker --context kiri images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}' | grep mogoai

# 重启服务（不重建）
./mogo restart

# 查看服务日志
./mogo logs admin-api -f
```

---

*最后更新：2026-11-05*

---

## 附录 B：架构说明 (arm64 vs amd64)

### 当前环境架构

| 环境 | 架构 | Docker Context | 用途 |
|------|------|----------------|------|
| **Kiri** (本地开发) | arm64 | `kiri` | 本地开发、测试 |
| **172.17.5.96** (远程生产) | amd64 | `mogo-remote` | 生产部署 |

### 关键注意

1. **基础镜像必须匹配架构**：
   - arm64 使用 `base-images/images/arm64/` 下的 tar
   - amd64 使用 `base-images/images/amd64/` 下的 tar
   - 加载命令：`docker load -i base-images/images/<arch>/python_3.13-slim-bookworm.tar`

2. **Bundle 架构**：
   - `pip-wheels-bundle.tar.gz` 包含 `arm64/` 和 `amd64/` 两个目录
   - 构建时通过 `TARGETARCH` 自动选择对应架构
   - 确认 bundle 与目标架构一致

3. **Context 切换**：
   ```bash
   # 切换到 arm64 本地开发
   docker context use kiri
   
   # 切换到 amd64 远程生产
   docker context use mogo-remote
   ```

4. **文档对应**：
   - `docs/kiri-dev-build-guide.md` → arm64 架构操作指南
   - `docs/REMOTE-PUSH-DEPLOY.md` → amd64 架构部署指南

---

## 附录 A：架构说明 (arm64 vs amd64)

### 当前环境架构

| 环境 | 架构 | Docker Context | 用途 |
|------|------|----------------|------|
| **Kiri** (本地开发) | arm64 | `kiri` | 本地开发、测试 |
| **172.17.5.96** (远程生产) | amd64 | `mogo-remote` | 生产部署 |

### 关键注意

1. **基础镜像必须匹配架构**：
   - arm64 使用 `base-images/images/arm64/` 下的 tar
   - amd64 使用 `base-images/images/amd64/` 下的 tar
   - 加载命令：`docker load -i base-images/images/<arch>/python_3.13-slim-bookworm.tar`

2. **Bundle 架构**：
   - `pip-wheels-bundle.tar.gz` 包含 `arm64/` 和 `amd64/` 两个目录
   - 构建时通过 `TARGETARCH` 自动选择对应架构
   - 确认 bundle 与目标架构一致

3. **Context 切换**：
   ```bash
   # 切换到 arm64 本地开发
   docker context use kiri
   
   # 切换到 amd64 远程生产
   docker context use mogo-remote
   ```

4. **文档对应**：
   - `docs/kiri-dev-build-guide.md` → arm64 架构操作指南
   - `deploy/production/REMOTE-PUSH-DEPLOY.md` → amd64 架构部署指南
