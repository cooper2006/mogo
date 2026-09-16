from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any

from app.dsh_runtime.model_gateway.token import ModelGatewayTokenService
from app.dsh_runtime.tool_gateway import ToolGatewayTokenService

from .scenarios import SCENARIOS, SKILL_SCENARIO, ConversationScenario


BY_ID = {scenario.id: scenario for scenario in (*SCENARIOS, SKILL_SCENARIO)}


class DeterministicBridge(BaseHTTPRequestHandler):
    model_tokens: ModelGatewayTokenService
    tool_tokens: ToolGatewayTokenService
    model_calls: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    scenario_by_session: dict[str, str] = {}

    @classmethod
    def reset(cls, model_tokens: ModelGatewayTokenService, tool_tokens: ToolGatewayTokenService) -> None:
        cls.model_tokens = model_tokens
        cls.tool_tokens = tool_tokens
        cls.model_calls = []
        cls.tool_calls = []
        cls.scenario_by_session = {}

    def do_POST(self) -> None:  # noqa: N802
        payload = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)))
        token = str(self.headers.get("authorization") or "").removeprefix("Bearer ")
        if self.path == "/model":
            self.model_tokens.verify(token)
            self.model_calls.append(payload)
            self._model(payload)
            return
        self.tool_tokens.verify(token)
        if self.path == "/tools/execute":
            self.tool_calls.append(payload)
            self._json({"ok": True, "result": self._tool_result(payload)})
            return
        self._json({"error": "not found"}, status=404)

    def _model(self, payload: dict[str, Any]) -> None:
        session_id = str(payload.get("sessionId") or "")
        serialized = json.dumps(payload.get("messages") or [], ensure_ascii=False)
        for scenario_id in ("context_followup", "context_seed", "direct_answer"):
            if f"REGRESSION_SCENARIO:{scenario_id}" in serialized:
                if scenario_id == "context_followup":
                    assert "SCENARIO_OK:context_seed" in serialized
                self._ndjson(self._answer_events(scenario_id))
                return
        scenario = self._scenario(serialized, session_id)
        if scenario.id == "skill_followup":
            self._ndjson(self._answer_events(scenario.id))
            return
        assert scenario.model_tool_name in {tool["name"] for tool in payload.get("tools") or []}
        if self._current_turn_has_result(payload):
            self._ndjson(self._answer_events(scenario.id))
            return
        self._ndjson([
            {
                "type": "tool-call",
                "id": f"call-{scenario.id}",
                "name": scenario.model_tool_name,
                "arguments": json.dumps(scenario.arguments, ensure_ascii=False),
            },
            {"type": "finish", "reason": {"kind": "tool-calls"}},
        ])

    def _scenario(self, serialized: str, session_id: str) -> ConversationScenario:
        if "REGRESSION_SCENARIO:skill_followup" in serialized:
            return ConversationScenario("skill_followup", "", "", "", {})
        for scenario_id, scenario in BY_ID.items():
            if f"REGRESSION_SCENARIO:{scenario_id}" in serialized:
                self.scenario_by_session[session_id] = scenario_id
                if scenario_id == "dynamic_skill":
                    assert "SKILL_REGRESSION_INSTRUCTION" in serialized
                    assert "skill-invocation" in serialized
                return scenario
        return BY_ID[self.scenario_by_session[session_id]]

    @staticmethod
    def _current_turn_has_result(payload: dict[str, Any]) -> bool:
        return any(
            block.get("type") == "tool-result"
            for message in list(payload.get("messages") or [])
            for block in list(message.get("content") or [])
            if isinstance(block, dict)
        )

    @staticmethod
    def _answer_events(scenario_id: str) -> list[dict[str, Any]]:
        return [
            {"type": "text-delta", "text": f"SCENARIO_OK:{scenario_id}"},
            {"type": "finish", "reason": {"kind": "stop"}},
        ]

    @staticmethod
    def _tool_result(payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload["toolName"])
        arguments = payload.get("arguments") or {}
        result: dict[str, Any] = {
            "success": True,
            "echo": str(arguments.get("value") or name),
            "receipt": f"TOOL_OK:{name}",
        }
        if name == "content_production":
            result.update({"accepted": True, "markdown": "# SCENARIO_OK:content_generation"})
        elif name in {"artifact_export", "document_transform"}:
            result["artifact"] = {
                "object_path": f"regression/{name}.docx",
                "filename": f"{name}.docx",
                "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }
        elif name in {"external_search", "progressive_research", "knowledge_search"}:
            result["results"] = [{"title": "Regression evidence", "url": "https://example.test/evidence"}]
        return result

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _ndjson(self, events: list[dict[str, Any]]) -> None:
        encoded = "".join(json.dumps(event) + "\n" for event in events).encode()
        self.send_response(200)
        self.send_header("content-type", "application/x-ndjson")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def start_bridge(
    model_tokens: ModelGatewayTokenService, tool_tokens: ToolGatewayTokenService
) -> tuple[ThreadingHTTPServer, Thread]:
    DeterministicBridge.reset(model_tokens, tool_tokens)
    server = ThreadingHTTPServer(("127.0.0.1", 0), DeterministicBridge)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
