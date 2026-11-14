# MOGO 环境差异与影响评估

本文档维护 MOGO 服务在不同环境间的配置差异，并评估每项差异对系统行为的影响。

## 1. 环境分类

| 环境 | 用途 | 规模 | 副本 | 外部依赖 |
|------|------|------|------|----------|
| local-dev | 本地开发 | 单进程 | 1 | 容器化（Docker Compose） |
| ci | 持续集成 | 单进程 | 1 | 模拟（Mock） |
| staging | 预发布 | 小规模 | 2-3 | 真实但限流 |
| production | 生产环境 | 大规模 | 3-10 | 真实 |

## 2. 配置差异清单

### 2.1 服务规模

| 配置项 | local-dev | ci | staging | production | 影响评估 |
|--------|-----------|-----|---------|------------|----------|
| `DB_CONNECTION_POOL_SIZE` | 10 | 5 | 20 | 50-100 | 连接池大小影响并发能力 |
| `REDIS_MAX_CONNECTIONS` | 10 | 5 | 20 | 50-100 | 缓存连接数影响性能 |
| `WEAVIATE_BATCH_SIZE` | 100 | 50 | 200 | 500-1000 | 向量写入批次影响索引速度 |
| `WORKER_COUNT` | 1 | 2 | 4 | 8-16 | 工作进程数影响吞吐量 |

### 2.2 超时配置

| 配置项 | local-dev | ci | staging | production | 影响评估 |
|--------|-----------|-----|---------|------------|----------|
| `LLM_TIMEOUT_SECONDS` | 30 | 10 | 30 | 60-120 | LLM 调用超时影响响应时间 |
| `DB_QUERY_TIMEOUT_SECONDS` | 30 | 10 | 30 | 60 | 数据库查询超时影响稳定性 |
| `REDIS_TIMEOUT_SECONDS` | 5 | 2 | 5 | 10 | 缓存超时影响性能 |
| `REQUEST_TIMEOUT_SECONDS` | 60 | 30 | 60 | 120 | 请求超时影响用户体验 |

### 2.3 外部依赖

| 依赖 | local-dev | ci | staging | production | 影响评估 |
|------|-----------|-----|---------|------------|----------|
| LLM Provider | OpenAI/DashScope | Mock | OpenAI/DashScope | OpenAI/DashScope | Mock 模式无法测试真实 LLM 行为 |
| MongoDB | 容器化 | 容器化 | 真实集群 | 真实集群 | CI 容器化环境可能与生产不一致 |
| Redis | 容器化 | 容器化 | 真实集群 | 真实集群 | 容器化 Redis 无持久化 |
| Weaviate | 容器化 | 容器化 | 真实集群 | 真实集群 | 容器化 Weaviate 无高可用 |
| Email Service | 本地模拟 | Mock | 真实但限流 | 真实 | Mock 模式无法测试邮件发送 |

### 2.4 操作系统与架构

| 配置项 | local-dev | ci | staging | production | 影响评估 |
|--------|-----------|-----|---------|------------|----------|
| OS | macOS/Linux | Ubuntu Linux | Ubuntu Linux | Ubuntu Linux | macOS 本地开发可能与 Linux 生产环境有差异 |
| Architecture | ARM/AMD64 | AMD64 | AMD64 | ARM/AMD64 | 架构差异可能影响性能 |
| Python Version | 3.13 | 3.13 | 3.13 | 3.13 | 版本一致 |
| Node.js Version | 22 | 22 | 22 | 22 | 版本一致 |

## 3. 已知问题与影响

### 3.1 时区差异

**问题**：本地开发时区可能与生产环境不同。

**影响**：
- 测试中时间相关的逻辑可能产生不一致结果
- 已修复：conftest.py 和 CI 配置固定 TZ=Asia/Shanghai（QF-106）

**缓解措施**：
```python
# conftest.py
import os
os.environ.setdefault("TZ", "Asia/Shanghai")
os.environ.setdefault("LANG", "en_US.UTF-8")
os.environ.setdefault("LC_ALL", "en_US.UTF-8")
```

### 3.2 网络差异

**问题**：本地开发使用容器网络，生产环境使用 VPC 网络。

**影响**：
- 服务间调用延迟不同
- 容器网络隔离可能导致本地测试通过但生产环境失败

**缓解措施**：
- 部署文档明确 internal 网络即受控边界（QF-649）
- CI 使用容器化环境模拟生产网络拓扑

### 3.3 存储差异

**问题**：本地开发使用容器卷，生产环境使用云存储。

**影响**：
- 存储性能差异
- 备份策略不同

**缓解措施**：
- 备份链提供可选 gpg/age 加密（QF-653）
- 文档标注备份目录权限要求

## 4. 测试策略

### 4.1 CI 测试覆盖

| 测试类型 | 覆盖范围 | 环境差异处理 |
|----------|----------|--------------|
| 单元测试 | 纯逻辑 | 使用 Mock 隔离外部依赖 |
| 集成测试 | 服务间交互 | 容器化依赖 |
| E2E 测试 | 完整流程 | 仅 staging/production |
| 性能测试 | 负载测试 | 仅 staging |

### 4.2 环境一致性检查

```bash
# 检查配置差异
python3 scripts/check_config_consistency.py

# 检查依赖版本
python3 scripts/check_dependency_versions.py

# 检查运行时版本
python3 scripts/check_runtime_versions.py
```

## 5. 变更管理

### 5.1 新增环境差异

当新增配置项或环境差异时，必须：
1. 更新本文档的差异清单
2. 评估对系统行为的影响
3. 更新相关测试用例
4. 在 PR 中注明新增差异

### 5.2 差异评估模板

```markdown
## 新增环境差异评估

**配置项**：`<NAME>`

**环境差异**：
| 环境 | 值 |
|------|-----|
| local-dev | <value> |
| ci | <value> |
| staging | <value> |
| production | <value> |

**影响评估**：
- 对性能的影响：<描述>
- 对稳定性的影响：<描述>
- 对安全性的影响：<描述>

**缓解措施**：
- <措施 1>
- <措施 2>

**测试覆盖**：
- [ ] 单元测试覆盖差异逻辑
- [ ] 集成测试覆盖差异场景
- [ ] E2E 测试覆盖完整流程
```

## 6. 维护记录

| 日期 | 变更 | 评估人 |
|------|------|--------|
| 2026-10-11 | 创建初始文档（QF-185） | - |

---

*本文档对应 QualityForge 审计项：QF-185*
