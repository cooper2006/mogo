# k3s 本地开发部署指南

> 目的：把代码改动推到 Kiri 上的 k3s 集群（节点 `kiri-k8s`）跑起来做本地验证。
> **不涉及生产部署逻辑** —— `deploy/production/*` 完全不动。
> 配套脚本：`scripts/k3s-rebuild-deploy.sh`

---

## 0. 为什么需要这份指南

本地开发栈默认跑在 Docker Compose 上（`./mogo up --build`，11 个容器）。但有时需要把服务推到 k3s 集群里验证：

- k8s manifests 的 YAML 改动需要真实集群验证
- 网络策略 / PVC / hostPort 等配置只能在 k3s 里看效果
- 回归测试的 A5（本体权限容器内 e2e）需要 k3s 环境

k3s 用 **containerd** 管镜像，和 Kiri 的 Docker daemon 是两套 image store，所以 `docker build` 出来的镜像 k3s 拉不到。必须走「导出 tar → 传入节点 → ctr import」的桥接路线。

---

## 1. 架构

```
本地 Mac (Kiri Docker context)
  │
  ├─ ① ./mogo up --build          构建 7 个业务镜像（tag = git HEAD）
  ├─ ② docker save → .tar         导出镜像
  ├─ ③ scp → k3s 节点             传文件
  └─ ④ ctr import                 导入 k3s containerd
                                    │
k3s 节点 (kiri-k8s)                │
  └─ ⑤ kubectl apply -f           拉起服务（更新镜像 tag）
```

### 镜像清单

| 服务 | 镜像 | 大小（参考） |
|---|---|---|
| admin-api | `ghcr.io/mogoai/admin-api` | ~445 MB |
| chat-api | `ghcr.io/mogoai/chat-api` | ~4.3 GB |
| document-parser | `ghcr.io/mogoai/document-parser` | ~5.3 GB |
| dsh-runtime-host | `ghcr.io/mogoai/dsh-runtime-host` | ~1.3 GB |
| admin-web | `ghcr.io/mogoai/admin-web` | ~46 MB |
| user-web | `ghcr.io/mogoai/user-web` | ~47 MB |
| gateway | `ghcr.io/mogoai/gateway` | ~31 MB |
| **合计** | | **~12 GB** |

---

## 2. 前置条件

- [ ] Kiri docker context 可用，builder `kiri-bk2` running（首次需 `scripts/k3s-rebuild-deploy.sh builder-clean` 确保唯一）
- [ ] 离线 bundle 就绪（`base-images/` + 各服务 `*-bundle.tar.gz`）
- [ ] k3s 节点可通过 SSH 访问（默认 `bonc@kiri-k8s`，密钥 `~/.ssh/id_ed25519`）
- [ ] k3s 节点磁盘空间 ≥ 15 GB
- [ ] k3s 节点上 secrets / PVC 已就位（首次部署需手动确认）
- [ ] kubectl context `kiri-k8s` 可用

---

## 3. 快速上手

```bash
cd /Users/cooper/mogo

# 一键全流程
scripts/k3s-rebuild-deploy.sh all

# 或者分步执行：
scripts/k3s-rebuild-deploy.sh build          # ① 构建
scripts/k3s-rebuild-deploy.sh export         # ② 导出 tar
scripts/k3s-rebuild-deploy.sh scp            # ③ 传到 k3s 节点
scripts/k3s-rebuild-deploy.sh import         # ④ 导入 containerd
scripts/k3s-rebuild-deploy.sh apply          # ⑤ 更新 manifests + apply
scripts/k3s-rebuild-deploy.sh verify         # ⑥ 验证
scripts/k3s-rebuild-deploy.sh clean          # 清理节点上的 tar
scripts/k3s-rebuild-deploy.sh builder-clean  # 清理冗余 builder
```

### Builder 重复问题（已修复）

kiri docker context 下曾存在 `kiri` 和 `kiri-build` 两个 buildx builder，
两者指向同一个 buildkit 容器，导致 `buildx history ls` 出现重复构建记录。

**根因**：两个 builder 实例共享同一个 BuildKit daemon，每次构建在历史中产生两份记录。

**修复**：
- 删除了冗余的 `kiri-build` builder
- 新建独立 builder `kiri-bk2`（当前唯一运行中的 builder）
- 脚本默认 `BUILDX_BUILDER=kiri-bk2`，并提供 `builder-clean` 子命令清理冗余

