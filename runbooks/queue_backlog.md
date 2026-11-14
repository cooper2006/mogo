# 队列积压

> 告警：`MogoLatencyP99High`（P1）/ `MogoServiceNotReady`（P0）
> 关联场景：文档解析任务长时间「处理中」、预览不生成、批量导入卡住

## 1. 症状

- 文档状态长期停在 `pending` / `processing`，前端一直转圈；
- `document-worker` 日志无新任务开始，或只有 `Received task` 没有 `succeeded`；
- Redis 中队列长度持续上涨（`llen`）；
- 用户侧：上传成功但永远解析不出来；批量导入进度不动。

[只读排查]

```bash
docker compose ps document-worker
docker compose logs --tail=200 document-worker

# 队列长度（Celery/RQ 任务队列，默认 Redis DB 0）
docker compose exec redis redis-cli KEYS '*queue*' | head -20
docker compose exec redis redis-cli LLEN <队列名>

# worker 是否还活着、并发是否打满
docker compose exec document-worker ps aux | grep -c worker
docker compose exec redis redis-cli INFO stats | grep -E "instantaneous_ops_per_sec"
```

## 2. 影响

- 解析能力降级，用户上传后无结果（属于**用户可见的失败**，不是单纯的等待变慢）；
- 任务积压会持续占用 Redis 内存，可能反向触发 `redis_stall`；
- 若 worker 重启并重复投递，需确认任务幂等（否则重复解析计费）。

## 3. 根因（按概率排序）

1. **worker 挂了 / 未启动** — 最常见。`docker compose ps` 显示 `Exited` 或
   `Restarting`；看日志里的启动自检失败（依赖不可达）。
2. **worker 存活但卡在单任务** — 某个大文档解析耗时极长（OCR/表格），
   并发槽位被占满。特征：队列不降但 CPU 持续高，日志只有一条 `started` 没 `succeeded`。
3. **投递快于消费** — 批量导入或重试风暴导致生产速率 > 消费速率。
4. **重试放大** — 任务失败后无限重试（缺 `max_retries`），把队列灌满。
5. **broker 连接问题** — worker 与 Redis 之间连接不稳定，任务反复重新入队。

## 4. 恢复步骤

```bash
# A. worker 未运行 → 拉起（不影响已有数据）
docker compose up -d document-worker
docker compose logs -f --tail=100 document-worker

# B. 扩容消费能力（临时加副本；需确认任务幂等）
docker compose up -d --scale document-worker=3 document-worker

# C. 卡死的单任务 → 定位后终止该任务（会改状态）
#    先从日志找到 task_id，再按 Celery/RQ 的撤销接口处理；
#    禁止直接 kill -9 丢任务（会留下永久 processing 状态）
docker compose logs document-worker | grep -i "started" | tail -5

# D. 重试放大 → 确认 max_retries 上限，必要时清理失败队列
docker compose exec redis redis-cli LLEN <队列名>
```

**状态修复**：任务确实丢失时，需要把文档状态从 `processing` 改回 `pending`
（属数据修复，走双人确认 + 记录工单）。

## 5. 验证

```bash
docker compose exec redis redis-cli LLEN <队列名>      # 期望持续下降
docker compose logs --tail=50 document-worker | grep -c succeeded
curl -s http://127.0.0.1:8200/ready | head -c 300
```

## 6. 事后复盘模板

```markdown
### 复盘：队列积压（YYYY-MM-DD）
- 发现 / 恢复时间，最大积压条数，最长等待时长：
- 卡住的文档数 / 受影响租户：
- 根因分类（worker 挂 / 单任务卡死 / 产能不足 / 重试放大）：
- 是否有任务丢失？状态修复记录（工单号）：
- 改进项：
  - [ ] 队列深度作为一等指标暴露（当前无 `mogo_queue_depth` 业务值接入）
  - [ ] 单任务超时上限 + 幂等保证
  - [ ] 批量导入前的产能评估与限速
```
