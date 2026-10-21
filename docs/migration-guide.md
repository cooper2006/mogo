# 迁移指南 (Migration Guide)

破坏性变更的迁移说明。每次发布包含 breaking changes 时，本文件必须更新。

> **品牌归一说明（2026-10-21）**：`MOVO_` 前缀已彻底下线（不再作为回退被接受），只认 `MOGO_`；卷名前缀默认值已由 `movo` 改为 `mogo`，升级既有部署需按 `docs/migrate-volumes-movo-to-mogo.md` 迁移数据卷。

## v0.1.x → v0.2.0

### 1. 数据库 schema 变更

**MongoDB 索引新增**：
```javascript
// 在 MongoDB 6.0 中执行（如未自动迁移）
db.runCommand({
  createIndexes: "knowledge_documents",
  index: [{ tenant_id: 1, document_id: 1 }]
})
```

**字段改名**：
| 旧字段 | 新字段 | 迁移脚本 |
| --- | --- | --- |
| `main_id` | `tenant_id` | `scripts/migrate/main_id_to_tenant_id.py` |
| `owner_user_id` | `created_by` | `scripts/migrate/owner_to_created_by.py` |

**迁移步骤**：
```bash
# 1. 备份
./mogo backup /path/to/backup

# 2. 停止服务
./mogo down

# 3. 执行迁移脚本
python scripts/migrate/main_id_to_tenant_id.py --mongo-uri $MONGO_URI --dry-run
python scripts/migrate/main_id_to_tenant_id.py --mongo-uri $MONGO_URI --apply

# 4. 启动新版本
./mogo up
```

### 2. 环境变量变更

**新增必需键**：
```env
MOGO_VOLUME_PREFIX=mogo           # 必填，默认 mogo
MOGO_BASE_IMAGE_POLICY=reuse      # 可选，默认 reuse
MOGO_SECURITY_REFRESH=            # 可选，发布镜像时设置
```

**已移除键**：
- `MOGO_DATA_DIR`（v0.1.x）→ 使用 `MOGO_VOLUME_PREFIX` 替代
- `MOGO_REGISTRY`（v0.1.x）→ 使用 `MOGO_IMAGE_REGISTRY` 替代

### 3. API 变更

**Breaking Changes**：
- `POST /documents/upload` 新增必填字段 `tenant_id`（之前为 `main_id`）
- `GET /documents/{id}` 响应中 `owner` 字段改名为 `created_by`
- `DELETE /documents/{id}` 需管理员权限（之前仅检查 owner）

**新增端点**：
- `GET /health`：健康检查
- `GET /metrics`：Prometheus 指标（需启用）
- `POST /documents/batch-upload`：批量上传

### 4. 配置变更

**docker-compose.yml 新增服务**：
- `weaviate`：向量数据库（可选，默认启用）
- `minio`：对象存储（可选，默认禁用）

**端口变更**：
- user-web: 3000 → 3000（无变化）
- admin-web: 3001 → 3001（无变化）
- chat-api: 8000 → 8000（无变化）

### 5. 回滚步骤

```bash
# 1. 停止新版本
./mogo down

# 2. 恢复备份
./mogo restore /path/to/backup --yes

# 3. 执行反向迁移（如需）
python scripts/migrate/main_id_to_tenant_id.py --mongo-uri $MONGO_URI --reverse

# 4. 启动旧版本
MOGO_VERSION=v0.1.x ./mogo up
```

## v0.2.0 → v0.3.0

*（待 v0.3.0 发布时补充）*

## 通用迁移工具

```bash
# 查看当前版本
./mogo status | grep version

# 查看可用迁移脚本
ls scripts/migrate/

# 预检迁移
python scripts/migrate/check_preconditions.py --target v0.2.0

# 执行完整迁移（含备份）
./mogo migrate --to v0.2.0 --backup-dir /path/to/backup
```

## 兼容性检查清单

- [ ] 数据库版本符合要求（MongoDB ≥ 6.0）
- [ ] 已执行所有必要的迁移脚本
- [ ] `.env` 中新增必需键已填写
- [ ] 已阅读 CHANGELOG breaking changes 段落
- [ ] 备份已完成且可恢复
- [ ] 回滚方案已验证

## 支持窗口

迁移问题在目标版本停止支持前均可获得维护者帮助。停止支持后仅接收安全修复。

详见 [支持政策](support-policy.md)。
