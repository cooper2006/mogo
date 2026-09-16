import asyncio
import json

import httpx

from app.services.mcp_streamable_http import MCP_PROTOCOL_VERSION, StreamableHttpMcpClient


def test_streamable_http_initializes_session_before_listing_tools_and_preserves_headers():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append((payload, dict(request.headers)))
        assert request.headers["authorization"] == "Bearer secret"
        assert request.headers["x-custom-auth"] == "tenant-token"
        assert request.headers["mcp-protocol-version"] == MCP_PROTOCOL_VERSION

        if payload["method"] == "initialize":
            assert "mcp-session-id" not in request.headers
            return httpx.Response(
                200,
                headers={"Mcp-Session-Id": "session-123"},
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "serverInfo": {"name": "test", "version": "1"},
                    },
                },
            )

        assert request.headers["mcp-session-id"] == "session-123"
        if payload["method"] == "notifications/initialized":
            assert "id" not in payload
            return httpx.Response(202)
        assert payload["method"] == "tools/list"
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": payload["id"], "result": {"tools": [{"name": "search"}]}},
        )

    client = StreamableHttpMcpClient(
        endpoint="https://mcp.example.test/mcp",
        headers={
            "Authorization": "Bearer secret",
            "X-Custom-Auth": "tenant-token",
            "mcp-session-id": "caller-must-not-control-this",
            "accept": "text/plain",
        },
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(client.call("tools/list", {}))

    assert result == {"tools": [{"name": "search"}]}
    assert [payload["method"] for payload, _ in requests] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
    ]


def test_streamable_http_uses_negotiated_version_and_matches_sse_response_id():
    seen_versions = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload["method"] == "initialize":
            return httpx.Response(
                200,
                headers={"Mcp-Session-Id": "sse-session"},
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {"protocolVersion": "2025-03-26", "capabilities": {}},
                },
            )
        seen_versions.append(request.headers["mcp-protocol-version"])
        if payload["method"] == "notifications/initialized":
            return httpx.Response(202)
        body = (
            'event: message\n'
            'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{"progress":1}}\n\n'
            'event: message\n'
            f'data: {json.dumps({"jsonrpc": "2.0", "id": payload["id"], "result": {"content": [{"type": "text", "text": "ok"}]}})}\n\n'
        )
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, text=body)

    result = asyncio.run(
        StreamableHttpMcpClient(
            endpoint="https://mcp.example.test/mcp",
            transport=httpx.MockTransport(handler),
        ).call("tools/call", {"name": "search", "arguments": {"q": "MOVO"}})
    )

    assert result["content"][0]["text"] == "ok"
    assert seen_versions == ["2025-03-26", "2025-03-26"]


def test_streamable_http_allows_stateless_server_without_session_id():
    session_headers = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload["method"] == "initialize":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {"protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {}},
                },
            )
        session_headers.append(request.headers.get("Mcp-Session-Id"))
        if payload["method"] == "notifications/initialized":
            return httpx.Response(202)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": {"tools": []}})

    result = asyncio.run(
        StreamableHttpMcpClient(
            endpoint="https://mcp.example.test/mcp",
            transport=httpx.MockTransport(handler),
        ).call("tools/list")
    )

    assert result == {"tools": []}
    assert session_headers == [None, None]


def test_legacy_direct_jsonrpc_endpoint_remains_compatible_when_initialize_is_rejected():
    methods = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        methods.append(payload["method"])
        if payload["method"] == "initialize":
            return httpx.Response(405, text="initialize unsupported")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": {"tools": []}})

    result = asyncio.run(
        StreamableHttpMcpClient(
            endpoint="https://legacy.example.test/rpc",
            transport=httpx.MockTransport(handler),
        ).call("tools/list")
    )

    assert result == {"tools": []}
    assert methods == ["initialize", "tools/list"]
