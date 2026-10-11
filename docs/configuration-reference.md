# MOGO 配置参考

本文档枚举所有公开配置项，来源为 `services/chat-api/app/core/config.py` 的 Settings 模型。

## 运行时配置

| 键 | 类型 | 默认值 | 必填 | 敏感 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `PROJECT_NAME` | str | `MOGO` | 否 | 否 | 项目名称，显示在 UI 和 API 响应中 |
| `API_V1_STR` | str | `/api/v1` | 否 | 否 | API 路由前缀 |
| `ALLOWED_ORIGINS` | str | `http://localhost:3000,http://localhost:8080` | 否 | 否 | CORS 允许的源，逗号分隔 |
| `DEBUG` | bool | `false` | 否 | 否 | 调试模式，启用详细日志和文档端点 |
| `LOG_LEVEL` | str | `INFO` | 否 | 否 | 日志级别（DEBUG/INFO/WARNING/ERROR） |

## 日志配置

| 键 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `LOG_FILE_ENABLED` | bool | `false` | 启用文件日志 |
| `LOG_FILE_PATH` | str | `backend.log` | 日志文件路径 |
| `LOG_FILE_FORMAT` | str | `json` | 日志格式（json/text） |
| `LOG_CONSOLE_PRETTY` | bool | `true` | 控制台日志美化输出 |
| `LOG_CAPTURE_PRINTS` | bool | `true` | 捕获 print 语句到日志 |
| `LOG_DEBUG_PAYLOADS` | bool | `false` | 记录 LLM 请求/响应 payload |
| `LOG_REQUEST_HEARTBEAT_SECONDS` | int | `15` | 请求心跳间隔（秒） |
| `LOG_SLOW_SPAN_MS` | int | `10000` | 慢 span 阈值（毫秒） |

## LLM 模型配置

### OpenAI

| 键 | 类型 | 默认值 | 敏感 | 说明 |
| --- | --- | --- | --- | --- |
| `OPENAI_API_KEY` | str | `""` | ✅ | OpenAI API 密钥 |
| `OPENAI_BASE_URL` | str | `https://api.openai.com/v1` | 否 | API 端点 |
| `OPENAI_MODEL` | str | `gpt-3.5-turbo` | 否 | 默认模型 |
| `OPENAI_MODEL_GENERAL` | str | `gpt-5.2` | 否 | 通用任务模型 |
| `OPENAI_MODEL_CHAT` | str | `gpt-5.2-chat` | 否 | 对话模型 |
| `OPENAI_MODEL_CODING` | str | `gpt-5.3-codex` | 否 | 编码模型 |

### Azure OpenAI

| 键 | 类型 | 默认值 | 敏感 | 说明 |
| --- | --- | --- | --- | --- |
| `USE_AZURE` | bool | `false` | 否 | 启用 Azure OpenAI |
| `AZURE_OPENAI_ENDPOINT` | str | `""` | 否 | Azure 端点 |
| `AZURE_OPENAI_API_VERSION` | str | `2023-05-15` | 否 | API 版本 |
| `AZURE_DEPLOYMENT_NAME` | str | `""` | 否 | 默认部署名 |

### Qwen (DashScope)

| 键 | 类型 | 默认值 | 敏感 | 说明 |
| --- | --- | --- | --- | --- |
| `USE_QWEN` | bool | `false` | 否 | 启用 Qwen |
| `QWEN_API_KEY` | str | `""` | ✅ | DashScope API 密钥 |
| `QWEN_BASE_URL` | str | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 否 | API 端点 |
| `QWEN_MODEL` | str | `qwen-plus` | 否 | 默认模型 |

### 多模态视觉

| 键 | 类型 | 默认值 | 敏感 | 说明 |
| --- | --- | --- | --- | --- |
| `USE_MULTIMODAL` | bool | `true` | 否 | 启用多模态 |
| `DASHSCOPE_API_KEY` | str | `""` | ✅ | DashScope 密钥 |
| `VISION_BASE_URL` | str | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 否 | API 端点 |
| `VISION_MODEL` | str | `qwen3-vl-plus` | 否 | 视觉模型 |
| `VISION_ENABLE_THINKING` | bool | `true` | 否 | 启用思考模式 |
| `VISION_THINKING_BUDGET` | int | `81920` | 否 | 思考 token 预算 |

## 搜索与爬虫

| 键 | 类型 | 默认值 | 敏感 | 说明 |
| --- | --- | --- | --- | --- |
| `SERPAPI_API_KEY` | str | `""` | ✅ | SerpAPI 密钥 |
| `SERPER_API_KEY` | str | `""` | ✅ | Serper API 密钥 |
| `TAVILY_API_KEY` | str | `""` | ✅ | Tavily API 密钥 |
| `BAIDU_QIANFAN_API_KEY` | str | `""` | ✅ | 百度千帆密钥 |
| `ARK_API_KEY` | str | `""` | ✅ | 火山引擎方舟密钥 |

## 上传限制

| 键 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `MAX_UPLOAD_IMAGE_BYTES` | int | `52428800` | 图片上传上限（50MB） |
| `MAX_UPLOAD_FILE_BYTES` | int | `104857600` | 文件上传上限（100MB） |
| `MAX_UPLOAD_DOCUMENT_BYTES` | int | `209715200` | 文档上传上限（200MB） |

