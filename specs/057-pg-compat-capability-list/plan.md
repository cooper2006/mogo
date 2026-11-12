# Plan: pg_compat 能力清单与 CI 静态扫描（057-pg-compat-capability-list）

**Input**: `specs/057-pg-compat-capability-list/spec.md`

**Created**: 2026-11-12

## 实施范围

### 新增文件

| 路径 | 用途 |
|---|---|
| `services/admin-api/app/core/pg_compat_manifest.py` | 能力清单常量（SUPPORTED_AGGREGATION_STAGES / UNSUPPORTED_STAGE_EXPLANATIONS） |
| `scripts/check_pg_compat_pipeline_stages.py` | CI 静态扫描脚本（AST 级管道阶段提取） |
| `docs/pg-compat-capability-baseline.md` | 全仓 aggregate 调用基线报告（首轮生成后手动维护） |
| `services/admin-api/app/api/endpoints/compatibility.py` | `/api/v1/admin/compatibility/pipeline-support` 端点 |
| `services/admin-api/tests/test_pg_compat_manifest.py` | 清单常量的单测 |

### 修改文件

| 路径 | 变更内容 |
|---|---|
| `services/admin-api/app/core/pg_compat.py` | 顶部新增 import manifest 常量；分派逻辑加结构化 warning 日志 |
| `.githooks/pre-commit` | 新增调用 `check_pg_compat_pipeline_stages.py --staged` |
| `.github/workflows/quality-gate.yml` | 新增 `pg-compat-scan` job |

### 不修改的文件

- `services/admin-api/app/core/column_map.py`（R3 扁平化逻辑不动）
- 任何业务代码中的 aggregate 调用点（由后续迭代按需修复，本特性只做发现和阻断）

## 实施步骤

### Phase 1：清单常量与文档

1. 在 `pg_compat.py` 顶部新增 `SUPPORTED_AGGREGATION_STAGES` frozenset 常量（当前 7 个：match/sort/limit/skip/count/group/project）
2. 新增 `UNSUPPORTED_STAGE_EXPLANATIONS` dict，为已知 unsupported 阶段填写原因说明
3. 写 `tests/test_pg_compat_manifest.py`：断言常量存在、内容正确、与处理器数一致
4. 运行一次全仓扫描（不门禁），输出基线报告到 `docs/pg-compat-capability-baseline.md`

### Phase 2：静态扫描脚本

5. 新建 `scripts/check_pg_compat_pipeline_stages.py`：
   - 支持 `--full`（全仓）和 `--staged`（仅 staged diff）两种模式
   - 用 ast.parse 解析 Python 源码，找 `aggregate(...)` 调用点的管道列表
   - 对每个管道中的 dict key 做 `$` 前缀剥离，得到阶段名
   - 与 SUPPORTED_AGGREGATION_STAGES 比较，报告未支持的阶段
6. 本地运行脚本，验证对现有代码库 exit 0（存量绕过点不在本次扫描范围内，见 R-5）
7. 把脚本注册到 `.githooks/pre-commit`（staged 模式）

### Phase 3：运行时守卫增强

8. 在 `pg_compat.py:_dispatch_stage()` 或等效分派处，对未知阶段先打 structured warning log（含文件名、行号、stage name），再抛 `PgCompatUnsupported`
9. 写单测：mock collection，传入含 `$unwind` 的管道，断言警告日志包含推荐替代方案文本

### Phase 4：Admin API 端点

10. 新建 `services/admin-api/app/api/endpoints/compatibility.py`，注册到 `admin-api/app/main.py`
11. 端点逻辑：import `SUPPORTED_AGGREGATION_STAGES`，调 `scripts/check_pg_compat_pipeline_stages.py --full --json`，返回 JSON
12. 加 admin RBAC 守卫（需 `admin:compatibility:read` 权限）
13. 写单测：mock 文件系统下的违规文件，断言响应 JSON 结构正确

### Phase 5：CI 集成与文档

14. 在 `.github/workflows/quality-gate.yml` 的 `backend-quality` job 中新增 step：`python scripts/check_pg_compat_pipeline_stages.py --full`
15. 确保 baseline 文档已更新（第 1 轮运行结果）
16. 更新 `specs/INDEX.md`

## 依赖关系

```
Phase 1 (constants/docs) ──→ Phase 2 (scan script) ──→ Phase 5 (CI)
                              ↑
Phase 3 (runtime guard) ─────┘（可与 Phase 2 并行）
                              ↓
                        Phase 4 (API endpoint)
```

## 测试策略

| 测试类型 | 位置 | 覆盖重点 |
|---|---|---|
| 单测 | `tests/test_pg_compat_manifest.py` | 常量正确性、与处理器数对齐 |
| 单测 | `tests/test_pg_compat_runtime_guard.py` | 未知阶段的 warning log + 异常抛出 |
| 契约测试 | `GET /api/v1/admin/compatibility/pipeline-support` | JSON schema 符合 spec |
| CI 冒烟 | 提交含 `$unwind` 的 mock PR | `pg-compat-scan` job fail |
| 回归 | admin-api 全部既有测试 | 无新增 failure |

## 风险与回滚

- **False positive**：动态拼接的 pipeline（`pipeline = build(); coll.aggregate(pipeline)`）无法静态识别。处理策略：扫描器对这类 case 标为 `dynamic_pipeline`，不阻断但列出供人工审查（不在 fail-open scan 的 exit 1 范围内）
- **Pre-commit 性能**：全仓扫描约 30-50ms（小仓库），不影响开发体验
- **回滚**：`.githooks/pre-commit` 中注释掉该 hook 即可临时绕过；manifest 常量为纯读操作，不会引入 bug
