# 数据迁移脚本目录（024 T051 / FR-024）

本目录存放**可回滚的数据迁移脚本**，配合 `deploy/runbook/data-rollback-matrix.md` 使用。
灰度发布（canary）推进档位前，如需数据层变更，先在此提交迁移脚本，再由人工/自动回滚执行。

## 文件命名约定

```
<序号>_<描述>.py       # 迁移脚本（如 0001_add_optional_field.py）
<序号>_<描述>.down.py  # 对应的回滚脚本（reverse migration）
```

- 序号三位数递增，全局唯一；不得复用。
- 每个变更必须成对提供 `up`（正向）与 `down`（回滚）脚本，缺一不可。
- `down` 必须在 `up` 之后可执行（幂等：重复执行不产生副作用）。

## 脚本接口约定

每个脚本实现 `up()` / `down()`，`__main__` 里按 `--direction up|down` 分派：

```python
"""0001_add_optional_field.py — 为 chat-api 会话记录新增可选字段。"""
import sys

FIELD = "canary_probe_at"

def up():
    # 幂等：字段已存在则跳过
    ...

def down():
    # 删除字段（仅当确实要回滚时）
    ...

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--direction" and sys.argv[2] == "down":
        down()
    else:
        up()
```

## 硬性要求

1. **幂等**：脚本重复执行结果一致（用 `exists` / `if not` 判断）。
2. **向后兼容**：变更不得让旧版本（stable）读写失败；字段改名/类型调整必须保留双写窗口。
3. **备份前置**：运行迁移前先 `./mogo backup`，并把备份时间记入部署记录。
4. **可回滚**：`down` 能把数据层恢复到 `up` 之前可用的状态；不可逆变更（删字段、改类型）
   必须先在 `deploy/runbook/data-rollback-matrix.md` 标注为高风险并写清恢复路径。
5. **评审**：迁移脚本随 PR 提交，在 PR 描述中说明影响面、回滚方式、预估耗时。

## 目录内容

当前为空（本轮 024 T051 只建立目录与约定）。后续数据变更脚本按上表命名加入。
## 在线迁移要求（024 T058 / FR-031）

除基础约定外，在线迁移 MUST 满足：

1. **迁移幂等**：同一迁移重复执行结果一致（已用 `exists` / `if not` 判断，up 与 down 都可重跑）。
2. **长事务拆分**：单次事务影响行数超过阈值（默认 1000 条）必须拆成小批次循环
   （如每次 200 条 + `time.sleep(0.05)`），避免长事务持有锁阻塞线上。
3. **不阻塞线上请求**：迁移期间 MUST 持续发送探测请求验证吞吐未下降
   （见 `scripts/migrations/probe_throughput.py`），任一窗口吞吐下降 > 20% 立即中止迁移。
4. **分批与重试**：失败批不整体回滚，只重跑该批；连续失败 3 批则暂停并告警。
5. **时间窗**：高风险迁移在低峰期执行（默认 02:00-05:00 本地时区），并在发布检查单记录窗口。
6. **回滚**：迁移中断必须能从任意批次继续或整体 down（down 也幂等）。

上述要求由 `deploy/cli/migration-gate.sh`（FR-029）与 `scripts/migrations/probe_throughput.py`（FR-031）
落地到发布流程与 CI。
