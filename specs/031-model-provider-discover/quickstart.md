# Quickstart: 模型供应商发现与多协议接入（获取模型列表 + Anthropic/Gemini/Ollama）

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Tasks**: [tasks.md](./tasks.md)

**用途**: 本文件是**可执行的验证清单**。覆盖「获取模型列表」端到端、后端五协议 discover 归一化、种子供应商与首次向导字段提示三类场景。本特性已于 2026-10-18 按 T001–T018 落地（commit `6ea16f3` 起；admin-api `tests/test_models_discover.py` 11/11 全绿）。

> 前置：admin-api 已配置至少一个 provider 的 Base URL + API Key（Ollama 本地可无 Key）。

## 0. 前置

```bash
cd services/admin-api    # 后端 discover 端点
cd apps/admin-web        # 前端「获取列表」弹窗 + 首次向导
pnpm install             # 若依赖未装
```

## 1. 验证清单

### 1.1 新增模型配置「获取列表」点选保存（US1 / FR-001–FR-006）

1. 管理员在 admin-web「模型管理 → 新增模型配置」选好供应商、填好 Base URL 与 API Key。
2. 点「获取列表」→ 后端按 `providerType` 分发到对应 discover 函数，返回去重后的模型清单。
3. 前端弹窗逐行展示（模型 ID / 名称 / 提供方），点选一项 → 模型 ID 回填表单并关闭弹窗，其余字段不变。
4. 填配置名称保存 → 全程无需手敲模型 ID。

### 1.2 后端 discover 覆盖五类协议（US2 / FR-002–FR-004）

1. `providerType=anthropic` → 返回 `[{id:"claude-3-5-sonnet-20241022", name:"claude-3-5-sonnet-20241022", ownedBy:"anthropic"}]`。
2. `providerType=gemini` → 返回项 `id` 为去掉 `models/` 前缀的 `gemini-1.5-pro`。
3. `providerType=ollama`（`/api/tags`）→ 返回 `[{id:"llama3.1", name:"llama3.1", ownedBy:"ollama"}]`。
4. 任意协议列表出现重复 id → 结果去重。
5. provider 列表接口返回 4xx/5xx 或不可达 → 后端返回 502 并附可读错误，前端提示拉取失败而不静默卡死。
6. `providerType` 为未知值（如 `foo`）→ pydantic 校验层返回 422，不进分发逻辑。

### 1.3 种子供应商 + 首次向导字段提示（US3 / FR-005 / FR-007–FR-008）

1. `DEFAULT_PROVIDERS` 种子含 Anthropic / Gemini / Ollama 三条（`provider_type` 分别为 `anthropic`/`gemini`/`ollama`，`auth_type` 为 `api_key`/`api_key`/`none`）。
2. 首次向导切到 Anthropic → Base URL 占位符 `https://api.anthropic.com`，提示以 `/v1/models` 拉清单、需 `x-api-key`。
3. 切到 Gemini → 占位符 `https://generativelanguage.googleapis.com`，提示 Key 经 URL 参数传递。
4. 切到 Ollama → 占位符 `http://localhost:11434`，API Key 字段提示「本地部署默认无需 API Key，可留空」。
5. 连接测试（`_provider_test_events`）对 anthropic/gemini/ollama 各提供非流式一次性测试分支，复用 `_decrypt_api_key` / `_build_ssl_context`。

## 2. 自动化验证

```bash
# 后端：五协议解析 + 错误转 502 + 路由分发 + 未知类型 422
cd services/admin-api
python -m pytest tests/test_models_discover.py -q
# 预期: 11 passed

# 前端：首次向导 SetupModelFields 单文件编译通过（Base URL 占位符随 provider_type 变化）
cd apps/admin-web
pnpm exec vue-tsc --noEmit -p tsconfig.app.json
# 预期: exit 0
```

## 3. 回滚

本特性为"获取列表"辅助能力，无数据迁移。回滚只需：

- 移除 admin-api `models.py` 的 `_discover_anthropic/gemini/ollama_models` 与 `_anthropic/gemini/ollama_test_events` 分支。
- 从 `model_repository.py` 的 `DEFAULT_PROVIDERS` 种子删除三条新协议条目（provider_type 退回到 `openai_compatible` / `azure_openai`）。
- 回退 admin-web「获取列表」弹窗与 `SetupModelFields` 的字段提示（用户改回手填模型 ID）。

回滚后既有 OpenAI/Azure 兼容供应商的 discover 不受影响。
