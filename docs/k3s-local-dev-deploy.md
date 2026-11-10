# k3s 本地开发部署指南

> 目的：把代码改动推到 Kiri 上的 k3s 集群（节点容器 `kiri-k8s`）跑起来做本地验证。
> **不涉及生产部署逻辑** —— `deploy/production/*` 完全不动。
> 配套脚本：`scripts/k3s-rebuild-deploy.sh`

---

## 0. 为什么需要这份指南

本地开发栈默认跑在 Docker Compose 上（`./mogo up --build`）。但有些改动需要真实集群验证：

- k8s manifests 的 YAML 改动需要真实集群验证
- 网络策略 / PVC / hostPort 等配置只能在 k3s 里看效果
- 回归测试的 A5（本体权限容器内 e2e）需要 k3s 环境

k3s 用 **containerd** 管镜像，和 Kiri 的 Docker daemon 是两套 image store，所以 `docker build` 出来的镜像 k3s 拉不到。必须走「导出 tar → 传入节点 → ctr import」的桥接路线。

另外，k3s 的 `registries.yaml` 只给 `ghcr.io` / `quay.io` / `registry.k8s.io` 配了 DaoCloud 代理，而 `ghcr.m.daocloud.io` 对 `mogoai/*` 返回 **403 白名单拒绝**、`docker.io` 也不通。因此**所有部署需要的镜像都必须在本地预导入**，不能指望 kubelet 自己去拉。

---

## 1. 架构

```
本地 Mac (docker context = kiri)
  │
  ├─ ① ./mogo up --build            构建 7 个业务镜像（tag = git short HEAD）
  ├─ ② docker save → *.tar          导出 7 个业务镜像 + 4 个基础镜像
  ├─ ③ docker cp → kiri-k8s         传 tar 进 k3s 节点容器（无需 SSH）
  ├─ ④ ctr --namespace k8s.io import 导入 containerd（边导边删 tar 降峰值）
  └─ ⑤ kubectl apply -f - + rollout restart（经 docker exec -i，走 stdin）
                                    │
k3s 节点 (kiri-k8s)                │
  └─ ⑥ 11 个 Deployment 拉起服务 + 集群内 HTTP 探测
```

> k3s 节点本身是 Kiri 上的一个 Docker 容器，`/Users`、`/Volumes` 以 bind mount 挂进去。
> 脚本不依赖这个挂载（apply 走 stdin），也不依赖 SSH 或本机 kubectl context。

### 镜像清单

| 类型 | 镜像 | tar | 大小（参考） |
|---|---|---|---|
| 业务 | `ghcr.io/mogoai/admin-api` | `admin-api.tar` | ~94 MB |
| 业务 | `ghcr.io/mogoai/chat-api` | `chat-api.tar` | ~1.0 GB |
| 业务 | `ghcr.io/mogoai/document-parser` | `document-parser.tar` | ~1.5 GB |
| 业务 | `ghcr.io/mogoai/dsh-runtime-host` | `dsh-runtime-host.tar` | ~271 MB |
| 业务 | `ghcr.io/mogoai/user-web` | `user-web.tar` | ~12 MB |
| 业务 | `ghcr.io/mogoai/admin-web` | `admin-web.tar` | ~12 MB |
| 业务 | `ghcr.io/mogoai/gateway` | `gateway.tar` | ~8.5 MB |
| 基础 | `mongo:8.3.13` | `base-mongo.tar` | ~275 MB |
| 基础 | `redis:7.4.2-alpine` | `base-redis.tar` | ~17 MB |
| 基础 | `semitechnologies/weaviate:1.25.7` | `base-weaviate.tar` | ~65 MB |
| 基础 | `alpine:3.21` | `base-alpine.tar` | ~15 MB |
| **合计** | | **11 个 tar** | **~3.3 GB** |

> `alpine:3.21` 是 `04-bootstrap-job.yaml` 里迁移 Job 的镜像，漏导会导致 bootstrap Pod `ErrImagePull`。脚本已把它纳入基础镜像清单，离线包 `BASE_BUNDLE` 里也有，会自动切出 `base-alpine.tar`。

