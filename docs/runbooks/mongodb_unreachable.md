# MongoDB 不可达

> 告警：`MogoServiceNotReady`（P0）/ `MogoServiceScrapeDown`（P0）
> 关联场景：写入失败、登录不可用、会话列表加载失败

## 1. 症状

- `/ready` 返回非 200，响应体里 `dependencies.mongodb` 为 `false` 或缺失；
- 日志出现 `ServerSelectionTimeoutError` / `pymongo.errors.ConnectionFailure` /
  `topology ... closed`；
- 用户侧：登录失败、会话列表空白、消息发送报 5xx。

[只读排查]

```bash
docker compose ps mongo
docker compose logs --tail=200 mongo
# 应用侧连接串（默认 mongodb://mongo:27017）
docker compose exec chat-api printenv | grep -i MONGODB_URI
# 从应用容器内验证网络可达
docker compose exec chat-api python -c "import socket;s=socket.create_connection(('mongo',27017),3);print('tcp ok');s.close()"
# Prometheus 侧确认抓取是否也断了
curl -s 'http://127.0.0.1:9090/api/v1/query?query=up{job="chat-api"}' | head -c 400
```

## 2. 影响

| 能力 | 影响 |
|---|---|
| 登录 / 鉴权 | 完全不可用（用户库在 MongoDB） |
| 会话与消息 | 读不可用、写失败 |
| 文档解析 | 任务可入队但状态无法落库，最终超时 |
| 计费与审计 | **可能丢事件**，需人工核对 |

## 3. 根因（按概率排序）

1. **容器未运行 / 反复重启** — `docker compose ps mongo` 显示 `Restarting`。
   看日志里是否有 `Data directory ... not found` 或磁盘满导致的 `fsync` 失败。
2. **磁盘打满** — MongoDB 拒绝写入并以只读状态存活。`df -h` 看 `/var/lib/docker`。
   通常伴随 `MogoHostDiskLow`（P2）。
3. **内存不足 / OOMKill** — `docker inspect mongo --format '{{.State.OOMKilled}}'`。
4. **连接池耗尽** — 应用侧 `connections ... maxPoolSize` 打满，MongoDB 本身健康。
   特征：`/ready` 间歇性失败而 `mongosh ping` 正常。
5. **网络隔离** — compose 网络变更、backend 网络被重建，`mongo` 主机名解析失败。
6. **副本集选主失败** — 多节点部署时 `rs.status()` 无 PRIMARY。

## 4. 恢复步骤

[只读排查] 先定位到上面的某一类，再按对应分支处理。

```bash
# A. 容器没起来 → 看原因后重启（不改数据）
docker compose up -d mongo
docker compose logs --tail=100 mongo

# B. 磁盘满 → 先腾空间（清理日志卷/旧备份），再重启 mongo
df -h
docker system df
docker compose restart mongo

# C. 连接池耗尽 → 先降流量（网关侧限流），再滚动重启应用
docker compose restart chat-api admin-api document-parser

# D. 数据目录损坏 → 停止写入，从最近备份恢复（会改状态，需双人确认）
ls -la backups/
# 按 022 灾备流程执行，禁止直接 rm -rf 数据卷
```

**禁止**：不要 `docker compose down -v`（会删数据卷）；不要在生产直接跑 `repair`。

## 5. 验证

```bash
docker compose exec mongo mongosh --quiet --eval 'db.adminCommand({ping:1})'
curl -s http://127.0.0.1:8000/ready | head -c 300      # 期望 200 且 mongodb=true
curl -s 'http://127.0.0.1:9090/api/v1/query?query=up{job="chat-api"}'
```

## 6. 事后复盘模板

```markdown
### 复盘：MongoDB 不可达（YYYY-MM-DD）
- 发现时间 / 恢复时间 / 总时长：
- 影响面：受影响租户数、失败请求数、是否丢事件（是/否，如何核对）：
- 直接原因：
- 根本原因（5 Whys 至少 3 层）：
- 检测：哪条告警先触发？`/ready` 与 `up` 是否都触发？MTTD：
- 改进项（每条带负责人与截止日期）：
  - [ ] 容量/磁盘水位提前预警阈值
  - [ ] 连接池参数与限流联动
  - [ ] 备份恢复演练纳入季度计划
```
