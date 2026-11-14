from __future__ import annotations

import re

from app.api.setup_status_messages import setup_service_label
from app.api.model_test_messages import localize_model_test_message


_ENGLISH_DETAILS = {
    "生成服务不可用": "The workflow generation service is unavailable",
    "润色服务不可用": "The workflow refinement service is unavailable",
    "检查服务不可用": "The workflow check service is unavailable",
    "检查失败": "Workflow check failed",
    "后端检查服务暂不可用，请稍后重试。": "The backend check service is temporarily unavailable. Try again later.",
    "本次未完成后端语义检查。": "The backend semantic check did not complete.",
    "本次未完成后端语义节点检查。": "The backend semantic node check did not complete.",
    "PPT 生成设置保存失败": "Failed to save presentation generation settings",
    "账号组下仍有账号，无法删除": "This account group still contains accounts and cannot be deleted",
    "系统内置账号不可删除": "Built-in system accounts cannot be deleted",
    "企业总 Token 必须大于 0": "The organization total token quota must be greater than zero",
    "员工默认 Token 必须大于 0": "The default employee token quota must be greater than zero",
    "图片生成数量 n 必须在 1 到 10 之间": "The number of images n must be between 1 and 10",
    "额外请求参数必须是 JSON 对象": "Additional request parameters must be a JSON object",
    "额外请求参数不能超过 20000 个字符": "Additional request parameters cannot exceed 20,000 characters",
    "工作流节点格式无效": "Invalid workflow node format",
    "工作流各步骤的输出名称不能重复": "Workflow step output names must be unique",
    "版本号应为 1.2.0 格式": "Use a version number in the format 1.2.0",
    "外部身份用户不能设置本地密码": "Externally managed users cannot set a local password",
    "请填写登录名": "Enter a login name",
    "请设置至少 10 位密码": "Set a password with at least 10 characters",
    "密码至少 10 位": "The password must be at least 10 characters",
    "正在连接 backend 模型运行时...": "Connecting to the backend model runtime...",
    "模型连接测试成功。": "Model connection test succeeded.",
    "图片生成测试成功。": "Image generation test succeeded.",
    "图片模型连接测试失败": "Image model connection test failed",
    "图片模型运行时返回了无效响应": "The image model runtime returned an invalid response",
    "连接成功": "Connection succeeded",
    "搜索连接测试成功": "Search connection test succeeded",
    "全能力管理员由系统维护，不能修改": "The full access administrator is managed by the system and cannot be changed",
    "全能力管理员不能停用": "The full access administrator cannot be disabled",
    "系统保障岗位角色不能删除": "System protected position roles cannot be deleted",
    "该岗位角色仍有员工，请先迁移员工": "This position role still has employees. Reassign them first.",
    "必须选择主要岗位角色": "Choose a primary position role",
    "岗位角色不存在或已停用": "Position role not found or disabled",
    "岗位角色不存在": "Position role not found",
    "岗位角色名称已存在": "Position role name already exists",
    "岗位角色名称不能为空": "Position role name is required",
    "邀请只能指定一个岗位角色；额外角色请在员工入职后单独设置": "An invitation can assign one position role. Add other roles after the employee joins.",
    "企业已有部门，请选择邀请员工所属部门": "Choose a department for the invited employee",
    "企业已有岗位角色，请选择主要岗位角色": "Choose a primary position role for the invited employee",
    "预览文件不存在": "Preview file not found",
    "文件路径无效": "Invalid file path",
    "文件不存在": "File not found",
    "OSS 存储配置不完整": "OSS storage configuration is incomplete",
    "OSS 依赖未安装，请安装 oss2": "OSS dependency is missing. Install oss2.",
    "ZIP 安装服务返回了无效结果": "The ZIP installation service returned an invalid result",
    "API Key 不能为空": "API key is required",
    "HTTP 工具不需要 MCP 工具名称": "An HTTP tool does not need an MCP tool name",
    "不能移动到自身或子部门下": "Cannot move a department into itself or one of its subdepartments",
    "不能移动到自身的子目录下": "Cannot move a directory into one of its subdirectories",
    "不能移动到自身目录": "Cannot move a directory into itself",
    "企业工具连接不存在": "Organization tool connection not found",
    "企业部门初始化异常，请联系管理员": "Department setup failed. Contact an administrator",
    "供应商ID无效": "Invalid provider ID",
    "供应商不存在或已禁用": "Provider not found or disabled",
    "包含未知的 Agent 能力": "Unknown Agent capability",
    "只有对话模型可以启用视觉输入": "Only chat models can enable vision input",
    "可选模型不能重复配置 chat 能力": "Only one optional model can have chat capability",
    "同一能力不能同时允许和禁止": "A capability cannot be both allowed and denied",
    "向量模型不存在、已禁用或不支持向量能力": "Embedding model not found, disabled, or unsupported",
    "员工登录名已存在": "Employee login name already exists",
    "员工默认 Token 不能超过企业总 Token": "Default employee tokens cannot exceed the organization total",
    "基础对话模型能力必须为 chat": "The base chat model must have chat capability",
    "失效时间必须晚于生效时间": "The end time must be later than the start time",
    "头像仅支持 JPG、PNG、WebP": "Avatar must be a JPG, PNG, or WebP image",
    "头像文件不能为空": "Choose an avatar file",
    "头像文件不能超过 2MB": "Avatar file must not exceed 2 MB",
    "头像文件内容无效": "Invalid avatar file content",
    "头像路径无效": "Invalid avatar path",
    "姓名不能为空": "Name is required",
    "字段key已存在": "Field key already exists",
    "字段不存在": "Field not found",
    "存在无效部门": "Invalid department in selection",
    "工具名称不能为空": "Tool name is required",
    "工具类型只支持 HTTP 接口或 MCP 服务": "Tool type must be an HTTP endpoint or MCP service",
    "当前企业本周期总额度为 0，不能为成员分配大于 0 的额度。请先配置企业总额度。": "The organization has no quota for this period. Set its total quota before assigning member quota.",
    "当前企业本周期总额度为 0，不能为用户分配大于 0 的额度。请先配置企业总额度。": "The organization has no quota for this period. Set its total quota before assigning user quota.",
    "当前密码不正确": "Current password is incorrect",
    "当前模型未启用图片生成能力": "Image generation is not enabled for this model",
    "当前用户未配置登录名": "The current user has no login name",
    "当前管理员租户ID仍为 default，请先配置真实租户ID后再生成邀请链接": "Set a real tenant ID before generating an invitation link",
    "当前邀请策略仅支持新用户注册，请联系管理员重置密码": "Invitations currently support new user registration only. Contact an administrator to reset the password.",
    "循环移动错误": "Cannot move a directory into a cycle",
    "技能名称不能为空": "Skill name is required",
    "技能类型无效": "Invalid skill type",
    "搜索服务未返回结果": "The search service returned no results",
    "搜索源不存在": "Search source not found",
    "搜索目录不存在": "Search directory not found",
    "文件类型不支持": "Unsupported file type",
    "文件超过大小限制": "File exceeds the size limit",
    "文档不存在或未删除": "Document not found or not deleted",
    "知识文档中已存在同名文件": "A knowledge document with this filename already exists",
    "请选择 ZIP 格式的 Skill 安装包": "Select a Skill package in ZIP format",
    "Skill ZIP 不能超过 100 MiB": "Skill ZIP must not exceed 100 MiB",
    "文档尚未完成分段，无法索引": "Document segmentation is incomplete; indexing is unavailable",
    "文档或索引任务不存在": "Document or indexing task not found",
    "文档或解析任务不存在": "Document or parsing task not found",
    "文档或转换任务不存在": "Document or conversion task not found",
    "文档正在学习中，请勿重复提交": "Document learning is in progress. Do not submit it again.",
    "文档正在索引中，请勿重复提交": "Document indexing is in progress. Do not submit it again.",
    "文档状态无效": "Invalid document status",
    "新密码不能与当前密码相同": "The new password must differ from the current password",
    "无权查看该记录": "You do not have access to this record",
    "无权限查看其他企业数据": "You do not have access to another organization's data",
    "未找到对应的调用记录": "Matching call record not found",
    "根部门不可删除": "The root department cannot be deleted",
    "模型供应商ID无效": "Invalid model provider ID",
    "模型配置创建失败": "Failed to create model configuration",
    "每种可选模型只能配置一个": "Only one model can be configured for each optional capability",
    "父目录不存在": "Parent directory not found",
    "特殊授权不存在": "Special authorization not found",
    "状态只支持 active 或 disabled": "Status must be active or disabled",
    "用户ID不一致": "User IDs do not match",
    "用户ID无效": "Invalid user ID",
    "目标父目录不存在": "Target parent directory not found",
    "目标目录下已存在同名目录": "A directory with this name already exists at the destination",
    "管理员账号和员工账号不能相同": "Admin and employee usernames must be different",
    "该外部身份已被绑定": "This external identity is already linked",
    "该工具正在被知识库配置引用。请先切换知识检索来源或更换工具并保存，再删除。": "This tool is used by a knowledge configuration. Change the retrieval source or tool and save before deleting it.",
    "该文档类型无需生成预览": "This document type does not need a preview",
    "该目录存在子目录，无法删除": "This directory has subdirectories and cannot be deleted",
    "该目录或其子目录下存在知识文档，无法删除": "This directory or its subdirectories contain knowledge documents and cannot be deleted",
    "该部门下仍有用户": "This department still has users",
    "请先保存并启用搜索源": "Save and enable the search source first",
    "请先删除子部门": "Delete subdepartments first",
    "请先发布 Skill，再启用": "Publish the Skill before enabling it",
    "请先在 HTTP 工具中声明文本入参，并选择用户问题传入字段": "Declare a text input in the HTTP tool and select the field for the user's question",
    "请先选择本企业已启用的工具": "Select an enabled tool from this organization first",
    "请填写姓名": "Enter a name",
    "请填写登录名": "Enter a login name",
    "请选择有效的向量模型": "Choose a valid embedding model",
    "请选择有效的重排模型": "Choose a valid rerank model",
    "请选择此 MCP 服务中已启用的检索工具": "Choose an enabled retrieval tool from this MCP service",
    "请选择该 MCP 工具已声明的文本入参作为用户问题传入字段": "Choose a declared text input of this MCP tool for the user's question",
    "账号ID无效": "Invalid account ID",
    "账号组ID无效": "Invalid account group ID",
    "账号组创建失败，请重试": "Failed to create account group. Try again.",
    "身份绑定不存在": "Identity link not found",
    "邀请ID无效": "Invalid invitation ID",
    "邀请不存在": "Invitation not found",
    "邀请不存在或已失效": "Invitation not found or invalid",
    "邀请所属租户ID无效，请联系管理员重新生成邀请链接": "The invitation has an invalid tenant ID. Ask an administrator for a new link.",
    "邀请链接不存在或已失效": "Invitation link not found or invalid",
    "邀请链接已过期": "Invitation link has expired",
    "重排模型不存在、已禁用或不支持重排能力": "Rerank model not found, disabled, or unsupported",
    "预览文件正在生成中，请勿重复提交": "Preview generation is in progress. Do not submit it again.",
    "默认部门不存在或已停用": "Default department not found or disabled",
    "默认部门不存在或已停用，请联系管理员重发邀请": "Default department not found or disabled. Ask an administrator to resend the invitation.",
    "工具连接不存在": "Tool connection not found",
    "模型配置不存在": "Model configuration not found",
    "模型配置ID无效": "Invalid model configuration ID",
    "用户不存在": "User not found",
    "技能不存在": "Skill not found",
    "登录名已存在": "Login name already exists",
    "登录账号已存在": "Login account already exists",
    "账号组不存在": "Account group not found",
    "账号不存在": "Account not found",
    "部门不存在": "Department not found",
    "父部门不存在": "Parent department not found",
    "目录不存在": "Directory not found",
    "文档不存在": "Document not found",
    "模型配置已存在": "Model configuration already exists",
    "邀请用户不存在": "Invited user not found",
    "请填写邮箱": "Enter an email address",
    "请填写手机号": "Enter a phone number",
    "同级线下已存在同名目录": "A directory with this name already exists at this level",
    "$in/$nin 需要一个数组": "`$in`/`$nin` require an array",
    "$inc 只支持数值增量": "`$inc` only supports numeric increments",
    "049：quota_projects 写路径已退役，项目由 user-web 创建（见 ADR-9）": "049: the quota_projects write path has been retired; projects are created by user-web (see ADR-9)",
    "Key 不存在或已撤销": "The key does not exist or has been revoked",
    "MOGO_DATA_BACKEND=panweidb 时不能调用 init_db()：psycopg 的异步连接必须在事件循环内建立，请改为 await init_backend()。": "init_db() cannot be called when MOGO_DATA_BACKEND=panweidb: psycopg async connections must be created inside the event loop. Use await init_backend() instead.",
    "PanWeiDB 连接池尚未初始化": "The PanWeiDB connection pool has not been initialized",
    "PanWeiDB 连接池尚未初始化：启动时应 await app.core.db.init_backend()": "The PanWeiDB connection pool has not been initialized: await app.core.db.init_backend() during startup",
    "SSO 凭证已过期，请重新进入": "The SSO credential has expired. Please sign in again",
    "SSO 凭证无效": "The SSO credential is invalid",
    "SSO 凭证格式不正确": "The SSO credential format is invalid",
    "SSO 凭证签名无效": "The SSO credential signature is invalid",
    "community 版为无限成员版本，不支持设置成员上限": "The community edition is an unlimited-member edition and does not support a member limit",
    "create_index 需要至少一个字段": "create_index requires at least one field",
    "max_cases 至少为 1": "max_cases must be at least 1",
    "min_cases 至少为 1": "min_cases must be at least 1",
    "tenant_id / profile_version / model_instance_id 均为必填": "tenant_id, profile_version, and model_instance_id are all required",
    "timeout_seconds 至少为 1": "timeout_seconds must be at least 1",
    "不能复制全量工具访问模式的岗位角色；请使用创建接口并走审批流程": "Position roles with the full tool access mode cannot be copied. Use the create endpoint and the approval flow instead",
    "不能复制全量技能访问模式的岗位角色；请使用创建接口并走审批流程": "Position roles with the full skill access mode cannot be copied. Use the create endpoint and the approval flow instead",
    "令牌已过期": "The token has expired",
    "令牌已过期或已被使用": "The token has expired or has already been used",
    "企业总 Token 不能为负数": "The organization total token quota cannot be negative",
    "包含不存在、未启用或非企业级的 MCP/工具": "It contains an MCP server or tool that does not exist, is not enabled, or is not organization-scoped",
    "包含不存在或未启用的企业 Skill": "It contains an organization skill that does not exist or is not enabled",
    "发布物不存在": "The release does not exist",
    "员工不存在": "The employee does not exist",
    "员工不存在或不可用": "The employee does not exist or is unavailable",
    "员工未开通或已停用": "The employee is not provisioned or has been disabled",
    "员工默认 Token 不能为负数": "The default employee token quota cannot be negative",
    "当前岗位不能创建新的工具连接": "The current position role cannot create new tool connections",
    "当前岗位未开通该工具": "The current position role does not have access to this tool",
    "数据后端未初始化": "The data backend has not been initialized",
    "文件内容与扩展名不匹配": "The file content does not match its extension",
    "暂无评测报告": "No evaluation report is available",
    "未找到对应的调用或会话记录": "No matching call or session record was found",
    "登录尝试过于频繁，请 5 分钟后重试": "Too many login attempts. Try again in 5 minutes",
    "评级不存在": "The rating does not exist",
    "该 SSO 凭证已使用，请重新进入管理台": "This SSO credential has already been used. Please sign in to the console again",
    "该租户已停用或已归档，无法接受邀请": "This tenant is disabled or archived and cannot accept invitations",
    "该租户已停用或已归档，无法新增成员": "This tenant is disabled or archived and cannot add members",
    "该账号不存在或已停用": "This account does not exist or has been disabled",
    "请先保存搜索源配置": "Save the search source configuration first",
    "资源授权模式无效": "The resource authorization mode is invalid",
    "连接器模板不存在": "The connector template does not exist",
    "部门节点不存在": "The department node does not exist",
    "项目不存在或已归档": "The project does not exist or has been archived",
    "项目名称不能为空": "The project name cannot be empty",
}

