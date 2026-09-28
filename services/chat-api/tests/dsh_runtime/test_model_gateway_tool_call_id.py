"""Regression: tool results must keep their tool_call_id end to end.

DSH carries the tool-call identity on the message itself (``toolCallId``),
while some producers inline it inside a ``tool-result`` content block. Both
shapes used to collapse into an empty string, which the OpenAI-compatible
providers then dropped — producing the opaque upstream failure
``messages[n]: missing field tool_call_id``.
"""

from __future__ import annotations

from app.dsh_runtime.model_gateway.service import ModelGatewayRequest, ModelGatewayService
from app.llm.providers.azure_openai import AzureOpenAIClient
from app.llm.providers.default_openai import DefaultOpenAIClient
from app.llm.types import Role


def _request(messages: list[dict]) -> ModelGatewayRequest:
    return ModelGatewayRequest(
        profileVersion="v1",
        modelInstanceId="model-a",
        provider="askai-model-gateway",
        model="gpt-test",
        messages=messages,
    )


def test_message_level_tool_call_id_is_preserved() -> None:
    converted = ModelGatewayService._messages(
        _request(
            [
                {"role": "user", "content": "hi"},
                {
                    "role": "assistant",
                    "content": [{"type": "tool-call", "id": "call_1", "name": "bash", "arguments": "{}"}],
                },
                {"role": "tool", "toolCallId": "call_1", "content": [{"type": "text", "text": "ok"}]},
            ]
        )
    )
    tool_messages = [message for message in converted if message.role is Role.TOOL]
    assert [message.tool_call_id for message in tool_messages] == ["call_1"]


def test_snake_case_and_block_level_ids_are_accepted() -> None:
    converted = ModelGatewayService._messages(
        _request(
            [
                {"role": "tool", "tool_call_id": "call_snake", "content": "a"},
                {
                    "role": "tool",
                    "content": [
                        {
                            "type": "tool-result",
                            "toolCallId": "call_block",
                            "content": [{"type": "text", "text": "b"}],
                        }
                    ],
                },
            ]
        )
    )
    assert [message.tool_call_id for message in converted] == ["call_snake", "call_block"]


def test_openai_conversion_backfills_missing_id_from_pending_call() -> None:
    converted = ModelGatewayService._messages(
        _request(
            [
                {
                    "role": "assistant",
                    "content": [{"type": "tool-call", "id": "call_A", "name": "bash", "arguments": "{}"}],
                },
                # Unknown producer shape: a tool message with no id anywhere.
                {"role": "tool", "content": "no-id"},
            ]
        )
    )
    wire = DefaultOpenAIClient.__new__(DefaultOpenAIClient)._convert_messages(converted)
    tool_messages = [message for message in wire if message["role"] == "tool"]
    assert tool_messages and all(message.get("tool_call_id") == "call_A" for message in tool_messages)


def test_azure_chat_conversion_backfills_missing_id_from_pending_call() -> None:
    """The Azure chat path rejects the same malformed tool message."""
    converted = ModelGatewayService._messages(
        _request(
            [
                {
                    "role": "assistant",
                    "content": [{"type": "tool-call", "id": "call_Z", "name": "bash", "arguments": "{}"}],
                },
                {"role": "tool", "content": "no-id"},
            ]
        )
    )
    wire = AzureOpenAIClient.__new__(AzureOpenAIClient)._convert_messages_chat(converted)
    tool_messages = [message for message in wire if message["role"] == "tool"]
    assert tool_messages and all(message.get("tool_call_id") == "call_Z" for message in tool_messages)
