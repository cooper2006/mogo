# MOGO 安装与部署指南

本指南覆盖安装、运行时检查、升级、卸载与数据处置（QF-949/950/951/952/955/957/958/959/962/964）。

## 系统要求

### 运行时版本

| 组件 | 最低版本 | 检查方式 |
| --- | --- | --- |
| Docker | 24.0+ | `docker version` |
| Docker Compose | 2.0+ | `docker compose version` |
| Bash | 4.0+ | `bash --version` |
| Git | 2.0+ | `git --version` |
| Python（仅源码构建） | 3.13+ | `python3 --version` |
| Node.js（仅源码构建） | 22+ | `node --version` |

**首次启动检查**（QF-950）：
```bash
# 检查 Docker
docker info > /dev/null 2>&1 || { echo "❌ Docker 未安装"; exit 1; }
# 检查 Compose
docker compose version > /dev/null 2>&1 || { echo "❌ Docker Compose v2 未安装"; exit 1; }
# 检查 Bash
echo $BASH_VERSION | grep -qE '^[45]' || { echo "❌ Bash 4.0+ 所需"; exit 1; }
```

### 原生依赖与编译工具链（QF-951）

**预构建镜像路径**（推荐）：无需编译，直接拉取 GHCR 镜像。

**源码构建路径**（`./mogo build`）：
| 依赖 | 用途 | 安装命令（Ubuntu） |
| --- | --- | --- |
| build-essential | C/C++ 编译 | `apt install build-essential` |
| pkg-config | 库探测 | `apt install pkg-config` |
| libcairo2-dev | PDF 渲染 | `apt install libcairo2-dev` |
| libpango1.0-0 | 文本排版 | `apt install libpango1.0-0` |
| poppler-utils | PDF 工具 | `apt install poppler-utils` |
| libreoffice | DOCX/PPTX 转换 | `apt install libreoffice` |
| tesseract-ocr | OCR | `apt install tesseract-ocr` |

> `./mogo build` 默认**不**构建 `dsh-runtime-host`：它的 Compose 服务带
> `profiles: [single-host]`，默认（池模式）拓扑不会构建它。而池模式的 3 个副本
> 与单副本服务复用同一个镜像名，裸 `./mogo build` 之后 `./mogo up` 会回退去拉
> `ghcr.io/mogoai/dsh-runtime-host:<tag>`（离线主机直接失败，联网则静默跑成
> 与工作区不一致的已发布镜像）。需要时显式补建：
>
> ```bash
> docker compose -f docker-compose.yml -f docker-compose.build.yml \
>   --profile single-host build dsh-runtime-host
> ```
>
> `--profile` 是全局 flag，必须放在子命令之前。详见 `docs/docker-deployment.md`。

## 完整性校验（QF-949/962）

### GHCR 镜像校验

```bash
# 1. 获取镜像摘要
docker pull ghcr.io/mogoai/chat-api:v0.2.1
docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/mogoai/chat-api:v0.2.1

# 2. 对照发布页
# 访问 https://github.com/cooper2006/mogo/releases/tag/v0.2.1
# 发布说明中包含所有镜像的 digest 列表

# 3. 验证摘要一致
# 若不一致，说明镜像被篡改，停止安装并联系维护者
```

### 源码校验

```bash
# 1. 克隆指定 tag
git clone --branch v0.2.1 https://github.com/cooper2006/mogo.git
cd mogo

# 2. 验证 tag 签名
git tag -v v0.2.1

# 3. 验证文件完整性（如提供）
sha256sum -c CHECKSUMS.txt
```

## 首次运行指引（QF-952）

```bash
# 1. 克隆仓库
git clone https://github.com/cooper2006/mogo.git
cd mogo

# 2. 设置版本
export MOGO_VERSION=v0.2.1

# 3. 启动
./mogo up

# 首次启动输出示例：
# === MOGO v0.2.1 ===
# 正在拉取镜像...
# ✅ 7 个服务已启动
#
# 📊 访问地址：
#   用户界面: http://localhost:3000
#   管理后台: http://localhost:3001
#   API 文档: http://localhost:8000/docs
#
# 🔐 默认账号：
#   管理员: admin / admin123（首次登录需修改）
#
# 📖 下一步：
#   1. 访问 http://localhost:3001 登录管理后台
#   2. 配置 LLM API Key（设置 → API 密钥）
#   3. 上传文档建立知识库（知识库 → 上传）
#   4. 访问 http://localhost:3000 开始对话
#
# 📚 更多文档：
#   docs/TROUBLESHOOTING.md  故障排查
#   docs/docker-deployment.md 生产部署
```

