from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.dsh_runtime.chat_service import DshChatService


def test_completed_conversation_turn_uses_the_newly_selected_model_binding() -> None:
    async def run() -> None:
        current = {
            "binding_id": "binding-a",
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "conversation_id": "conversation-a",
            "kernel_session_id": "session-a",
            "runtime_id": "runtime-a",
            "profile_version": "profile-a",
            "model_instance_id": "model-a",
            "execution_location": "server",
            "active_turn": None,
        }

        class Conversations:
            async def owned(self, *_args, **_kwargs):
                return {"_id": "conversation-a"}

            async def append_message(self, **_kwargs):
                return None

            async def mark_active_run(self, **_kwargs):
                return None

        class Bindings:
            async def current(self, *_args, **_kwargs):
                return current

            async def claim_turn(self, binding_id, **_kwargs):
                assert binding_id == "binding-b"
                return {**current, "binding_id": binding_id, "model_instance_id": "model-b"}

            async def finish_turn(self, *_args, **_kwargs):
                return None

        class Profiles:
            async def compile_model_profile(self, **scope):
                assert scope["model_instance_id"] == "model-b"
                return SimpleNamespace(profile_version="profile-b", model_instance_id="model-b")

            async def publish_snapshot(self, snapshot, **_scope):
                assert snapshot.model_instance_id == "model-b"

        class Coordinator:
            def __init__(self) -> None:
                self.rotated = False

            async def restore(self, binding):
                return binding

            async def rotate_binding(self, binding, *, profile_version, model_instance_id):
                self.rotated = True
                assert binding["conversation_id"] == "conversation-a"
                assert (profile_version, model_instance_id) == ("profile-b", "model-b")
                return {
                    **binding,
                    "binding_id": "binding-b",
                    "kernel_session_id": "session-b",
                    "runtime_id": "runtime-b",
                    "profile_version": profile_version,
                    "model_instance_id": model_instance_id,
                }

            async def dispose_restored_session(self, binding):
                assert binding["kernel_session_id"] == "session-a"
                return True

        coordinator = Coordinator()
        service = DshChatService(
            gateway=SimpleNamespace(),
            coordinator=coordinator,  # type: ignore[arg-type]
            conversations=Conversations(),  # type: ignore[arg-type]
            bindings=Bindings(),  # type: ignore[arg-type]
            events=SimpleNamespace(),
            profiles=Profiles(),  # type: ignore[arg-type]
            kernel_version="test",
        )

        async def finish_immediately(**_kwargs):
            return "completed"

        service._turn_runner.run = finish_immediately  # type: ignore[method-assign]
        turn = await service.prepare_turn(
            tenant_id="tenant-a",
            user_id="user-a",
            conversation_id="conversation-a",
            text="continue with model B",
            model_instance_id="model-b",
            timezone_name="Asia/Shanghai",
            images=[],
            documents=[],
        )
        assert turn.conversation_id == "conversation-a"
        assert turn.binding_id == "binding-b"
        assert coordinator.rotated is True
        assert await service.wait_turn(turn.message_id) == "completed"

    asyncio.run(run())