基础镜像由 compose 拉取而非构建；本机 Docker 里没有时，脚本会自动从离线包
`backups/kiri-to-dory-20261108/images.tar` 切出 `base-*.tar`（`BASE_BUNDLE` 可覆盖）。
切出来的是标准 `manifest.json + blobs/sha256/*` 的 docker save 格式，`ctr import`
会自动把短名规范化成 `docker.io/library/mongo:8.3.13` 这类全名。

---

## 2. 前置条件

- [ ] Kiri docker context 可用（默认 `DOCKER_CTX=kiri`），builder `kiri-bk2` running
- [ ] k3s 节点容器 `kiri-k8s` 在运行，节点 `Ready` 且 `DiskPressure=False`
- [ ] 节点可用磁盘 ≥ 6 GiB（preflight 会拦截；首次全量导入建议 ≥ 15 GiB）
- [ ] containerd 里有 `rancher/mirrored-pause` 镜像（缺失则所有 Pod 起不来）
- [ ] k3s 节点上 secrets / PVC 已就位（首次部署需手动确认）
- [ ] 离线 bundle / 基础镜像 tar 或 `BASE_BUNDLE` 可用
- [ ] `python3` 可用（仅自动切分基础镜像时需要）

> 当前离线环境里的 `rancher/mirrored-pause:3.10.2` 是本地构造的替代镜像
> （`python:3.13-slim-bookworm` + `sleep infinity`），不是官方 pause 二进制。
> 只用于本地 k3s 验证，正常环境请换成官方镜像。

---

## 3. 快速上手

```bash
cd /Users/cooper/mogo

# 环境自检（建议每次先跑）
scripts/k3s-rebuild-deploy.sh preflight

# 一键全流程（含构建）
scripts/k3s-rebuild-deploy.sh all

# 已构建过、只想重推 tar（跳过 build，复用 OUTDIR 里的镜像 tar）
SKIP_BUILD=1 scripts/k3s-rebuild-deploy.sh all

# 分步执行
scripts/k3s-rebuild-deploy.sh build
scripts/k3s-rebuild-deploy.sh export
scripts/k3s-rebuild-deploy.sh scp
scripts/k3s-rebuild-deploy.sh import
scripts/k3s-rebuild-deploy.sh apply
scripts/k3s-rebuild-deploy.sh verify
scripts/k3s-rebuild-deploy.sh clean           # 清理节点上的 tar
scripts/k3s-rebuild-deploy.sh builder-clean   # 清理冗余 builder
```

`verify` 失败会返回非零退出码（rollout 未就绪 / 异常 Pod / gateway 非 2xx），可用于脚本化判定。

### Builder 重复问题（已修复）

kiri context 下曾存在 `kiri` 和 `kiri-build` 两个 buildx builder，两者指向同一个
buildkit 容器，导致 `buildx history ls` 出现重复构建记录。

**修复**：删除冗余的 `kiri-build`，新建独立 builder `kiri-bk2`；脚本默认使用它，
`builder-clean` 可清理其余 builder。

**注意**：新建的 buildkit 容器默认落在 `bridge` 网络，解析不到 `mogo-local-reg`
镜像源，构建会报 `lookup mogo-local-reg ... no such host`。需要：

```bash
docker --context kiri network connect mogo-build-net buildx_buildkit_kiri-bk20
docker --context kiri exec buildx_buildkit_kiri-bk20 sh -c 'echo "nameserver 127.0.0.11" > /etc/resolv.conf'
docker --context kiri exec buildx_buildkit_kiri-bk20 sh -c 'cat > /etc/buildkit/buildkitd.toml <<EOF
[registry]
  [registry."docker.io"]
    mirrors = ["http://mogo-local-reg:5000"]
  [registry."mogo-local-reg:5000"]
    http = true
    insecure = true
EOF'
docker --context kiri restart buildx_buildkit_kiri-bk20
```

`step_builder_ensure` 会检查网络和 DNS，不合规时打印上述修复命令。

---

