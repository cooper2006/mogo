# 待确认：陈旧的基础镜像 tar 归档

**日期**：2026-10-10
**状态**：**已处理完毕**（2026-10-10 用户确认后执行，见下方「处置结果」）
**来源**：三类缓存审计时发现（用户确认清理 `base-images/manifest.txt` 陈旧条目时一并整理）

## 背景

`base-images/` 是「外部下载内容本地缓存」目录，整体被 `.gitignore` 的 `/base-images/` 忽略，
下面所有文件**均未被 git 跟踪**，属本地构建产物。

2026-10-08 的 commit `d6c4982` 统一了 node / nginx 版本（node:20 → node:24、
nginx:1.29.8 → 1.31.5），当时删除了对应镜像 tag，但**未同步清理本目录的 tar 归档**，
也**未更新 manifest.txt**（本次已按官方机制重新生成）。

## 待确认项

| 文件 | 大小 | 内含镜像 | 状态判定 |
|---|---|---|---|
| `base-images/node_20-slim.tar` | 71M | `node:20-slim` | **陈旧**：Dockerfile 已全部改用 node:24-bookworm-slim |
| `base-images/nginx_1.29.8-alpine.tar` | 26M | `nginx:1.29.8-alpine` | **陈旧**：Dockerfile 已全部改用 nginx:1.31.5-alpine3.24-slim |

**合计约 97MB。**

判定依据：
- `scripts/export_base_images.sh list` 从 Dockerfile 扫描出的当前需求只有 4 个：
  `python:3.13-slim-bookworm`、`node:24-bookworm-slim`、`python:3.10-slim-bookworm`、
  `nginx:1.31.5-alpine3.24-slim`。
- 两个陈旧镜像在上表中均**不在**该清单内。
- `docs/WORK_LOG.md` 2026-10-08 条目已记录这两个版本被统一替换并删除 tag。

## 另发现：缺少 python:3.13 的归档

`base-images/` 下有 `python_3.10-slim-bookworm.tar`，但**没有** `python_3.13-slim-bookworm.tar`，
而 `services/chat-api/Dockerfile` 与 `services/admin-api/Dockerfile` 都以它为 `ARG BASE_IMAGE`。

旧 `manifest.txt` 也**漏列**了 `python:3.13-slim-bookworm`（本次已补齐）。
若某次离线部署依赖这份 tar 集合，chat-api / admin-api 的基础镜像会缺失。
建议补导出：

```bash
scripts/export_base_images.sh save base-images
```

（该命令按 Dockerfile 自动发现，会同时补齐缺失项并重写 manifest。）

## 处置建议

按 `AGENTS.md`「禁止删除任何文件；需要移除时移入待确认清单」，此处**未删除**上述两个 tar。

需要用户确认后二选一：
1. **删除**这两个陈旧 tar（约 97MB），并补导出 `python:3.13-slim-bookworm.tar`；
2. **保留**，仅在后续 `export_base_images.sh save` 时自然覆盖。

注：即使保留也不影响构建——`save` 每次都会按 Dockerfile 重新发现集合，
陈旧 tar 只是占地方，不会被 `load` 用于当前版本。

---

## 处置结果（2026-10-10 执行）

用户确认选择**方案 1**，已执行完毕：

1. **删除**陈旧归档（删除前已核验绝对路径与内含镜像）：
   - `base-images/node_20-slim.tar`（71M，内含 `node:20-slim`）
   - `base-images/nginx_1.29.8-alpine.tar`（26M，内含 `nginx:1.29.8-alpine`）
2. **补导出**缺失的 `base-images/python_3.13-slim-bookworm.tar`（46M）：
   ```bash
   scripts/export_base_images.sh save base-images
   ```

**最终状态**：`base-images/` 现有 4 个 tar，与 `manifest.txt` 完全一致：

| 归档 | 大小 | 镜像 |
|---|---|---|
| `python_3.13-slim-bookworm.tar` | 46M | `python:3.13-slim-bookworm` |
| `node_24-bookworm-slim.tar` | 79M | `node:24-bookworm-slim` |
| `python_3.10-slim-bookworm.tar` | 47M | `python:3.10-slim-bookworm` |
| `nginx_1.31.5-alpine3.24-slim.tar` | 9.0M | `nginx:1.31.5-alpine3.24-slim` |

### 附带记录：`load` 的单平台语义

验证 `load` 路径时确认（并已实测复现）：**单平台归档会替换本地 tag**，
即 `export_base_images.sh load` 之后，这些 tag 在本机只解析为归档所含的平台
（本次归档为 `linux/arm64`）。脚本第 342 行注释已说明这一点。

由此带来的影响与后续处置：
- 本机 4 个构建基础镜像一度只剩 arm64，amd64 变体丢失 → 生产构建
  （`DOCKER_DEFAULT_PLATFORM=linux/amd64`）会失败。
- 已从国内镜像站 `docker.1ms.run` 重新拉取 4 个 amd64 变体，
  并**统一使用裸镜像名**（`python:3.10-slim-bookworm` 等），
  不保留 `docker.1ms.run/library/...` 前缀标签，便于后续处理。
- 实测 `docker run --platform linux/amd64 <裸名>` 均返回 `x86_64`；
  生产路径 `DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose ... build`
  构建 `document-api` 成功（5 分 23 秒），产物 `Architecture: amd64`，
  离线装 388 个 .deb + 294 个 wheel，LibreOffice 与 CJK 字体均正常。