_STATUS_FALLBACKS = {
    400: "Invalid request",
    401: "Authentication required",
    403: "Access denied",
    404: "Resource not found",
    409: "Request conflicts with the current state",
    422: "Invalid request data",
}

_PRESENTATION_MODEL_LABELS = {
    "PPT 内容与布局模型": "presentation content and layout model",
    "PPT 图片生成模型": "presentation image generation model",
    "PPT 视觉重建模型": "presentation vision reconstruction model",
}


def _localize_dynamic_detail(detail: str) -> str | None:
    match = re.fullmatch(r"backend 不可用：(.*)", detail)
    if match:
        suffix = match.group(1)
        message = "The backend is unavailable"
        return f"{message}: {suffix}" if not any("\u3400" <= char <= "\u9fff" for char in suffix) else message
    match = re.fullmatch(r"图片模型运行时返回 HTTP (\d+): (.*)", detail)
    if match:
        suffix = match.group(2)
        message = f"The image model runtime returned HTTP {match.group(1)}"
        return f"{message}: {suffix}" if not any("\u3400" <= char <= "\u9fff" for char in suffix) else message
    match = re.fullmatch(r"无法连接图片模型运行时: (.*)", detail)
    if match:
        suffix = match.group(1)
        message = "Could not connect to the image model runtime"
        return f"{message}: {suffix}" if not any("\u3400" <= char <= "\u9fff" for char in suffix) else message
    match = re.fullmatch(r"当前版本最多允许 (\d+) 名成员", detail)
    if match:
        return f"This edition allows at most {match.group(1)} members"
    match = re.fullmatch(r"仍有 (\d+) 名员工未分配岗位角色", detail)
    if match:
        return f"{match.group(1)} employees still need a position role"
    for chinese, english in _PRESENTATION_MODEL_LABELS.items():
        if detail == f"请选择{chinese}":
            return f"Select a {english}"
        if detail == f"请选择有效的{chinese}":
            return f"Select a valid {english}"
        match = re.fullmatch(rf"{re.escape(chinese)}不存在、已禁用或不支持 (\w+) 能力", detail)
        if match:
            return f"The {english} is unavailable, disabled, or does not support {match.group(1)}"
    match = re.fullmatch(r"以下服务尚未就绪：(.*)", detail)
    if match:
        services = ", ".join(setup_service_label(item.strip()) for item in match.group(1).split(","))
        if not any("\u3400" <= char <= "\u9fff" for char in services):
            return f"The following services are not ready: {services}"
    return None


def localize_detail(detail: object, status_code: int, accept_language: str | None) -> object:
    language = (accept_language or "zh").split(",", 1)[0].split(";", 1)[0].strip().lower()
    if not language.startswith("en"):
        return detail
    if isinstance(detail, dict):
        message = detail.get("message")
        translated = localize_detail(message, status_code, accept_language)
        return {**detail, "message": translated} if translated != message else detail
    if not isinstance(detail, str):
        return detail
    if not any("\u3400" <= char <= "\u9fff" for char in detail):
        return detail
    return _ENGLISH_DETAILS.get(detail) or localize_model_test_message(detail) or _localize_dynamic_detail(detail) or _STATUS_FALLBACKS.get(status_code, "Request failed")
