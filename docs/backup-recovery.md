# MOGO 备份与恢复策略

## 恢复点目标（RPO）

| 数据集 | RPO | 说明 |
| --- | --- | --- |
| MongoDB 主数据 | 15 分钟 | 每 15 分钟增量备份 |
| MongoDB 日志 | 15 分钟 | 与主数据同步 |
| 文件存储 | 1 小时 | 每小时同步到远端 |
| 配置数据 | 实时 | 纳入 Git 版本控制 |

## 恢复时间目标（RTO）

| 故障场景 | RTO | 说明 |
| --- | --- | --- |
| 单节点故障 | 30 分钟 | 从最近备份恢复 |
| 磁盘故障 | 1 小时 | 从远端备份恢复 |
| 整个集群故障 | 4 小时 | 从异地备份恢复 |
| 数据损坏 | 2 小时 | 从校验备份恢复 |

## 备份调度

### systemd timer 模板

```ini
# /etc/systemd/system/mogo-backup.timer
[Unit]
Description=MOGO Backup Timer
After=network.target

[Timer]
OnCalendar=*:0/15
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/mogo-backup.service
[Unit]
Description=MOGO Backup Service

[Service]
Type=oneshot
ExecStart=/opt/mogo/scripts/backup.sh
User=mogo
Group=mogo
```

### Docker Compose 模板

```yaml
# docker-compose.yml
services:
  backup:
    image: bitnami/mongodump:6.0
    volumes:
      - ./backups:/backups
      - mongodb_data:/data/db
    entrypoint: >
      /bin/sh -c "
      mongodump --uri mongodb://mongodb:27017/mogo
      --archive=/backups/mogo-$(date +%Y%m%d_%H%M%S).tar
      --gzip
      && echo $(date +%Y-%m-%dT%H:%M:%SZ) > /backups/last-success
      "
    restart: "no"
    profiles: ["backup"]
```

## 备份脚本

```bash
#!/bin/bash
# /opt/mogo/scripts/backup.sh

set -euo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/opt/mogo/backups"
REMOTE_DIR="s3://mogo-backups/daily/${TIMESTAMP}"

# 1. 本地备份
mongodump --uri "$MONGODB_URI" --db mogo \
  --archive="${BACKUP_DIR}/mogo-${TIMESTAMP}.tar" --gzip

# 2. 校验备份
tar -tzf "${BACKUP_DIR}/mogo-${TIMESTAMP}.tar" > /dev/null 2>&1 || {
  echo "Backup validation failed"
  exit 1
}

# 3. 加密备份
openssl enc -aes-256-cbc -salt -in "${BACKUP_DIR}/mogo-${TIMESTAMP}.tar" \
  -out "${BACKUP_DIR}/mogo-${TIMESTAMP}.tar.enc" \
  -pass file:/opt/mogo/secrets/backup.key

# 4. 推送到远端（跨故障域）
rclone copy "${BACKUP_DIR}/mogo-${TIMESTAMP}.tar.enc" \
  "${REMOTE_DIR}/" --progress

# 5. 记录成功时间戳
echo "${TIMESTAMP}" > "${BACKUP_DIR}/last-success"

# 6. 清理本地过期备份（保留 7 天）
find "${BACKUP_DIR}" -name "*.tar*" -mtime +7 -delete

echo "Backup completed: ${TIMESTAMP}"
```

## 备份监控

### 最近成功时间戳

备份成功后记录时间戳到 MongoDB `backup_metadata` 集合：

```python
# 备份成功后
db.backup_metadata.update_one(
    {"service": "mongodb"},
    {"$set": {
        "last_success_at": datetime.now(timezone.utc),
        "last_backup_file": backup_path,
        "size_bytes": os.path.getsize(backup_path)
    }},
    upsert=True
)
```

### 超期告警

检查最近成功时间戳，超过 RPO 的 2 倍则告警：

```python
# 告警检查
from datetime import datetime, timezone, timedelta

last_success = db.backup_metadata.find_one({"service": "mongodb"})["last_success_at"]
rpo_threshold = datetime.now(timezone.utc) - timedelta(minutes=30)

if last_success < rpo_threshold:
    alert("Backup overdue! Last success: " + str(last_success))
```

## 恢复演练

### 演练脚本

