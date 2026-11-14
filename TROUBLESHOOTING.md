# MOGO 故障排查指南

按症状检索的常见故障与处置步骤。每条条目包含：**症状原文** → **成因** → **处置**。

## 快速定位

```bash
./mogo status                    # 查看服务健康状态
./mogo logs <service>            # 查看指定服务日志
./mogo logs chat-api --tail 100  # 最近 100 行
```

## Docker / 容器

### 症状：`./mogo up` 报 `permission denied` 或 `cannot connect to the Docker daemon`

**成因**：当前用户无 Docker 权限。

**处置**：
```bash
sudo usermod -aG docker $USER
newgrp docker      # 或重新登录
docker info        # 验证
```

### 症状：`Error response from daemon: manifest for ghcr.io/... not found`

**成因**：镜像 tag 不存在或 registry 不可达。

**处置**：
1. 确认 `MOGO_VERSION` 指向存在的 tag：`docker manifest inspect ghcr.io/mogoai/chat-api:$MOGO_VERSION`
2. 若网络受限，配置镜像加速器：`MOGO_BASE_IMAGE_MIRROR=docker.m.daocloud.io ./mogo build`
3. 若使用 `latest` tag，改用固定版本：`MOGO_VERSION=v0.2.1 ./mogo up`

### 症状：`port is already allocated`

**成因**：端口被其他进程占用。

**处置**：
```bash
lsof -i :3000     # 查看 3000 端口占用
docker ps         # 检查是否有其他 mogo 实例
./mogo down       # 停止本实例（不影响数据卷）
```

### 症状：`OOMKilled` 或 `container is unhealthy`

**成因**：内存不足或镜像拉取不完整。

**处置**：
```bash
./mogo logs chat-api | tail -50
docker stats      # 查看当前内存使用
./mogo restart    # 重启服务
```

## LLM 与 API

### 症状：`ConnectionError: [Errno 111] Connection refused`（chat-api 日志）

**成因**：DashScope / OpenAI API 不可达或配置错误。

**处置**：
1. 检查 `.env` 中 `DASHSCOPE_API_KEY` 或 `OPENAI_API_KEY`
2. 验证 API key 有效：`curl -H "Authorization: Bearer $KEY" https://dashscope.aliyuncs.com/compatible-mode/v1/models`
3. 检查代理配置：`NO_PROXY=127.0.0.1,localhost`

### 症状：`401 Unauthorized` 或 `Invalid API key`

**成因**：API key 无效或已过期。

**处置**：
- 重新生成 API key，更新 `.env`，执行 `./mogo restart chat-api`

### 症状：`Rate limit exceeded` 或 `429 Too Many Requests`

**成因**：API 调用频率超限。

**处置**：
1. 查看当前配额：登录 DashScope 控制台查看用量
2. 实现重试与退避（chat-api 已内置 tenacity 重试）
3. 降级到备用模型或降低并发

### 症状：`TimeoutError` 或 `request timeout`

**成因**：网络延迟或 LLM 响应慢。

**处置**：
- 检查 `CHAT_API_TIMEOUT_SECONDS`（默认 120s）
- 若持续超时，检查 LLM 服务状态或切换模型

## 文档解析 (document-parser)

### 症状：`docling errors` 或 `OCR failed`

**成因**：docling 版本与 rapidocr 模型不匹配，或 CPU 架构不兼容。

**处置**：
- 确认使用 `docling 2.108.0` + `rapidocr 3.8.4`（见 `requirements-docling.txt`）
- ARM 架构（Apple Silicon）确认使用 `linux/arm64` 镜像
- 查看日志：`./mogo logs document-parser | grep -i error`

### 症状：`PDF` 解析结果为空或乱码

**成因**：PDF 为扫描件或加密，需 OCR 但 OCR 模型未加载。

**处置**：
- 检查 LibreOffice 是否可用：`./mogo logs document-parser | grep -i libreoffice`
- 确认 `docling` 模型目录存在：`ls /models`

### 症状：`ImportError: No module named 'docling'`

**成因**：依赖未安装或安装失败。

**处置**：
```bash
./mogo logs document-parser | grep -i "pip install"
# 重建镜像
./mogo build document-parser
./mogo up document-parser
```

## 数据库 (MongoDB)

### 症状：`ServerSelectionTimeoutError` 或 `unable to connect to server`

**成因**：MongoDB 容器未启动或连接串错误。

**处置**：
```bash
./mogo status | grep mongo
docker logs mogo-mongo-1   # 查看 MongoDB 日志
# 检查连接串
echo $ASKAI_ADMIN_MONGODB_URI
```

