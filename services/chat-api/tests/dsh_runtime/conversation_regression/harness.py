from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from app.dsh_runtime import DshAgentKernelGateway, DshHostConfig, DshRuntimeHostManager, HttpKernelHostTransport
from app.dsh_runtime.contracts import ContentBlock, CreateRuntimeRequest, CreateSessionRequest, SendRequest, SessionSpec
from app.dsh_runtime.model_gateway.token import ModelGatewayTokenService
from app.dsh_runtime.profile import InMemoryRuntimeProfileStore, RuntimeProfileResolver, RuntimeProfileSnapshot
from app.dsh_runtime.tool_gateway import ToolGatewayTokenService

from .bridge import DeterministicBridge, start_bridge
from .profile import regression_skill, regression_tools


CHAT_API_ROOT = Path(__file__).parents[3]
HOST_ENTRY = CHAT_API_ROOT / "dsh" / "runtime-host" / "src" / "host.mjs"
CODEX_NODE = Path("/Users/jack/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")


def compatible_node() -> Path | None:
    for value in (shutil.which("node"), str(CODEX_NODE)):
        candidate = Path(value) if value else None
        if not candidate or not candidate.is_file():
            continue
        result = subprocess.run([str(candidate), "--version"], capture_output=True, text=True, check=False)
        parts = tuple(int(part) for part in result.stdout.strip().removeprefix("v").split(".")[:2])
        if parts >= (24, 0) or (22, 19) <= parts < (23, 0):
            return candidate
    return None


async def collect_turn(gateway: DshAgentKernelGateway, session_id: str, after_cursor: int):
    events = []
    async for event in gateway.subscribe(session_id, after_cursor=after_cursor):
        events.append(event)
        if event.type == "turn.completed":
            return events
    raise AssertionError("turn did not complete")


class ConversationHarness:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.host: DshRuntimeHostManager | None = None
        self.transport: HttpKernelHostTransport | None = None
        self.gateway: DshAgentKernelGateway | None = None
        self.runtime_id = ""
        self.server = None
        self.thread = None
        self.cursors: dict[str, int] = {}

    async def start(self) -> None:
        node = compatible_node()
        if node is None:
            pytest.fail("DSH conversation regression requires Node ^22.19.0 or >=24.0.0")
        model_tokens = ModelGatewayTokenService("conversation-regression-model-secret")
        tool_tokens = ToolGatewayTokenService("conversation-regression-tool-secret")
        self.server, self.thread = start_bridge(model_tokens, tool_tokens)
        tools = await regression_tools()
        skill = regression_skill()
        profile = RuntimeProfileSnapshot(
            profile_version="profile-conversation-regression-v1",
            content_hash="a" * 64,
            tenant_id="tenant-regression",
            subject_user_id="user-regression",
            model_source_tenant_id="tenant-regression",
            model_instance_id="model-regression",
            provider_id="provider-regression",
            provider_type="openai_compatible",
            provider_name="deterministic-regression-bridge",
            model_name="deterministic-regression-model",
            display_name="Deterministic Regression Model",
            capabilities=("chat", "tools", "skills"),
            tool_versions=tuple(tool.version for tool in tools),
            tools=tools,
            skills=(skill,),
            skill_versions=(skill.version,),
        )
        store = InMemoryRuntimeProfileStore()
        await store.publish(profile, actor_id="regression", activate=False)
        resolver = RuntimeProfileResolver(
            store,
            model_tokens,
            gateway_url=f"http://127.0.0.1:{self.server.server_port}/model",
            tool_token_service=tool_tokens,
            tool_gateway_url=f"http://127.0.0.1:{self.server.server_port}/tools",
        )
        self.host = DshRuntimeHostManager(DshHostConfig(
            node_executable=node,
            host_entry=HOST_ENTRY,
            storage_root=self.tmp_path / "sessions",
            log_path=self.tmp_path / "host.log",
        ))
        self.transport = HttpKernelHostTransport(await self.host.start(), timeout_seconds=10)
        self.gateway = DshAgentKernelGateway(self.transport, profile_resolver=resolver)
        runtime = await self.gateway.create_runtime(CreateRuntimeRequest(
            tenant_id="tenant-regression",
            profile_version=profile.profile_version,
            isolation_key="tenant-regression:conversation-suite",
        ))
        self.runtime_id = runtime.runtime_id

    async def stop(self) -> None:
        if self.transport is not None:
            await self.transport.close()
        if self.host is not None:
            await self.host.stop()
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2)

    async def create_session(self, conversation_id: str) -> str:
        assert self.gateway is not None
        session = await self.gateway.create_session(CreateSessionRequest(
            runtime_id=self.runtime_id,
            session_spec=SessionSpec(
                conversation_id=conversation_id,
                tenant_id="tenant-regression",
                user_id="user-regression",
                profile_version="profile-conversation-regression-v1",
            ),
        ))
        self.cursors[session.session_id] = 0
        return session.session_id

    async def turn(self, session_id: str, request_id: str, text: str, *, selected_skill_id: str = ""):
        assert self.gateway is not None
        context = {"selected_skill_id": selected_skill_id} if selected_skill_id else {}
        await self.gateway.send(SendRequest(
            session_id=session_id,
            request_id=request_id,
            content=[ContentBlock(type="text", data={"text": text})],
            turn_context=context,
        ))
        try:
            events = await asyncio.wait_for(
                collect_turn(self.gateway, session_id, self.cursors[session_id]), timeout=15
            )
            self.cursors[session_id] = max(event.cursor for event in events)
            return events
        except asyncio.TimeoutError as exc:
            raise AssertionError(
                f"turn timed out: request={request_id}, model_calls={len(DeterministicBridge.model_calls)}, "
                f"tool_calls={DeterministicBridge.tool_calls[-2:]}"
            ) from exc


def event_text(events) -> str:
    return " ".join(str(event.payload) for event in events)


__all__ = ["ConversationHarness", "DeterministicBridge", "event_text"]