```bash
#!/bin/bash
# /opt/mogo/scripts/restore-drill.sh

set -euo pipefail

DRILL_DIR="/tmp/restore-drill-${TIMESTAMP}"
mkdir -p "${DRILL_DIR}"

# 1. 解压最新备份
LATEST=$(ls -t /opt/mogo/backups/mogo-*.tar.enc | head -1)
openssl enc -d -aes-256-cbc -in "${LATEST}" \
  -out "${DRILL_DIR}/mogo.tar" \
  -pass file:/opt/mogo/secrets/backup.key

tar -xzf "${DRILL_DIR}/mogo.tar" -C "${DRILL_DIR}"

# 2. 启动临时 MongoDB 实例
#    镜像版本必须与被备份数据的数据目录格式一致：本栈已升级到 8.3.13，
#    8.x 的数据目录用 mongo:6.0 起不来（WiredTiger 只升不降）。
docker run -d --name mongo-drill \
  -v "${DRILL_DIR}:/data/db" \
  -p 27018:27017 \
  mongo:8.3.13

# 3. 等待 MongoDB 就绪
until docker exec mongo-drill mongosh --quiet --eval "db.adminCommand('ping')" > /dev/null 2>&1; do
  sleep 1
done

# 4. 验证关键集合
echo "Verifying collection counts..."
for coll in users chat_sessions chat_messages token_usage_logs; do
  COUNT=$(docker exec mongo-drill mongosh --quiet --eval \
    "db.getSiblingDB('mogo').${coll}.countDocuments()")
  echo "${coll}: ${COUNT} documents"
  [ "$COUNT" -gt 0 ] || {
    echo "FAIL: ${coll} is empty"
    exit 1
  }
done

# 5. 记录演练结果
echo "${TIMESTAMP}" > "${DRILL_DIR}/drill-success"
echo "Restore drill completed successfully"

# 6. 清理
docker stop mongo-drill && docker rm mongo-drill
rm -rf "${DRILL_DIR}"
```

### 演练频率

| 演练类型 | 频率 | 通过标准 |
| --- | --- | --- |
| 恢复演练 | 每月 | RTO 内完成，数据完整 |
| 备份校验 | 每周 | 校验和匹配 |
| 跨域验证 | 每季度 | 远端备份可恢复 |

## 跨故障域备份

### S3 配置

```bash
# rclone 配置
rclone config create s3-mogo s3 \
  provider AWS \
  env_auth false \
  access_key_id "$AWS_ACCESS_KEY_ID" \
  secret_access_key "$AWS_SECRET_ACCESS_KEY" \
  region us-east-1 \
  bucket mogo-backups
```

### 备份加密策略（QF-707）

#### 加密算法

| 层级 | 算法 | 密钥长度 | 说明 |
| --- | --- | --- | --- |
| 传输层 | TLS 1.2+ / TLS 1.3 | — | 备份推送到远端时自动加密（见 `deploy/nginx/nginx.conf`） |
| 存储层 | AES-256-GCM | 256 位 | 备份文件本身加密（GPG 默认） |
| 密钥管理 | HashiCorp Vault / AWS KMS | — | 备份密钥由 KMS 管理，与应用密钥分离 |

#### 密钥管理

- 备份密钥（`backup.key`）与备份文件**物理分离存放**（密钥在 Vault/KMS，文件在 S3）
- 密钥轮换周期：**90 天**（Vault 自动轮换或手动触发）
- 密钥访问审计：所有密钥使用操作记录到 Vault audit device
- 密钥分级：
  - **主密钥（MK）**：Vault/KMS 根密钥，仅 Vault 管理员可访问
  - **数据密钥（DEK）**：每次备份生成独立的 DEK，用于加密备份文件
  - DEK 由 MK 加密后随备份文件一起存储（envelope encryption）

#### 恢复验证

- 每次备份后立即执行**校验和验证**（`sha256sum`）
- 每周执行一次**恢复演练**（从备份恢复到测试环境，验证数据完整性）
- 每月执行一次**全量恢复演练**（见 `docs/security/DISASTER_RECOVERY_DRILL.md`）
- 恢复演练记录保留至少 1 年，纳入合规审计范围

## 审计与合规

- 备份操作记录到 `audit_logs` 集合
- 恢复操作需要管理员权限
- 备份删除需要双人审批
- 法定保留数据不可自动删除

## 更多文档

- [部署指南](docker-deployment.md)
- [故障排查](TROUBLESHOOTING.md)
- [隐私政策](privacy.md)
