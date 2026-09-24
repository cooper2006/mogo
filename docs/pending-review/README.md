# 待确认清单（pending-review）

本目录收录代理在处理任务时**无法判断归属或用途**、或**需要用户确认才能决定去留**的文件。
遵循 `AGENTS.md` 的代理操作规约：不删除、不强行处理，先归档到本清单。

## 收录规则

- 代理发现的文件符合以下任一情况时，移入或登记到本目录：
  - 用途不明（既不是源码、也不是文档、也不像构建产物）
  - 疑似临时文件但不确定是否仍有价值
  - 与当前任务冲突，去留需要用户拍板
  - 重复、过时但不敢确认已废弃
- 禁止在本目录删除任何文件；只能新增条目或移除（移走）条目。

## 条目登记格式

每个待确认项在 `index.md` 登记一行：

| 字段 | 说明 |
|---|---|
| 文件路径 | 工作区相对路径 |
| 发现日期 | YYYY-MM-DD |
| 发现者 | 代理名称 / 任务名 |
| 疑点 | 为什么无法判断 |
| 建议 | 代理的建议处置（保留/删除/移动/重构），仅供参考 |
| 状态 | open / resolved |

## 处置流程

1. 用户审阅 `index.md` 条目
2. 用户对每项给出决定（保留 / 删除 / 移动 / 其他）
3. 代理按决定执行，并把条目状态改为 `resolved`
4. 被决定删除的文件由用户确认后，代理才执行删除（规约禁止代理自行删除）

---

`index.md` 为登记台账（下表）；具体待确认文件暂存于本目录子路径 `items/`。

## 登记台账（index.md）

| 文件路径 | 发现日期 | 发现者 | 疑点 | 建议 | 状态 |
|---|---|---|---|---|---|
| `services/chat-api/tests/services/test_session_versioning.py` | 2026-09-24 | DSH Agent（驾驶舱修复轮，提交前卫生检查） | `scripts/check_open_source_hygiene.py` 报 "possible AWS access key" 与 "possible OpenAI-compatible API key"。经查为测试夹具构造值：`AKIAIOSFODNN7EXAMPLE`（AWS 官方文档示例）、`sk-aB3xK9mQ2pL7wZ4tR8yU1iO6nM5vC0dF`（注释明确标注为 "long, high entropy" 的样本，用于验证 detect_secrets）。非真实凭据 | 保留。建议给卫生检查加测试目录/样例值白名单，或在这两行加 `# hygiene-check: allow` 类豁免注释 | open |
| `services/admin-api/tests/test_governance_pii.py` | 2026-09-24 | DSH Agent（同上） | 卫生检查报 "possible private key"。经查为 PII 脱敏测试的**输入样本**（`-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----`），必须包含敏感形态才能验证脱敏逻辑。非真实私钥 | 保留。同上，建议白名单或豁免注释 | open |

<!-- 新增条目追加到下表：
| 文件路径 | 发现日期 | 发现者 | 疑点 | 建议 | 状态 |
|---|---|---|---|---|---|
-->
