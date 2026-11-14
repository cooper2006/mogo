from __future__ import annotations


_ENGLISH_DETAILS = {
    "巡检工单不存在": "Inspection ticket not found",
    "工具连接不存在": "Tool connection not found",
    "定时任务不存在": "Scheduled task not found",
    "目标会话无效": "Invalid target session",
    "目标会话不存在或无权访问": "The target session is unavailable or you do not have access",
    "任务已在本次时间点触发": "This task has already run at the scheduled time",
    "单次任务的执行时间不能早于当前时间": "The run time must be in the future",
    "固定会话模式必须选择目标会话": "Choose a target session for fixed session mode",
    "每周任务必须选择有效星期": "Choose at least one valid weekday",
    "当前用户无权使用该工具": "You do not have access to this tool",
    "当前用户无权使用该 MCP 服务": "You do not have access to this MCP service",
    "模型未返回可用代码": "The model did not return usable code",
    "所选知识文档已删除或尚未解析，请重新选择": "The selected knowledge document was deleted or has not been parsed. Choose another document.",
    "无权使用所选知识文档，请重新选择": "You do not have access to the selected knowledge document. Choose another document.",
    "请先选择要读取的知识文档": "Select a knowledge document to read first",
    "当前岗位未开通代码生成能力，本次任务未执行": "Code generation is unavailable for your role. This task was not run.",
    "请选择 ZIP 格式的 Skill 安装包": "Select a Skill package in ZIP format",
    "只有企业管理后台可以安装企业 Skill": "Only the organization admin console can install organization Skills",
    "员工不存在或不可用": "The employee does not exist or is unavailable",
    "员工未开通或已停用": "The employee is not provisioned or has been disabled",
    "当前岗位不能创建新的工具连接": "The current position role cannot create new tool connections",
    "当前岗位未开通该工具": "The current position role does not have access to this tool",
}

_STATUS_FALLBACKS = {
    400: "Invalid request",
    401: "Authentication required",
    403: "Access denied",
    404: "Resource not found",
    409: "Request conflicts with the current state",
    422: "Invalid request data",
}


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
    return _ENGLISH_DETAILS.get(detail, _STATUS_FALLBACKS.get(status_code, "Request failed"))
