# 025 契约文件格式规范

US3（FR-16 ~ FR-24）的三份契约文件（`admin-api.yaml` / `chat-api.yaml` /
`document-parser.yaml`）与工具脚本（`tools/contract/validate.py`、`diff.py`、
`deprecation_check.py`）必须遵循本文件的统一约定。**契约由消费方定义**（FR-16），
只覆盖消费方代码**实际读取**的字段/状态码/错误码（FR-17），不覆盖"可能用到"的字段。

## 1. 文件位置与顶层结构

每份契约文件放在 `specs/025-api-contract-hardening/contracts/<service>.yaml`：

```yaml
name: admin-api            # 服务名，与 services/<name>/ 一致
version: "1.0.0"           # 契约自身版本（semver，非服务 API 版本）
provider: admin-api        # 提供方服务
consumers:                 # 消费方（谁定义并验证这份契约）
  - admin-web
  - user-web
base_path: /api            # 路由前缀（契约里 path 不含 base_path）
interactions: [...]        # 交互列表，见下
```

## 2. interactions 条目

每个消费方实际调用的端点一条；**同路径不同方法各一条**：

```yaml
- id: list_skills                # 全局唯一、kebab-case
  method: GET
  path: /skills
  summary: 列出 Skill（admin-web 管理页）
  query:                          # 仅实际发送的查询参数
    page: {type: int, required: false}
    page_size: {type: int, required: false}
    keyword: {type: str, required: false}
  request_headers:                # 仅实际发送的请求头
    Authorization: "Bearer <token>"
  responses:                      # 仅消费方代码处理的分支
    - status: 200
      content_type: application/json
      fields:                     # 实际读取的字段（FR-17）
        data: {type: array, item: object}
        data[].id: {type: str}
        data[].name: {type: str}
        total: {type: int}
      error_codes: []
      notes: admin-web Views/SkillsPage 依赖
    - status: 401
      error_codes: [api.unauthorized]
    - status: 422
      error_codes: [api.validation_error]
  notes: 分页 + 关键字过滤
```

## 3. 字段语法约定

- **类型**：`str` / `int` / `float` / `bool` / `object` / `array`；数组用
  `array` + `item: <type>`；对象字段用 `data[].id` 这种 JSONPath 风格键。
- **嵌套**：`section.inner.field`；数组元素 `data[].id`。
- **可选性**：字段级 `required: false` 表示可选；**新增字段必须标**
  `required: false`（FR-21，T033 容忍缺失）。
- **弃用**：字段或端点级 `deprecated: true` + `deprecated_since: "1.2.0"`（FR-22，
  T037 按此扫描观察期，默认 2 个 minor 版本后才允许移除）。
- **类型变更/删除字段/改状态码** = 不兼容（FR-18），diff.py 判红。

## 4. error_codes 语义

- 值必须是 `app/core/errors.py` 注册表的 `api.*` 稳定码（FR-11/FR-29）。
- 响应条目**只需列消费方实际分支处理的错误码**；未列表示消费方不区分处理。
- 非 2xx 条目可只写 `status` + `error_codes`，省略 `fields`。

## 5. 消费方视角约束（验收检查）

1. `fields` 里每条必须能在对应消费方源码里找到**实际读取**（TS/TSX/Vue 里
   `data.<field>`、`res.data.xxx`、`detail.code` 之类），不得凭 API 文档臆造。
2. `responses` 里的状态码必须是消费方 `catch`/`if`/错误提示里**实际分支**的。
3. 每条 interaction 在 `notes` 里写明来源（消费方文件 + 组件）。
4. 三份契约之间不得重复定义同一服务端点；每份只写本服务。