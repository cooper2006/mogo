# 026 T049 — 容量模型（FR-30）

> 给定目标并发数 → 预测所需实例数与 CPU / 内存资源。
> 所有参数均可通过环境变量或 `baselines.yaml` 覆盖；公式保持单一来源，
> 压测实测值（`PerfBaselineCollector`，T006）回填后模型即可校正。

## 1. 输入参数

| 符号 | 含义 | 默认值 | 来源 |
|---|---|---|---|
| `C` | 目标并发在线用户数 | 用户输入 | — |
| `rps_u` | 单用户平均请求速率 | `0.5 rps`（约每 2s 一次请求） | 对话场景经验值 |
| `rps_i` | 单实例可承载 RPS | `1000` | `baselines.yaml → throughput.max_rps_per_instance` |
| `cpu_i` | 单实例 CPU 核数 | `1.0` | `deploy/config/image-baseline.yml` |
| `mem_i` | 单实例内存 | `512 MB` | 同上 |
| `cpu_util` | 目标 CPU 利用率水位 | `0.7`（70%，留出突发余量） | FR-10 峰值利用率 ≤ 80% 的保守取值 |
| `buf_mem` | 内存安全缓冲系数 | `1.3` | 缓存 / 连接池驻留 |
| `pool_max` | 单实例 MongoDB 连接池上限 | `100` | `baselines.yaml → database.pool.max_pool_size` |

## 2. 公式

### 2.1 所需总吞吐

```
R_total = C × rps_u          # 全部并发用户的目标聚合 RPS
```

### 2.2 所需实例数

```
N = ceil(R_total / rps_i)    # 单服务（chat-api / document-parser / admin-api 独立计算）
```

水平扩展近似线性（FR-27），即每新增 1 实例吞吐 ≈ 线性 + `rps_i`。

### 2.3 CPU 需求

```
CPU_total = N × cpu_i × cpu_util    # 单位：核（vCPU）
```

### 2.4 内存需求

```
MEM_total = N × mem_i × buf_mem     # 单位：MB
```

### 2.5 数据库连接池总量

```
POOL_total = N × pool_max            # 单位：连接数（MongoDB maxPoolSize 合计）
```

必须满足 `POOL_total ≤ Mongo 实例 maxPoolSize 上限 × 单实例可服务连接数`；
超限需增大 MongoDB 侧 pool 或引入读写分离（US2 Non-Goals 首期不启用）。

### 2.6 实例数向下取整约束

若 `R_total / rps_i` 非整数，向上取整；且至少保留 2 个实例以承载故障切换
（`N = max(N, 2)`）。

## 3. 示例（默认参数）

| 目标并发 C | R_total | 实例数 N | CPU（核） | 内存（MB） | DB 连接池合计 |
|---|---|---|---|---|---|
| 100 | 50 | 1 → 2 | 1.4 | 1331 | 200 |
| 500 | 250 | 1 → 2 | 1.4 | 1331 | 200 |
| 1 000 | 500 | 1 → 2 | 1.4 | 1331 | 200 |
| 5 000 | 2 500 | 3 | 2.1 | 1997 | 300 |
| 10 000 | 5 000 | 5 | 3.5 | 3328 | 500 |
| 50 000 | 25 000 | 25 | 17.5 | 16640 | 2500 |
| 100 000 | 50 000 | 50 | 35.0 | 33280 | 5000 |

> 说明：低并发段因 `max(N,2)` 保底规则取 2 实例；真实部署按
> `rps_i`（实测 T006 采集的 `perf_baselines`）回填后，低并发段可直接取 1 实例。

## 4. 模型校正（压测回填）

压测（T045-T048）产出 `perf_baselines` 后，按以下步骤校正模型：

1. 取各并发级别实测 `rps_total`（T013 `RuntimeKPIStore.throughput()`）；
2. 以 100 并发实测值计算 `rps_i_calibrated = rps_total(100) / 100 × 100`；
3. 替换公式中 `rps_i`；
4. 重新生成 §3 表格。

模型预测误差应满足：并发 ≤ 5000 时 `|预测 N - 实测 N| / 实测 N ≤ 0.2`（±20%）。

## 5. 使用命令

```bash
# 交互式计算（参数可用环境变量覆盖）
python3 -c "
from math import ceil
C = int(__import__('os').getenv('CAP_CONCURRENCY', '1000'))
rps_u = float(__import__('os').getenv('CAP_RPS_USER', '0.5'))
rps_i = float(__import__('os').getenv('CAP_RPS_INSTANCE', '1000'))
cpu_i = float(__import__('os').getenv('CAP_CPU_INSTANCE', '1.0'))
mem_i = float(__import__('os').getenv('CAP_MEM_INSTANCE', '512'))
util = float(__import__('os').getenv('CAP_CPU_UTIL', '0.7'))
buf = float(__import__('os').getenv('CAP_MEM_BUF', '1.3'))
pool = int(__import__('os').getenv('CAP_POOL_MAX', '100'))
rt = C * rps_u
N = max(ceil(rt / rps_i), 2)
print(f'C={C} R_total={rt:.0f} N={N} CPU={N*cpu_i*util:.1f} MEM={N*mem_i*buf:.0f}MB POOL={N*pool}')
"
```