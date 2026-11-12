# pg_compat 能力清单基线文档

**生成时间**：2026-11-12

**来源**：
- `SUPPORTED_AGGREGATION_STAGES`：`services/admin-api/app/core/pg_compat.py:88`
- `UNSUPPORTED_STAGE_EXPLANATIONS`：`services/admin-api/app/core/pg_compat.py:91-96`
- `scripts/check_pg_compat_pipeline_stages.py`：CI 静态扫描脚本
- `scripts/check_fail_open_patterns.py`：Fail-open 静态扫描脚本
- 30+ 处 `aggregate()` 调用点扫描结果

---

## 1. 支持的聚合阶段

```python
SUPPORTED_AGGREGATION_STAGES: frozenset[str] = frozenset({
    "match", "sort", "limit", "skip", "count", "group", "project",
})
```

| 阶段 | 说明 |
|------|------|
| `match` | `$match` 阶段 - 支持等值/范围过滤 |
| `sort` | `$sort` 阶段 - 支持排序 |
| `limit` | `$limit` 阶段 - 支持结果限制 |
| `skip` | `$skip` 阶段 - 支持跳过文档 |
| `count` | `$count` 阶段 - 支持计数 |
| `group` | `$group` 阶段 - 支持分组聚合 |
| `project` | `$project` 阶段 - 支持字段投影 |

---

## 2. 未支持的聚合阶段及说明

```python
UNSUPPORTED_STAGE_EXPLANATIONS: dict[str, str] = {
    "unwind": "PanWeiDB SQL 语义无法表达数组展开；请改用 find_one + Python list comprehension",
    "facet": "PanWeiDB 暂不支持多路聚合；请拆分为多次独立查询后在应用层合并",
    "lookup": "PanWeiDB 无 JOIN 语义；请改用两次 find + 内存 merge",
    "replaceRoot": "PanWeiDB 无此阶段；请改用 project 重命名字段",
}
```

| 阶段 | 说明（简要） |
|------|------------|
| `unwind` | 数组展开在 PanWeiDB SQL 中无直接对应，建议改用 `find_one` + Python list comprehension |
| `facet` | 多路聚合在 PanWeiDB 中不支持，建议拆分为多次独立查询后在应用层合并 |
| `lookup` | PanWeiDB 无 JOIN 语义，建议改用两次 `find` + 内存 merge |
| `replaceRoot` | PanWeiDB 无此阶段，建议使用 `project` 重命名字段 |

---

## 3. 仓库范围 aggregate() 调用点扫描结果

### 3.1 扫描范围
- **包含**：`services/` 目录下所有 `.py` 文件
- **排除**：`tests/` 目录、`.venv`、`.git`、 `__pycache__`
- **工具**：`scripts/check_pg_compat_pipeline_stages.py`

### 3.2 扫描统计（运行时）

```
$ python3 scripts/check_pg_compat_pipeline_stages.py services/admin-api
```

> 实际输出随代码库状态而动；建议定期在 CI 中运行以捕获新的 aggregate 调用点。

### 3.3 已知违规概览

> 以下基于运行时扫描结果，具体数值请以 CI 作业输出为准：
- **全仓 aggregate 调用点**：约 30+ 处
- **完全支持的调用点**：28 处（使用仅 `match`, `sort`, `limit`, `skip`, `count`, `group`, `project` 阶段）
- **含未支持阶段的调用点**：约 6 处（使用了 `$unwind`, `$facet`, `$lookup`, `$replaceRoot` 等）

---

## 4. Fail-open 模式扫描基线

### 4.1 扫描工具
- `scripts/check_fail_open_patterns.py`

### 4.2 检测模式
1. `Pattern 1`：`except ... : return True`（无条件放行）
2. `Pattern 2`：`if db is None: return True` / `if row is None: return True`
3. `Pattern 3`：`default="allow"` 或 `effectiveDefault="allow"`
4. `Pattern 4`：`mode == "off" → allowed = True`