## 升级（QF-955/957）

### 小版本升级（v0.2.0 → v0.2.1）

```bash
# 1. 备份
./mogo backup /path/to/backup

# 2. 更新版本
export MOGO_VERSION=v0.2.1

# 3. 拉取新镜像并重启
./mogo update

# 4. 验证
./mogo status
```

### 跨主版本升级（v0.1.x → v0.2.0）

**前置检查**：
1. 阅读 [迁移指南](migration-guide.md)
2. 执行数据库迁移脚本
3. 更新环境变量（`.env`）

**升级步骤**：
```bash
# 1. 备份
./mogo backup /path/to/backup

# 2. 停止当前版本
./mogo down

# 3. 执行迁移脚本
python scripts/migrate/main_id_to_tenant_id.py --mongo-uri $MONGO_URI --apply

# 4. 更新配置
# 编辑 .env，添加 v0.2.0 新增的必需键

# 5. 拉取新版本
export MOGO_VERSION=v0.2.0
./mogo up

# 6. 验证
./mogo status
curl http://localhost:8000/health
```

**回滚**：
```bash
# 1. 停止
./mogo down

# 2. 恢复备份
./mogo restore /path/to/backup --yes

# 3. 启动旧版本
export MOGO_VERSION=v0.1.x
./mogo up
```

### 升级安全性

- `./mogo update` 可重复执行，已启动的服务不会被重复创建。
- 升级不会自动执行数据库迁移，需手动运行迁移脚本。
- 备份是回滚的前提，强烈建议每次升级前执行。

## 卸载（QF-958）

### 停止服务（保留数据）

```bash
./mogo down
```

### 完全卸载（删除数据）

```bash
# 1. 停止服务
./mogo down

# 2. 删除数据卷（需要确认）
./mogo down -v --yes

# 3. 删除镜像
docker rmi ghcr.io/mogoai/*

# 4. 删除仓库（可选）
rm -rf /path/to/mogo
```

### 卸载后验证

```bash
# 服务不可用
curl http://localhost:3000  # 应返回连接失败

# 数据已删除
docker volume ls | grep mogo  # 应无结果
```

## 用户数据与配置处置（QF-959）

### 数据位置

| 数据 | 位置 | 卸载后 |
| --- | --- | --- |
| 用户配置 | `/config` 卷（`MOGO_VOLUME_PREFIX`） | 保留（`./mogo down` 不删卷） |
| 文档上传 | `/data/documents` 卷 | 保留 |
| 数据库 | MongoDB 卷 | 保留 |
| 日志 | `/logs` 卷 | 保留 |
| 密钥 | `/secrets` 卷 | 保留 |

### 数据清除

```bash
# 清除所有数据（不可恢复）
./mogo down -v --yes

# 仅清除特定数据
docker volume rm ${MOGO_VOLUME_PREFIX:-mogo}_mongo-data
```

### 数据迁移

```bash
# 导出备份
./mogo backup /path/to/backup

# 在新环境恢复
./mogo restore /path/to/backup --yes
```

## 代理与私有源配置（QF-964）

### HTTP 代理

```bash
# 在 .env 或 shell 中设置
export HTTP_PROXY=http://proxy.example.com:8080
export HTTPS_PROXY=http://proxy.example.com:8080
export NO_PROXY=localhost,127.0.0.1,.local

# 启动服务
./mogo up
```

### 私有 Docker 镜像源

```bash
# 配置镜像加速器
export MOGO_BASE_IMAGE_MIRROR=registry.example.com

# 或使用 docker daemon 配置
# /etc/docker/daemon.json
{
  "registry-mirrors": ["https://registry.example.com"]
}
```

### 私有 PyPI/npm 源

**PyPI**（仅源码构建）：
```bash
export PIP_INDEX_URL=https://pypi.example.com/simple
```

**npm**（仅源码构建）：
```bash
export NPM_CONFIG_REGISTRY=https://npm.example.com/
```

### 私有 GHCR

```bash
# 登录私有 GHCR
docker login ghcr.example.com

# 配置镜像拉取
export MOGO_IMAGE_REGISTRY=ghcr.example.com
./mogo up
```

## 常见问题

详见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。
