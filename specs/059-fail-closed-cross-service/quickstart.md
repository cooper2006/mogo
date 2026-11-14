# Quickstart: 跨服务 fail-closed 可机检约束（059）

**Feature**: `specs/059-fail-closed-cross-service/spec.md`

## 背景

四处已知漏洞在「未知/异常/未配置」场景下回退 allow，与宪法原则 III（Security and Data Protection）及 009/020 spec 的 fail-closed 语义冲突。虽然目前这些漏洞不在主路径上，但形成了不一致的治理模式，新增安全点会继续复制此问题。

## 变更摘要

| 文件 | 变更前 | 变更后 |
|---|---|---|
| `risk.py:_canon()` | unknown cell → `"allow"` | unknown cell → `"deny"` + warning log |
| `topic_admission/service.py` | `mode=off` → `allowed=True` | `mode=off` → `allowed=False` |
| `ontology_permission/service.py` | `effectiveDefault="allow"` | `effectiveDefault="deny"` |
| `im_gateway/bindings.py` | `db is None` → `return True` | retry 50ms → `return False` + error log |
| 新增 `fail_open_guard.py` | — | 统一 `enforce_fail_closed()` 工具函数 |
| 新增 `check_fail_open_patterns.py` | — | CI 静态扫描 fail-open 反模式 |
| `chat-api/main.py` | 无 ApiVersionMiddleware | 注册 `ApiVersionMiddleware("1.0.0")` |
| `document-parser/main.py` | 同上 | 同上 |
| `docs/error-codes.md` | 自称权威但未统一 | 明确声明唯一权威 + schema v2 |
| `docs/api-specification.md:51-80` | 独立错误码定义 | deprecated，指向 error-codes.md |

## 快速验证

### 单测

```bash
cd services/admin-api
pytest tests/test_risk_canon_fail_closed.py tests/test_topic_admission_mode_off.py \
       tests/test_ontology_enforcement.py -v

cd ../chat-api
pytest tests/test_im_gateway_bindings_fail_closed.py -v
```

### CI 扫描冒烟（测试新规则是否生效）

```bash
# 临时在某个文件中加一行 fail-open 反模式代码
echo 'if db is None: return True' >> /tmp/test_fo.py

# 运行扫描器
python scripts/check_fail_open_patterns.py --full /tmp/test_fo.py
# 预期 exit 1，输出违规行号
```

### API-Version 响应头

```bash
curl -I http://localhost:8000/healthz | grep -i api-version
# 预期: API-Version: 1.0.0

curl -I http://localhost:8001/healthz | grep -i api-version
# chat-api 同样预期 1.0.0
```

## 生产部署注意

**影响面评估**：
- `topic_admission mode=off`：若有线上部署用 mode=off 来「关闭检查」，改为 deny-by-default 会导致所有请求被拒。**部署前务必确认 mode=off 的真实语义是「禁用检查」还是「未配置」**
- `im_gateway db=None retry`：增加 50ms 延迟仅在 db 不可达时触发，正常路径零开销

**回滚**：
- 任意修复点均可单独 revert，不影响其他三点
- 如需紧急全量回滚，revert 整个 059 特性 commit 即可

## 豁免流程

若确有业务理由需要在某处保留 fail-open 行为：
1. 在代码行加上注释 `# fail-open-exempt: <作者名>/<理由>`
2. PR 需经 CODEOWNERS（security team）review 批准
3. 豁免条目登记到 `docs/fail-open-exemptions.md`（定期 review 清理）
