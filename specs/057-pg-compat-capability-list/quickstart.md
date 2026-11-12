# Quickstart: pg_compat 能力清单与 CI 静态扫描（057）

**Feature**: `specs/057-pg-compat-capability-list/spec.md`

## 背景

PanWeiDB 兼容层目前只实现了 7 个聚合阶段（match/sort/limit/skip/count/group/project），其余阶段（`$unwind`/`$facet`/`$lookup` 等）在运行期抛 `PgCompatUnsupported` 500。缺乏提前发现机制，导致 Mongo 下正常、上线后 500 的事故反复发生。

## 本特性交付物

| 交付物 | 位置 | 用途 |
|---|---|---|
| 能力清单常量 | `pg_compat.py:SUPPORTED_AGGREGATION_STAGES` | 唯一事实来源 |
| 静态扫描脚本 | `scripts/check_pg_compat_pipeline_stages.py` | CI/pre-commit 门禁 |
| Admin API 端点 | `GET /api/v1/admin/compatibility/pipeline-support` | 可视化覆盖率面板 |
| 基线报告 | `docs/pg-compat-capability-baseline.md` | 存量违规盘点 |

## 快速验证

### 本地运行扫描器

```bash
cd /path/to/mogo

# 全仓扫描
python scripts/check_pg_compat_pipeline_stages.py --full

# 仅扫暂存区（模拟 pre-commit）
git add <modified-files>
python scripts/check_pg_compat_pipeline_stages.py --staged
```

预期：clean main 分支 exit 0（存量绕过点不计入本次阻断）。

### 触发一次违规（测试用）

```bash
# 临时在某个 .py 文件中加入 aggregate([{'$unwind': '$items'}])
# 然后 git add + commit → pre-commit hook 应拦截
```

### Admin API 面板

```bash
# 登录 admin 后访问
curl http://localhost:8000/api/v1/admin/compatibility/pipeline-support \
  -H "Authorization: Bearer <admin-token>"
```

返回 JSON 包含：
- `supported_stages`: 当前支持的阶段列表
- `call_sites`: 每处 aggregate 调用的详细状态
- `summary`: fully_supported / has_unsupported_stage 计数

## 增量补全指引

1. 打开 `docs/pg-compat-capability-baseline.md`，找到 `has_unsupported_stage: true` 的条目
2. 按 `recommended_fix` 列的指引改造对应调用点
3. 每修复一处，重新运行扫描器确认该条消失
4. 高频调用点优先（按 call_site 频次排序）

## 回滚

删除 `.githooks/pre-commit` 中的扫描器注册行即可临时关闭门禁；manifest 常量为纯读操作，移除不会影响运行时行为。