### 症状：`Connection refused` 或 `socket timeout`

**成因**：MongoDB 启动中或连接池耗尽。

**处置**：
- 等待 30 秒后重试
- 检查 MongoDB 健康：`docker exec mogo-mongo-1 mongosh --eval "db.adminCommand('ping')"`
- 增加连接池：`MONGO_MAX_POOL_SIZE=100`

### 症状：`CommandNotSupported` 或 `FeatureCommandError`

**成因**：MongoDB 版本与驱动不兼容。

**处置**：
- 确认 MongoDB ≥ 6.0（见 `docker-compose.yml`）
- 检查驱动版本：`pip show pymongo`

## 前端 (user-web / admin-web)

### 症状：`502 Bad Gateway` 或 `504 Gateway Timeout`

**成因**：后端服务未启动或 nginx 配置错误。

**处置**：
```bash
./mogo status
./mogo logs user-web | tail -30
./mogo logs nginx | tail -30
```

### 症状：`CORS error` 或 `Origin not allowed`

**成因**：跨域配置缺失。

**处置**：
- 检查 `CORS_ORIGINS` 环境变量
- 确认前后端端口匹配

### 症状：`blank screen` 或 `failed to load resource`

**成因**：静态资源未加载或构建失败。

**处置**：
- 清理浏览器缓存
- 检查 nginx 日志：`./mogo logs nginx | grep -i error`
- 重新构建前端：`./mogo build user-web`

## 备份与恢复

### 症状：`./mogo backup` 报 `no space left on device`

**成因**：备份目标磁盘空间不足。

**处置**：
- 备份会包含所有 8 个命名卷，可能很大
- 选择大磁盘路径：`./mogo backup /path/on/large/disk/backup`
- 清理旧备份：`rm -rf /path/to/old/backup`

### 症状：`./mogo restore` 报 `checksum mismatch`

**成因**：备份文件损坏或传输中断。

**处置**：
- 重新生成备份
- 检查备份完整性：`sha256sum <backup-file>`

### 症状：`./mogo restore` 报 `volume prefix mismatch`

**成因**：`MOGO_VOLUME_PREFIX` 与备份时不一致。

**处置**：
- 恢复时保持 `MOGO_VOLUME_PREFIX` 不变
- 若必须更换前缀，需手动迁移卷

## CI / 构建

### 症状：CI `pnpm install --frozen-lockfile` 失败

**成因**：锁文件与 package.json 不一致。

**处置**：
```bash
cd apps/user-web
pnpm install --lockfile-only   # 重新生成锁文件
git add pnpm-lock.yaml
git commit -m "chore: update lockfile"
```

### 症状：CI `python -m compileall` 失败

**成因**：Python 语法错误。

**处置**：
```bash
python -m compileall -q services/chat-api/app
# 查看错误文件
```

### 症状：CI `pyflakes` 报 `undefined name`

**成因**：引用了未导入的符号。

**处置**：
- 查看 pyflakes 输出定位文件与行号
- 添加缺失的 import 或修正引用

### 症状：CI 超时（`timeout-minutes` exceeded）

**成因**：任务卡死或依赖拉取缓慢。

**处置**：
- 查看具体 job 的耗时
- 若为依赖拉取，配置 pip/pnpm 缓存
- 若为测试卡死，加 `--timeout=120` 参数

## 日志位置速查

| 服务 | 容器名 | 日志命令 |
| --- | --- | --- |
| chat-api | `mogo-chat-api-1` | `./mogo logs chat-api` |
| admin-api | `mogo-admin-api-1` | `./mogo logs admin-api` |
| document-parser | `mogo-document-parser-1` | `./mogo logs document-parser` |
| user-web (nginx) | `mogo-user-web-1` | `./mogo logs user-web` |
| admin-web (nginx) | `mogo-admin-web-1` | `./mogo logs admin-web` |
| MongoDB | `mogo-mongo-1` | `docker logs mogo-mongo-1` |
| Redis | `mogo-redis-1` | `docker logs mogo-redis-1` |
| Weaviate | `mogo-weaviate-1` | `docker logs mogo-weaviate-1` |

## 更多资源

- [Windows 安装指南](windows-installation.md)
- [企业级智能体功能补强规划](企业级智能体功能补强规划.md)
- [CHANGELOG](../CHANGELOG.md)
- [GitHub Issues](https://github.com/cooper2006/mogo/issues)
- [Security Policy](../SECURITY.md)
