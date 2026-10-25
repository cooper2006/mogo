# Rate Limiting（限流）

> 025 FR-13（QF-237~QF-240）｜实现位置：`services/admin-api/app/middleware/rate_limit.py`、
> `services/admin-api/app/config/rate_limit.py`、`services/admin-api/app/config/rate_limit.yaml`
>
> 本页为限流维度和阈值的**唯一权威来源**；与代码实现不一致时，以本页为准并修复实现。

## 一、为什么需要限流

- 防止单 IP / 单租户 / 单用户 / 单端点占用过多资源导致服务退化（QF-237 曾实测为**超配额返回 5xx**）。
- 超配额时返回**语义正确的 429**（而非 500），并给出**可解析的重试提示**（QF-238）与**配额维度与余额**（QF-239）。

## 二、限流维度与默认阈值

| 维度 | key | 阈值 | 窗口 | 说明 |
| --- | --- | --- | --- | --- |
| `ip` | `rate_limit:ip:<client_ip>` | **100 次** | 60 秒 | 客户端来源 IP |
| `tenant` | `rate_limit:tenant:<tenant_id>` | **1000 次** | 60 秒 | 多租户隔离，租户级配额 |
| `user` | `rate_limit:user:<user_id>` | **100 次** | 60 秒 | 单用户级配额 |
| `endpoint` | `rate_limit:endpoint:<path>` | **500 次** | 60 秒 | 单端点路径 |

> 阈值是**窗口内请求次数上限**；任一维度命中即拒绝（各维度独立计数）。

**路径前缀放宽**（`overrides`，命中最长前缀者生效）：

| 路径前缀 | 放宽维度 | 阈值 |
| --- | --- | --- |
| `/internal` | `endpoint` | 2000 次 / 60 秒 |
| `/internal/personal-knowledge` | `endpoint` | 2000 次 / 60 秒 |

## 三、配置来源与优先级

1. `services/admin-api/app/config/rate_limit.yaml`（基线，见上表）；
2. 环境变量逐项覆盖：`MOGO_RATE_LIMIT_<DIM>_LIMIT`、`MOGO_RATE_LIMIT_<DIM>_WINDOW`
   （例如 `MOGO_RATE_LIMIT_IP_LIMIT=200`、`MOGO_RATE_LIMIT_ENDPOINT_WINDOW=30`）；
3. yaml 缺失或损坏时**回退内置默认值**（即上表数值）并打 warning——保证中间件总能启动；
   非法值（非正整数）被忽略。

## 四、算法：Redis 滑动窗口

- 存储：Redis **ZSET**，`score = 时间戳`，member = 时间戳字符串；
- 每次请求：`ZREMRANGEBYSCORE` 清理窗口外的旧记录 → `ZCOUNT` 统计当前窗口计数；
- 未超配额：`ZADD` 记录本次，`EXPIRE` 设窗口 + 10s（避免冷键残留）；
- 超配额：用窗口内**最早一条记录的分数 + window** 计算恢复时刻 `reset_at`；
- **降级**：Redis 不可达或熔断器打开时按「不限流」放行（不误杀业务），并降级到进程内存计数
  （**单实例**语义；多实例部署必须依赖 Redis）。后端可通过 `store.backend` 查看 `redis` / `memory`。

## 五、429 响应契约

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 1
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
Content-Type: application/json; charset=utf-8
```

```json
{
  "detail": {
    "code": "RATE_LIMITED",
    "message": "请求频率超限，请稍后重试",
    "limit": 100,
    "remaining": 0,
    "window": 60,
    "reset_at": "2026-10-25T12:00:01+00:00",
    "dimension": "ip"
  }
}
```

| 字段 | 含义 |
| --- | --- |
| `code` | 稳定错误码（T001 注册表风格）`RATE_LIMITED` |
| `limit` | 当前维度的窗口配额 |
| `remaining` | 配额余额（超配额时为 0） |
| `window` | 窗口秒数 |
| `reset_at` | 恢复时刻（ISO 8601 UTC） |
| `dimension` | 触发限流的维度名 |
| 响应头 `Retry-After` | 秒数，= `ceil(reset_at - now)`，至少 1 |
| 响应头 `X-RateLimit-Limit` / `X-RateLimit-Remaining` | 配额与余额 |

## 六、与登录限流的区别

- `app/core/rate_limiter.py`：登录专用的**失败尝试**限流（滑动窗口，5 次 / 300 秒），作用于登录接口；
- `app/middleware/rate_limit.py`（本页）：**全站通用** API 限流，四维度 + 路径覆盖，作用于所有 HTTP 请求。
两者独立部署，互不替代。

## 七、测试

- `services/admin-api/tests/test_rate_limit_t024_t025.py`（20 用例）：yaml 默认值 / 最长前缀覆盖 /
  未知维度 / yaml 缺失与损坏回退 / 环境变量覆盖 / store 结构与滑动恢复 / 429 契约五字段与响应头 /
  IP / tenant / endpoint 维度隔离 / override 生效 / 空配置放行 / 维度子集。
- 原则：测试只用**进程内存 store**，不连真实 Redis。