```bash
# 清理冗余 builder，确保始终只有一个在运行
scripts/k3s-rebuild-deploy.sh builder-clean
```

---

## 4. 环境变量覆盖

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SSH_USER` | `bonc` | k3s 节点 SSH 用户 |
| `SSH_HOST` | `kiri-k8s` | k3s 节点 hostname |
| `SSH_PORT` | `22` | SSH 端口 |
| `SSH_KEY` | `~/.ssh/id_ed25519` | SSH 私钥路径 |
| `K3S_NS` | `mogo` | k3s namespace |
| `K3S_CTX` | `kiri-k8s` | kubectl context 名 |
| `IMAGE_TAG` | `git rev-parse --short HEAD` | 镜像 tag |
| `OUTDIR` | `/tmp/mogo-k3s-images` | 本地 tar 输出目录 |
| `REMOTE_DIR` | `/tmp/mogo-k3s-images` | 远端 tar 存放目录 |
| `DOCKER_BIN` | `docker` | Docker CLI 路径 |
| `BUILDX_BUILDER` | `kiri-bk2` | BuildKit builder（默认独立 builder，避免重复历史） |

---

## 5. 每一步详解

### Step 1 — 构建

复用现有的 `./mogo up --build` 流程（compose bake + 离线 bundle），自动以 `git rev-parse --short HEAD` 为 tag 构建 7 个业务镜像。

脚本自动调用 `step_builder_ensure` 确保 builder 唯一且就绪，默认使用 `kiri-bk2`。

### Step 2 — 导出

```bash
docker save ghcr.io/mogoai/chat-api:7b3261aa -o /tmp/mogo-k3s-images/chat-api.tar
```

大文件（chat-api / document-parser / dsh-runtime-host）导出耗时较长，建议单独跑。

### Step 3 — 传输

用 `scp -i` 逐个传到 k3s 节点。脚本已加 `ConnectTimeout` / `TCPKeepAlive` / `StrictHostKeyChecking=no` 防止超时断连。

大文件如果传输中断，脚本会跳过已存在的文件，重跑即可续传。

### Step 4 — 导入 containerd

k3s 的 containerd namespace 是 `k8s.io`，导入命令：

```bash
ctr --namespace k8s.io image import /tmp/mogo-k3s-images/chat-api.tar
```

注意：`ctr` 不是 `docker load`，镜像名会保留 `ghcr.io/mogoai/...` 前缀。

### Step 5 — Apply

脚本自动检测当前 manifests 里的镜像 tag，如果和 `IMAGE_TAG` 不一致就用 `sed` 替换，然后按依赖顺序 apply：

```
00-namespace → 01-pvc → 03-secrets → 04-bootstrap-job → 05-services → 06-deployments
```

### Step 6 — 验证

```bash
kubectl --context kiri-k8s get pods -n mogo
kubectl --context kiri-k8s rollout status deployment/gateway -n mogo
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:3000/admin/setup
```

---

## 6. 已知问题

| 问题 | 说明 |
|---|---|
| 首次部署 secrets 未就位 | `03-secrets.yaml` 引用的 Secret 需提前创建（密钥、证书等），否则 apply 后 pod 起不来 |
| PVC 数据 | `01-pvc.yaml` 用 `local-path` storageClass，数据在节点本地磁盘。首次无 PVC 时需确认 storageClass 是否可用 |
| hostPort 端口冲突 | gateway 用 hostPort 3000/8443，如果节点上已有服务占用需先停 |
| bootstrap job 冲突 | `04-bootstrap-job.yaml` 是 Job，重复 apply 会因 job 名称已存在而失败。首次跑完后，后续部署建议跳过或先 delete 旧 job |
| 镜像清理 | 导入完记得删节点上的 tar 文件释放磁盘 |

---

## 7. 故障排查

| 症状 | 可能原因 | 处理 |
|---|---|---|
| `./mogo up --build` 失败 | builder 未固定 | `docker --context kiri buildx use kiri` |
| scp 传输中断 | 大文件 + 网络不稳定 | 脚本自动跳过已传文件，重跑续传 |
| `ctr import` 失败 | 磁盘不足 | `df -h` 检查 k3s 节点剩余空间 |
| pod CrashLoopBackOff | 镜像 tag 不匹配 | 检查 `kubectl describe pod` 里的镜像名 |
| apply 后服务不响应 | bootstrap job 未跑或 secrets 缺失 | 检查 job 状态和 pod 日志 |

---

*最后更新：2026-11-09*