## 文档处理

| 键 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `DOCUMENT_PROCESSING_BASE_URL` | str | `http://127.0.0.1:8200` | 文档解析服务地址 |
| `DOCUMENT_PROCESSING_SERVICE_TOKEN` | str | `""` | 文档解析服务令牌 |
| `DOCUMENT_PROCESSING_TIMEOUT_SECONDS` | float | `30.0` | 解析超时（秒） |
| `DOCUMENT_PROCESSING_SYNC_PARSE_TIMEOUT_SECONDS` | float | `180.0` | 同步解析超时（秒） |

## 知识库

| 键 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `KNOWLEDGE_STORAGE_TYPE` | str | `local` | 存储类型（local/oss） |
| `KNOWLEDGE_LOCAL_STORAGE_DIR` | str | `../admin-api/data/knowledge-documents` | 本地存储目录 |
| `KNOWLEDGE_OSS_BUCKET` | str | `""` | OSS bucket 名称 |
| `KNOWLEDGE_OSS_ENDPOINT` | str | `""` | OSS 端点 |
| `KNOWLEDGE_CANDIDATES_API_URL` | str | `""` | 知识检索 API 地址 |
| `KNOWLEDGE_CANDIDATES_TIMEOUT_SECONDS` | float | `20.0` | 检索超时（秒） |
| `KNOWLEDGE_CANDIDATES_MIN_RERANK_SCORE` | float | `10.0` | 最小重排分数 |

## 功能开关

| 键 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `ENABLE_BROWSER_PLANNING` | bool | `true` | 启用浏览器规划 |
| `ENABLE_CODING_PLANNING` | bool | `true` | 启用编码规划 |
| `PLAN_ONLY_MODE` | bool | `false` | 仅规划模式（不执行） |
| `PIPELINE_MODE` | str | `task_network` | 流水线模式 |
| `USE_MOCK_DATA` | bool | `false` | 使用模拟数据 |
| `DEBUG_ARTIFACTS_ENABLED` | bool | `false` | 启用调试工件 |
| `DEBUG_ARTIFACT_RETENTION_DAYS` | int | `7` | 工件保留天数 |

## 数据库配置

| 键 | 类型 | 默认值 | 敏感 | 说明 |
| --- | --- | --- | --- | --- |
| `MONGODB_URI` | str | `mongodb://localhost:27017` | ✅ | MongoDB 连接串 |
| `MONGODB_DB` | str | `mogo` | 否 | 数据库名称 |

## Token 使用统计

| 键 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `TOKEN_USAGE_PUSH_ENABLED` | bool | `false` | 启用用量推送 |
| `TOKEN_USAGE_PUSH_URL` | str | `""` | 推送目标 URL |
| `TOKEN_USAGE_PUSH_TIMEOUT_SECONDS` | float | `2.0` | 推送超时（秒） |
| `TOKEN_USAGE_QUEUE_SIZE` | int | `512` | 队列大小 |

## 慢查询阈值

| 键 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `LLM_SLOW_MS` | int | `30000` | LLM 调用慢阈值（毫秒） |
| `TOOL_SLOW_MS` | int | `20000` | 工具调用慢阈值（毫秒） |
| `DB_SLOW_MS` | int | `3000` | 数据库慢查询阈值（毫秒） |
| `PRESENTATION_PAGE_SLOW_MS` | int | `20000` | 演示页面慢阈值（毫秒） |

## 环境变量文件

完整的环境变量示例见 `services/chat-api/.env.example`。

## 配置优先级

1. 环境变量（最高优先级）
2. `.env` 文件
3. Settings 模型默认值（最低优先级）

## 敏感配置清单

以下配置项包含敏感信息，不应提交到版本控制：

| 键 | 类型 | 说明 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 密钥 | OpenAI API 访问凭证 |
| `QWEN_API_KEY` | 密钥 | DashScope API 访问凭证 |
| `DASHSCOPE_API_KEY` | 密钥 | DashScope 多模态凭证 |
| `SERPAPI_API_KEY` | 密钥 | SerpAPI 访问凭证 |
| `SERPER_API_KEY` | 密钥 | Serper API 访问凭证 |
| `TAVILY_API_KEY` | 密钥 | Tavily API 访问凭证 |
| `BAIDU_QIANFAN_API_KEY` | 密钥 | 百度千帆访问凭证 |
| `ARK_API_KEY` | 密钥 | 火山引擎方舟凭证 |
| `MONGODB_URI` | 连接串 | 含数据库凭证 |
| `DOCUMENT_PROCESSING_SERVICE_TOKEN` | 令牌 | 内部服务令牌 |
| `TUSHARE_TOKEN` | 令牌 | Tushare 金融数据凭证 |
| `TIANYANCHA_TOKEN` | 令牌 | 天眼查 API 凭证 |

## 配置校验

启动时 Settings 模型会自动校验类型和必填项。无效配置会导致服务启动失败。

```bash
# 验证配置
python -c "from app.core.config import Settings; Settings()"
```

## 更多文档

- [安装指南](installation-guide.md)
- [部署指南](docker-deployment.md)
- [故障排查](TROUBLESHOOTING.md)