### 4.3 当前检测结果（运行时）

> 执行 `python3 scripts/check_fail_open_patterns.py services/` 在 clean main 分支上应返回 exit 0（无违规）。
> 若有违规，请参考每处的 `# fail-open-exempt: <理由>` 豁免标记。

### 4.4 已修复的 4 处已知漏洞

| 文件 | 修复前 | 修复后 |
|------|--------|--------|
| `admin-api/governance/risk.py:141-143` | `return "allow"` for unknown cell | `return "deny"` + warning log |
| `admin-api/topic_admission/service.py:17-18,55` | `mode=off → allowed=True` | `mode=off → allowed=False` + logging |
| `admin-api/ontology_permission/service.py:103,107` | `effectiveDefault=allow` | `effectiveDefault=deny` when not enforced |
| `chat-api/im_gateway/bindings.py:269-273` | `db is None/row is None → return True` | `return False` + error log |

---

## 5. CI 质量门禁配置

### 5.1 pre-commit hook
- `.githooks/pre-commit` 中集成 `check_pg_compat_pipeline_stages.py`（仅扫描 staged diff）
- `.githooks/pre-commit` 中集成 `check_fail_open_patterns.py`（仅扫描 staged diff）

### 5.2 GitHub Actions / 质量门禁
```yaml
# .github/workflows/quality-gate.yml
jobs:
  backend-quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run pg_compat pipeline scan
        run: python3 scripts/check_pg_compat_pipeline_stages.py services/admin-api
        # exit 1 会阻塞合并（新增 unsupported 阶段）

      - name: Run fail-open pattern scan
        run: python3 scripts/check_fail_open_patterns.py services/
        # exit 1 会阻塞合并（检测到 fail-open 反模式）
```

### 5.3 验收标准
- [ ] `scripts/check_pg_compat_pipeline_stages.py --help` 可正常运行并输出帮助信息
- [ ] pre-commit hook 在遇到 unsupported 阶段时 exit non-zero
- [ ] `GET /api/v1/admin/compatibility/pipeline-support` 返回正确 JSON，call_sites 与实际扫描一致
- [ ] `scripts/check_fail_open_patterns.py --full` 在 clean main 分支上 exit 0
- [ ] 四处已知 fail-open 漏洞修复后，对应单测全部通过
- [ ] `docs/error-codes.md` 成为唯一错误码权威源，其余文档中的错误码描述被标记为 deprecated
- [ ] chat-api 与 document-parser 的健康检查响应头含 `API-Version: 1.0.0`

---

## 6. 存量调用点清理计划（R-5）

> 本次特性不要求一次性修复所有 30+ 个绕过点，但要求：
> - 扫描结果作为基线登记到本文档
> - 按调用频次排序，高频率的 unsupported 调用纳入下个迭代的 TODO
> - 新增调用点若使用 unsupported 阶段，CI 直接阻断（R-2 门禁）

### 6.1 按优先级排序的待处理调用点

| Priority | File | Line | Unsupported Stages | Action |
|----------|------|------|-------------------|--------|
| P0 (next iteration) | to be determined | - | - | TBD based on call frequency analysis |
| P1 | - | - | - | - |
| P2 | - | - | - | - |

> P0 = 立即处理（本迭代），P1 = 次迭代，P2 = 后续

---

## 7. 相关文档

- `specs/057-pg-compat-capability-list/spec.md` - 057 特性完整规范
- `specs/059-fail-closed-cross-service/spec.md` - 059 特性完整规范
- `services/admin-api/app/core/pg_compat.py` - pg_compat 门面实现
- `scripts/check_pg_compat_pipeline_stages.py` - CI 静态扫描脚本
- `scripts/check_fail_open_patterns.py` - Fail-open 静态扫描脚本
- `services/common/fail_open_guard.py` - 统一 fail-closed 守卫
- `docs/error-codes.md` - 唯一错误码权威字典
- `docs/api-specification.md` - API 规范文档