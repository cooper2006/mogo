# 容量模型（024 T105 / T108，FR-050）

> 本文档定义「业务量 → 资源需求」的换算关系与扩容触发点，并给出**可复现**的换算示例（T108）。
> 所有系数均为经验 / 示例值；真实部署 MUST 用压测数据替换（见 T106，需远端/预发环境）。
> 阈值与水位的对应关系见 `deploy/monitoring/watermarks.yml`（T102），实跑用 `./mogo monitor check`（T103/T104）。

## 1. 业务量 → 资源需求换算

| 输入 | 换算公式 | 示例系数（经验值） | 对应水位项 |
|------|----------|-------------------|------------|
| 峰值 QPS | `核数 = QPS / (单核可支撑 QPS)` | 单核 ≈ 80 QPS | `host.cpu.percent` |
| 日均活跃用户 DAU | `内存 GiB = DAU / 1000 × 每千用户内存` | 每千用户 ≈ 1.5 GiB | `host.memory.percent` |
| 日增数据量 | `磁盘增长 GiB/天` | 由业务实测 | `disk.data.used_percent` |
| 备份保留 | `所需备份空间 = 每日备份大小 × 保留天数` | 见 `backup-schedule.yml` retention | `disk.backup.used_percent` |
| 日志体积 | `日志 GiB = 日增日志 × 保留天数` | 日增日志实测 | `logs.total.bytes` |

> 系数来自 `scripts/capacity_calc.py` 的默认值（`--cpu-per-core-qps 80`、`--mem-per-1000-users 1.5`）。
> 真实部署用本机 `docker stats` 采样 + 一次压测替换，否则只能作规划下限。

## 2. 扩容触发点

容量告警由 `deploy/monitoring/watermarks.yml` 定义，`./mogo monitor check` 判定：

| 水位 | warn | crit | 动作 |
|------|------|------|------|
| `host.memory.percent` | 80% | 92% | WARN 释放容器；CRIT 扩内存 |
| `host.cpu.percent` | 75% | 90% | WARN 定位高负载容器；CRIT 扩容 |
| `disk.data.used_percent` | 75% | 90% | WARN 清理旧备份；CRIT 扩容数据盘 |
| `disk.backup.used_percent` | 80% | 95% | WARN 调保留策略；CRIT 停止备份并告警 |
| `backup.retain_count` | < 3 | < 1 | 备份异常，立即补做 |
| `backup.size.bytes` | < 1MiB | < 0 | 备份内容疑似缺失 |
| `logs.total.bytes` | 10GiB | 20GiB | WARN 轮转；CRIT 立即归档 |

扩容触发点与容量的换算关系：`达到阈值的天数 = (容量 × 阈值% − 当前已用) / 日增`，见 §3 可复现示例。

## 3. 可复现换算示例（T108）

运行一次即可复现，系数可从 `deploy/monitoring/watermarks.yml` 反查：

```bash
python3 scripts/capacity_calc.py --users 5000 --qps 200 --data-gb-per-day 10 --days 30
```

实测输出（2026-10-26，本机 ServBay python3 3.13）：

```
业务量 → 资源需求换算（示例系数，真实值以压测为准）
  DAU            = 5000 人
  QPS            = 200 req/s
  日增数据       = 10.0 GiB/day
-- 换算结果 --
  所需 CPU 核数  = 2.5 核 (200/80 QPS/核)
  所需内存       = 7.5 GiB (5000/1000 × 1.5 GiB)
  数据盘容量     = 500.0 GiB（当前 0.0 GiB）
  到达 75%（warn）约 37.5 天
  到达 90%（crit）约 45.0 天
  扩容触发点：disk.data.used_percent 超过 warn(75) / crit(90)，见 deploy/monitoring/watermarks.yml
-- JSON --
{"users": 5000, "qps": 200, "data_gb_per_day": 10.0, "cores": 2.5, "mem_gb": 7.5,
 "disk_warn_days": 37.5, "disk_crit_days": 45.0, "watermarks_warn_percent": 75, "watermarks_crit_percent": 90}
```

换算示例可复现性校验（T108）：脚本输出固定格式 JSON，CI 或文档可用

```bash
python3 scripts/capacity_calc.py --users 1000 --qps 50 --data-gb-per-day 2 | grep -c '"watermarks_crit_percent": 90'
```

比对阈值与文档一致（输出含 `watermarks_warn_percent` / `watermarks_crit_percent`）。

## 4. 换算系数取值说明

| 系数 | 默认 | 说明 |
|------|------|------|
| `--cpu-per-core-qps` | 80 | 经验值，受业务复杂度影响大；用 `k6`/`ab` 压测替换 |
| `--mem-per-1000-users` | 1.5 GiB | 含 Redis / 应用常驻，实际依赖模型大小 |
| `--disk-capacity-gb` | 500 GiB | 数据盘容量，按部署规格改 |

## 5. 已知局限

- 未做真实压测前，换算只能作**规划下限**，不能承诺 SLA（FR-050 的容量承诺需 T106 压测结论支撑，需远端环境）。
- 扩容**实测耗时**（T107）需真实环境，本机不可验；本文档只给出触发点判定方法。