## 4. 环境变量覆盖

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DOCKER_CTX` | `kiri` | Docker context 名 |
| `K3S_NODE` | `kiri-k8s` | k3s 节点容器名（`docker cp` / `exec` 目标） |
| `K3S_NS` | `mogo` | k8s namespace |
| `K3S_CTX` | `kiri-k8s` | 保留字段（当前 apply 走容器内 kubectl） |
| `IMAGE_TAG` | `git rev-parse --short HEAD` | 镜像 tag |
| `OUTDIR` | `/tmp/mogo-k3s-images` | 本地 tar 目录 |
| `REMOTE_DIR` | `/tmp/mogo-k3s-images` | 节点内 tar 目录 |
| `DOCKER_BIN` | `docker` | Docker CLI 路径 |
| `BUILDX_BUILDER` | `kiri-bk2` | BuildKit builder |
| `BASE_BUNDLE` | `backups/kiri-to-dory-20261108/images.tar` | 基础镜像离线包 |
| `SKIP_BUILD` | `0` | `all` 跳过 build，复用已有 tar |
| `FORCE_EXPORT` | `0` | 强制重新 `docker save` / 重新切分基础镜像 |
| `KEEP_TARS` | `0` | import 后保留节点 tar（默认边导边删） |
| `VERIFY_TIMEOUT` | `120` | 每个 deployment 的 rollout 等待秒数 |

---

## 5. 每一步详解

### preflight — 环境自检

检查节点容器状态、节点 Ready、可用磁盘（< 6 GiB 直接失败；重复导入同名 tag 会复用已有 blob，稳态 6–7 GiB 可用即够）、DiskPressure、
pause 镜像、11 个 tar 是否齐备。磁盘不足先清：

```bash
docker --context kiri builder prune --force     # 构建缓存，本次释放 5.3 GB
docker --context kiri system prune --force
docker --context kiri exec kiri-k8s rm -f /tmp/mogo-k3s-images/*.tar
```

### Step 1 — 构建

复用 `./mogo up --build`（compose bake + 离线 bundle），以 git short HEAD 为 tag
构建 7 个业务镜像，并逐个校验镜像存在。

### Step 2 — 导出

```bash
docker save ghcr.io/mogoai/chat-api:3ec08f99 -o /tmp/mogo-k3s-images/chat-api.tar
```

已存在的 tar 会跳过（`FORCE_EXPORT=1` 强制重导）。基础镜像若本机 Docker 里没有，
自动从 `BASE_BUNDLE` 切分。

### Step 3 — 传输

`docker cp` 逐个传入节点容器，按文件大小比对决定是否跳过（可续传）。
不再使用 SSH / scp —— k3s 节点容器里没有 sshd。

### Step 4 — 导入

```bash
ctr --namespace k8s.io image import /tmp/mogo-k3s-images/chat-api.tar
```

导入成功后**立即删除该 tar**，避免 3.3 GB tar 与解压后的镜像同时占满磁盘。
`KEEP_TARS=1` 可保留。

### Step 5 — Apply

脚本只在 tag 变化时用 `sed -E -i.bak` 精确替换
`ghcr.io/mogoai/<svc>:<old>` → 新 tag（兼容 GNU / BSD sed），然后按依赖顺序走 stdin apply：

```
00-namespace → 01-pvc → 02-configmaps → 03-secrets → 04-bootstrap-job → 05-services → 06-deployments
```

**关键点**：同名同 tag 重新导入镜像不会改变 Deployment spec，`kubectl apply` 不会触发
重建，旧 Pod（尤其 `ImagePullBackOff`）会一直卡着。所以脚本在 apply 后对所有
Deployment 执行 `rollout restart`。

### Step 6 — 验证

- 列出 Pod
- 对 11 个 Deployment 逐个 `rollout status`
- 检查非 `Running` / `Completed` 的 Pod
- **集群内** HTTP 探测：从 `kubectl get svc gateway` 取 ClusterIP，用节点内的 `wget`
  请求 `/admin/setup`，要求 2xx

> 集群内探测是权威判据（不依赖宿主机转发链路）。脚本另外会对宿主入口
> `localhost:3000` 做一次探测，失败只告警、不影响退出码。

**宿主机访问入口**：`localhost:3000` → `mogo-gateway-relay`（L4 nginx stream）
→ `kiri-k8s:<hostPort 3000>` → gateway Pod `:80`。relay 配置在
`deploy/k8s/relay/nginx-stream.conf`（只读 bind mount），upstream 用 Docker
内嵌 DNS 动态解析容器名 `kiri-k8s`，**不要写死 IP**。详见第 6、7 节。

---

## 6. 已知问题

| 问题 | 说明 |
|---|---|
| 磁盘压力 | 节点是 63 GB 的 Kiri 虚拟盘，导入全量镜像后约 90% 占用。先 `builder prune` 腾空间，否则会被 kubelet 打上 `DiskPressure` 污点并驱逐 Pod |
| pause 镜像 | containerd 缺 `rancher/mirrored-pause:3.10.2` 时所有 Pod 无法创建沙箱；当前用本地替代镜像，preflight 会告警 |
| 镜像源 403 | `ghcr.m.daocloud.io` 拒绝 `mogoai/*`，`docker.io` 也不通；**必须全量导入 11 个镜像**（7 业务 + 4 基础），缺一个对应 Pod 就 `ImagePullBackOff` |
| 基础镜像易漏 | 只导入 7 个业务镜像时，mongo/redis/weaviate 三个 Pod 必然起不来；脚本已把它们 + `alpine:3.21` 纳入清单 |
| 首次部署 secrets | `03-secrets.yaml` 是未跟踪的本地产物，引用的 Secret 需提前创建，否则 Pod 起不来。脚本现已容错：本地缺文件但集群已有 secret 时，自动从集群 re-export 并 apply；集群也无才报错 |
| PVC 数据 | `01-pvc.yaml` 用 `local-path` storageClass，数据在节点本地磁盘 |
| hostPort 端口冲突 | gateway 用 hostPort 3000/8443，节点上已有服务占用需先停 |
| bootstrap job | 是 Job，`apply` 对已完成的 job 显示 unchanged，不会重跑；需要重跑得先 delete |
| 不要手写 containerd mirror | 曾在 `config-v3.toml.d/` 下写过错误的 mirror 配置导致 k3s 启动失败，需挂载 volume 删除后才恢复。镜像请一律走本脚本的 tar 导入 |
| relay upstream 不能写死 IP | `mogo-gateway-relay` 曾硬编码 `172.17.0.4`，k3s 容器重启后 IP 变成 `172.17.0.2`，`localhost:3000` 直接 `ERR_EMPTY_RESPONSE`。现已改为 `resolver 127.0.0.11` + 变量式 `proxy_pass kiri-k8s:3000` 动态解析 |
| relay 必须接入 `mogo-build-net` | 容器名解析只在 user-defined network 生效。`docker network connect` 是**运行时状态**，relay 容器重建后会丢，需重新执行 `docker --context kiri network connect mogo-build-net mogo-gateway-relay` |
| 8443 HTTPS 暂不可用 | Deployment 声明了 `containerPort 443` / `hostPort 8443`，但 `gateway-nginx` ConfigMap 目前只有 `listen 80`，Pod 内无 443 监听，转发会 `Connection refused`。等 gateway 启用 TLS server 后自动生效 |

---

## 7. 故障排查

| 症状 | 可能原因 | 处理 |
|---|---|---|
| `./mogo up --build` 报 `lookup mogo-local-reg ... no such host` | 新建 buildkit 容器没接 `mogo-build-net` / DNS 不对 | 见第 3 节 builder 修复命令 |
| `buildx history` 记录重复 | 多个 builder 指向同一 buildkit daemon | `scripts/k3s-rebuild-deploy.sh builder-clean` |
| Pod `ImagePullBackOff` + 403 白名单 | 镜像没导入 containerd | `ctr --namespace k8s.io image ls` 核对 11 个镜像（含 `docker.io/library/alpine:3.21`）；重跑 `import` + `apply` |
| Pod `Pending` / `Evicted` | 节点 DiskPressure | `df -h` / `kubectl describe node`；清 tar、prune 构建缓存，再 `kubectl delete pods --field-selector status.phase=Evicted` |
| Pod 卡在 `ContainerCreating` | pause 镜像缺失 | 确认 `rancher/mirrored-pause:3.10.2` 在 containerd 中 |
| apply 后镜像没更新 | 同名同 tag 不触发滚动 | 脚本已自动 `rollout restart`；手动可 `kubectl rollout restart deployment/<name> -n mogo` |
| `localhost:3000/admin/` 报 `ERR_EMPTY_RESPONSE` | relay 的 L4 upstream 连不上 k3s 节点（先查 `docker --context kiri logs mogo-gateway-relay`，典型是硬编码 IP 失效 / relay 掉出 `mogo-build-net`） | 确认 `deploy/k8s/relay/nginx-stream.conf` 用的是动态 DNS；`docker --context kiri network connect mogo-build-net mogo-gateway-relay`；`docker --context kiri exec mogo-gateway-relay nginx -s reload` |
| `curl localhost:3000` 空回复但集群内 200 | 只坏在宿主机转发链路 | 集群内 `kubectl get svc -n mogo gateway` 取 ClusterIP 用 `wget` 复核；按上一条修 relay |
| `node free space < 6 GiB` | preflight 保护性拦截 | 先清磁盘再重跑 |

---

## 8. 验证记录

**2026-11-10**：`SKIP_BUILD=1 scripts/k3s-rebuild-deploy.sh all` 全流程执行成功（退出码 0）：

- preflight：节点 Ready、17 GiB 可用、pause 镜像存在、10 个 tar 齐备
- export（复用 tar）→ scp（10 个，3.3 GB）→ import（10 个镜像全部 saved，tar 即时删除）
- apply：7 个 manifest 通过 stdin apply，`03-secrets` 更新，其余 unchanged；11 个 Deployment 重启
- verify：11/11 Deployment Ready、11/11 Pod `1/1 Running`、gateway `HTTP 200`、无 DiskPressure
- 单独重跑 `verify` 亦通过

**同日追加：修复 `http://localhost:3000/admin/` 的 `ERR_EMPTY_RESPONSE`**

- 根因：relay 的 `nginx-stream.conf` 把 3000/8443 硬编码转发到 `172.17.0.4`，
  但 k3s 容器重启后 IP 变成 `172.17.0.2`；日志刷 `connect() failed (113) Host is unreachable`，
  L4 转发建连失败直接断开客户端 → 浏览器空响应。
- 修复：`deploy/k8s/relay/nginx-stream.conf` 改为 `resolver 127.0.0.11 valid=10s`
  + 变量式 `proxy_pass`（`kiri-k8s:3000` / `kiri-k8s:8443`），并把 relay 接入
  `mogo-build-net`；`nginx -t` 通过、reload 生效，配置改的是仓库文件（只读 bind mount），可持久化。
- 结果：`localhost:3000/admin/` → **200**（admin-web index.html，850 B），
  `/`、`/admin/setup` 均 200；带本机代理的 curl 也 200。
- 8443 仍 `Connection refused`：gateway ConfigMap 只有 `listen 80`，Pod 内无 443 监听，
  属既有状态，非本次引入；已在配置注释和「已知问题」中标注。
- 脚本补强：`preflight` 检查 relay 是否在 `mogo-build-net`（缺失打印修复命令），
  `verify` 增加宿主入口探测（仅告警，不影响退出码）。

**同日追加：修复脚本三处「干净重跑必卡」缺陷（已写入 `scripts/k3s-rebuild-deploy.sh`）**

1. **bootstrap 镜像漏处理**：原 10 镜像清单只含 mongo/redis/weaviate，漏了 `04-bootstrap-job.yaml` 用的 `alpine:3.21` → bootstrap Pod `ErrImagePull`。已把 `alpine:3.21` 加入 `BASE_IMAGES`/`BASE_NAMES`，`split_base_bundle` 的 `WANTED` 表同步加入，离线包里已有，自动切 `base-alpine.tar` 并导入。全部计数改为 `${#TAR_SPECS[@]}` 动态，不再写死 10。
2. **SKIP_BUILD=1 的 tag 不一致**：`IMAGE_TAG` 原永远取 git HEAD，但离线重部署复用的是旧 commit 打的 tar → apply 用新 tag、containerd 只有旧 tag → `ImagePullBackOff`。现逻辑：未显式指定 `IMAGE_TAG` 且 `SKIP_BUILD=1` 时，从 `06-deployments.yaml` 现有 tag 反推，保证 apply/import 与磁盘 tar 一致；显式传 `IMAGE_TAG=xxx` 仍优先。
3. **`03-secrets.yaml` 硬依赖**：脚本原对该文件 `die` 中断。现逻辑：本地缺失但集群已有 secret → 自动从集群 re-export 写回本地并 apply（幂等）；集群也无 → 才报错指引创建。

> 修复后一条 `SKIP_BUILD=1 scripts/k3s-rebuild-deploy.sh all`（含缺 `03-secrets.yaml`、镜像 tag 与 tar 不一致场景）可干净跑过，无需手动补丁。

---

*最后更新：2026-11-10*
