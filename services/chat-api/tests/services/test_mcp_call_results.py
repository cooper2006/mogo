import asyncio

from app.services.external_tools import ExternalToolService
from app.services.mcp_call_result import build_mcp_call_outcome


def test_mcp_error_result_becomes_failed_execution() -> None:
    result = {
        "content": [{"type": "text", "text": "Repository not found"}],
        "isError": True,
    }

    outcome = build_mcp_call_outcome("ask_question", result)

    assert outcome["success"] is False
    assert outcome["status"] == "failed"
    assert outcome["errorCode"] == "mcp_tool_error"
    assert outcome["message"] == "Repository not found"
    assert outcome["raw"] == result


def test_mcp_success_result_keeps_successful_execution() -> None:
    outcome = build_mcp_call_outcome(
        "read_wiki_structure",
        {"content": [{"type": "text", "text": "Pages: Overview"}], "isError": False},
    )

    assert outcome["success"] is True
    assert outcome["status"] == "passed"
    assert outcome["responseSummary"] == "Pages: Overview"


def test_mcp_error_without_text_uses_clear_fallback() -> None:
    outcome = build_mcp_call_outcome("search", {"content": [], "isError": True})

    assert outcome["success"] is False
    assert outcome["message"] == "MCP tool search 执行失败"


def test_admin_test_path_uses_mcp_error_semantics(monkeypatch) -> None:
    service = ExternalToolService()

    async def fake_call(*args, **kwargs):
        return {
            "content": [{"type": "text", "text": "Remote business error"}],
            "isError": True,
        }

    monkeypatch.setattr(service, "_mcp_jsonrpc", fake_call)
    outcome = asyncio.run(
        service._test_mcp(
            {"type": "mcp", "config": {}},
            {"toolName": "search", "arguments": {}},
        )
    )

    assert outcome["success"] is False
    assert outcome["message"] == "Remote business error"


def test_agent_runtime_path_uses_mcp_error_semantics(monkeypatch) -> None:
    service = ExternalToolService()
    tool = {
        "id": "tool-1",
        "type": "mcp",
        "status": "active",
        "config": {"enabledToolNames": ["search"]},
    }

    async def fake_get(*args, **kwargs):
        return tool

    async def fake_call(*args, **kwargs):
        return {
            "content": [{"type": "text", "text": "Access denied"}],
            "isError": True,
        }

    monkeypatch.setattr(service, "get", fake_get)
    monkeypatch.setattr(service, "_mcp_jsonrpc", fake_call)
    outcome = asyncio.run(
        service.execute_runtime(
            external_tool_id="tool-1",
            provider_type="mcp",
            mcp_tool_name="search",
        )
    )

    assert outcome["success"] is False
    assert outcome["status"] == "failed"
    assert outcome["message"] == "Access denied"


def test_saved_tool_records_failed_status_for_mcp_business_error(monkeypatch) -> None:
    service = ExternalToolService()
    recorded = {}

    async def fake_get(*args, **kwargs):
        return {"id": "tool-1", "type": "mcp", "config": {}}

    async def fake_call(*args, **kwargs):
        return {"content": [{"type": "text", "text": "Remote business error"}], "isError": True}

    async def fake_record(tool_id, main_id, status, message):
        recorded.update(tool_id=tool_id, main_id=main_id, status=status, message=message)

    monkeypatch.setattr(service, "get", fake_get)
    monkeypatch.setattr(service, "_mcp_jsonrpc", fake_call)
    monkeypatch.setattr(service, "_record_test", fake_record)
    outcome = asyncio.run(service.test("tool-1", {"toolName": "search"}, "tenant-1"))

    assert outcome["success"] is False
    assert recorded == {
        "tool_id": "tool-1",
        "main_id": "tenant-1",
        "status": "failed",
        "message": "Remote business error",
    }
