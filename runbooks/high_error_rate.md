# 错误率升高

> 告警：`MogoErrorRateHigh`（P1，5xx 占比 > 1% 持续 10m）/ `MogoSloErrorBudgetFastBurn`（P1）
> 关联场景：接口大面积 5xx、前端操作失败率上升

## 1. 症状

- `mogo_http_errors_total` 增速上升，`status_class="5xx"` 占比 > 1%；
- 网关 / 应用日志出现堆栈或 `500 Internal Server Error`；
- 用户侧：操作失败、页面报错，但服务进程仍在（与 `service_not_ready` 区分）。

[只读排查]

```bash
# 定位是哪个服务、哪个路由在报错
curl -s 'http://127.0.0.1:9090/api/v1/query?query=sum by(path_template)(rate(mogo_http_errors_total[5m]))' | head -c 800
curl -s 'http://127.0.0.1:9090/api/v1/query?query=sum by(service,path_template)(rate(mogo_http_requests_total{status_class="5xx"}[5m]))' | head -c 800

# 服务日志里的异常聚合
docker compose logs --tail=500 chat-api | grep -E "Traceback|ERROR|Exception" | tail -40
```

## 2. 影响

- 按错误预算口径直接消耗可用性预算（SLO 99.9% → 每月约 43m 预算）；
- 若集中在写接口，**可能产生部分成功状态**（数据不一致），恢复后需对账。

## 3. 根因（按概率排序）

1. **下游依赖故障** — MongoDB / Redis / LLM provider 抖动被包装成 5xx。
   先看对应 runbook：`mongodb_unreachable.md`、`redis_stall.md`、`llm_timeout.md`。
2. **新发布引入缺陷** — 错误率在发布后突增。用 `docker compose ps` 的启动时间
   与错误率拐点对齐确认。
3. **数据库查询退化** — 缺索引 / 全表扫描导致超时并转 5xx（配合 `latency_regression.md`）。
4. **配置漂移** — 环境变量、密钥、上游 URL 被改错（401/403 通常被转成 5xx）。
5. **输入触发未捕获异常** — 特定 payload 打到边界条件（可复现、量不大但稳定）。

## 4. 恢复步骤

```bash
# A. 发布导致 → 回滚到上一个已知good镜像（会改状态）
git log --oneline -5
# 按 022 部署流程回滚，禁止直接 git reset --hard 到远端

# B. 单接口故障 → 网关侧临时摘除/熔断（会改状态）
grep -n "location\|proxy_pass" deploy/nginx/nginx.conf | head -30

# C. 依赖故障 → 转对应 runbook，不要在本场景里重复处置

# D. 输入触发 → 找到可复现 payload，加参数校验（改代码，走正常发布）
docker compose logs --tail=2000 chat-api | grep -B2 -A10 "Traceback" | tail -60
```

**禁止**：不要用「把 5xx 改成 4xx」来让告警消失——那只是把故障藏起来。

## 5. 验证

```bash
curl -s 'http://127.0.0.1:9090/api/v1/query?query=sum(rate(mogo_http_requests_total{status_class="5xx"}[5m]))/sum(rate(mogo_http_requests_total[5m]))'
# 期望回落到 < 1% 并连续 10m 保持
curl -s http://127.0.0.1:9093/api/v2/alerts | grep -i "MogoErrorRateHigh" || echo "已恢复"
```

## 6. 事后复盘模板

```markdown
### 复盘：错误率升高（YYYY-MM-DD）
- 发现 / 恢复时间，总时长，5xx 峰值占比：
- 影响的路由 Top3 与请求量：
- 预算消耗：本次占总预算的 X%（按 SLO target 计算）
- 是否产生数据不一致？对账结果：
- 改进项：
  - [ ] 该路径补充参数校验 / 单测
  - [ ] 发布增加错误率金丝雀门禁
  - [ ] 把该 5xx 归因映射为更准确的 4xx/503
```
