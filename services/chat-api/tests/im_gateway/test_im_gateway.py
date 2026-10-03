"""Tests for the multi-IM gateway core (feature 013): adapter / bindings / webhook."""

from __future__ import annotations

import pytest

from app.im_gateway.adapter_base import (
    DEFAULT_CHUNK_SIZE,
    FIRST_DELIVERY_CHANNEL,
    SUPPORTED_CHANNELS,
    ChannelError,
    FeishuAdapter,
    DingtalkAdapter,
    WecomAdapter,
    SlackAdapter,
    TeamsAdapter,
    build_adapter,
    chunk_text,
)
from app.im_gateway.bindings import (
    BindingError,
    SessionBindingRegistry,
    resolve_group_sender,
)
from app.im_gateway.webhook import (
    NonceCache,
    REPLAY_WINDOW_SECONDS,
    WebhookSignatureError,
    sign_payload,
    verify_signature,
)


# --- adapter -----------------------------------------------------------------

def test_first_delivery_channel_is_feishu() -> None:
    assert FIRST_DELIVERY_CHANNEL == "feishu"
    assert "feishu" in SUPPORTED_CHANNELS


def test_build_adapter_feishu() -> None:
    adapter = build_adapter("feishu")
    assert isinstance(adapter, FeishuAdapter)


def test_build_adapter_rejects_unknown_channel() -> None:
    with pytest.raises(ChannelError):
        build_adapter("telegram")


def test_feishu_parse_inbound_p2p() -> None:
    adapter = FeishuAdapter()
    message = adapter.parse_inbound(
        {
            "event": {
                "message": {"chat_id": "oc_1", "chat_type": "p2p", "content": '{"text": "hello"}'},
                "sender": {"sender_id": {"open_id": "ou_1"}},
            }
        }
    )
    assert message.channel == "feishu"
    assert message.channel_conversation_id == "oc_1"
    assert message.sender_id == "ou_1"
    assert message.text == "hello"
    assert message.is_group is False


def test_feishu_parse_inbound_group() -> None:
    adapter = FeishuAdapter()
    message = adapter.parse_inbound(
        {"event": {"message": {"chat_id": "oc_2", "chat_type": "group", "content": '{"text": "hi"}'}}}
    )
    assert message.is_group is True


def test_chunk_text_splits_and_marks_final() -> None:
    chunks = chunk_text("abcdefghij", size=4)
    assert [chunk.text for chunk in chunks] == ["abcd", "efgh", "ij"]
    assert chunks[-1].is_final is True
    assert chunks[0].is_final is False


def test_chunk_text_empty_returns_no_chunks() -> None:
    assert chunk_text("", size=4) == []


def test_default_chunk_size() -> None:
    assert DEFAULT_CHUNK_SIZE == 2000


def test_render_reply_produces_chunks() -> None:
    adapter = FeishuAdapter(chunk_size=5)
    reply = adapter.render_reply(conversation_id="oc_1", text="hello world")
    assert reply.conversation_id == "oc_1"
    assert reply.as_text() == "hello world"
    assert len(reply.chunks) == 3


# --- bindings ----------------------------------------------------------------

def test_bind_creates_one_to_one_mapping() -> None:
    registry = SessionBindingRegistry()
    binding = registry.bind(channel="feishu", conversation_id="oc_1", movo_session_id="s-1")
    assert binding.channel == "feishu"
    assert binding.movo_session_id == "s-1"


def test_rebind_same_conversation_to_same_session_is_idempotent() -> None:
    registry = SessionBindingRegistry()
    first = registry.bind(channel="feishu", conversation_id="oc_1", movo_session_id="s-1")
    second = registry.bind(channel="feishu", conversation_id="oc_1", movo_session_id="s-1")
    assert first is second


def test_session_cannot_bind_two_channels() -> None:
    registry = SessionBindingRegistry()
    registry.bind(channel="feishu", conversation_id="oc_1", movo_session_id="s-1")
    with pytest.raises(BindingError):
        registry.bind(channel="wecom", conversation_id="oc_9", movo_session_id="s-1")


def test_bind_rejects_empty_ids() -> None:
    registry = SessionBindingRegistry()
    with pytest.raises(BindingError):
        registry.bind(channel="", conversation_id="oc_1", movo_session_id="s-1")


def test_disabling_channel_marks_bindings_read_only() -> None:
    registry = SessionBindingRegistry()
    registry.bind(channel="feishu", conversation_id="oc_1", movo_session_id="s-1")
    affected = registry.disable_channel("feishu")
    assert affected == 1
    assert registry.get("feishu", "oc_1").read_only is True


def test_disabled_channel_rejects_new_bindings() -> None:
    registry = SessionBindingRegistry()
    registry.disable_channel("feishu")
    with pytest.raises(BindingError):
        registry.bind(channel="feishu", conversation_id="oc_2", movo_session_id="s-2")


def test_enabling_channel_restores_bindings() -> None:
    registry = SessionBindingRegistry()
    registry.bind(channel="feishu", conversation_id="oc_1", movo_session_id="s-1")
    registry.disable_channel("feishu")
    assert registry.enable_channel("feishu") == 1
    assert registry.get("feishu", "oc_1").read_only is False


def test_resolve_group_sender_requires_binding() -> None:
    with pytest.raises(BindingError):
        resolve_group_sender(sender_id="ou_1", user_map={})
    assert resolve_group_sender(sender_id="ou_1", user_map={"ou_1": "u-1"}) == "u-1"


# --- webhook -----------------------------------------------------------------

def test_replay_window_is_five_minutes() -> None:
    assert REPLAY_WINDOW_SECONDS == 300


def test_sign_and_verify_roundtrip() -> None:
    body = b'{"event": 1}'
    signature = sign_payload(secret="s", body=body, nonce="n1", timestamp=1000)
    verify_signature(secret="s", body=body, nonce="n1", timestamp=1000, signature=signature, now=1000)


def test_verify_rejects_missing_signature() -> None:
    with pytest.raises(WebhookSignatureError):
        verify_signature(secret="s", body=b"x", nonce="n", timestamp=1000, signature="", now=1000)


def test_verify_rejects_tampered_body() -> None:
    signature = sign_payload(secret="s", body=b"original", nonce="n1", timestamp=1000)
    with pytest.raises(WebhookSignatureError):
        verify_signature(secret="s", body=b"tampered", nonce="n1", timestamp=1000, signature=signature, now=1000)


def test_verify_rejects_stale_timestamp() -> None:
    body = b"x"
    signature = sign_payload(secret="s", body=body, nonce="n1", timestamp=1000)
    with pytest.raises(WebhookSignatureError):
        verify_signature(secret="s", body=body, nonce="n1", timestamp=1000, signature=signature, now=1000 + 400)


def test_nonce_cache_rejects_replay() -> None:
    cache = NonceCache()
    assert cache.check_and_store("n1", now=1000) is True
    assert cache.check_and_store("n1", now=1000) is False


def test_nonce_cache_evicts_after_window() -> None:
    cache = NonceCache()
    cache.check_and_store("n1", now=1000)
    # beyond the window the nonce is forgotten, so it can be reused
    assert cache.check_and_store("n1", now=1000 + REPLAY_WINDOW_SECONDS + 1) is True


def test_nonce_cache_rejects_empty_nonce() -> None:
    with pytest.raises(WebhookSignatureError):
        NonceCache().check_and_store("", now=1000)


# --- router (T010) -----------------------------------------------------------

def test_router_registers_and_routes_feishu() -> None:
    from app.im_gateway.router import ChannelRouter

    router = ChannelRouter()
    router.register("feishu")
    message = router.route(
        "feishu",
        {"event": {"message": {"chat_id": "oc_1", "chat_type": "p2p", "content": '{"text": "hi"}'}}},
    )
    assert message.channel == "feishu"
    assert message.text == "hi"


def test_router_rejects_disabled_channel() -> None:
    from app.im_gateway.router import ChannelRouter, RoutingError
    import pytest as _pytest

    router = ChannelRouter()
    router.register("feishu")
    router.disable("feishu")
    with _pytest.raises(RoutingError):
        router.route("feishu", {"event": {}})


def test_router_disable_marks_bindings_read_only() -> None:
    from app.im_gateway.router import ChannelRouter

    router = ChannelRouter()
    router.register("feishu")
    router.bind_conversation(channel="feishu", conversation_id="oc_1", movo_session_id="s-1")
    router.disable("feishu")
    assert router.registry.get("feishu", "oc_1").read_only is True


def test_router_rebind_after_enable_works() -> None:
    from app.im_gateway.router import ChannelRouter

    router = ChannelRouter()
    router.register("feishu")
    router.disable("feishu")
    router.enable("feishu")
    assert router.is_enabled("feishu") is True
    binding = router.bind_conversation(channel="feishu", conversation_id="oc_2", movo_session_id="s-2")
    assert binding.read_only is False


def test_router_rejects_unknown_channel() -> None:
    from app.im_gateway.router import ChannelRouter, RoutingError
    import pytest as _pytest

    router = ChannelRouter()
    with _pytest.raises(RoutingError):
        router.route("telegram", {})


def test_router_available_channels() -> None:
    from app.im_gateway.router import ChannelRouter

    router = ChannelRouter()
    router.register("feishu")
    assert router.available_channels() == ["feishu"]


# --- persisted registry (FR-10) ---------------------------------------------

class _FakeColl:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def find_one(self, query: dict, *args, **kwargs):
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    def find(self, query: dict, *args, **kwargs):
        matched = [dict(d) for d in self._docs if all(d.get(k) == v for k, v in query.items())]

        class _Cur:
            def sort(self, *a, **k):
                return self

            async def to_list(self, length: int):
                return matched[:length]

        return _Cur()

    async def update_one(self, query: dict, update: dict, upsert: bool = False, **kwargs):
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                doc.update(update.get("$set", {}))
                return None
        if upsert:
            self._docs.append({**query, **update.get("$set", {})})
        return None

    async def update_many(self, query: dict, update: dict, **kwargs):
        class _R:
            modified_count = 0

        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                doc.update(update.get("$set", {}))
                _R.modified_count += 1
        return _R()


class _FakeDB:
    def __init__(self, collections: dict[str, list[dict]]) -> None:
        self._collections = collections

    def __getitem__(self, name: str) -> _FakeColl:
        if name not in self._collections:
            self._collections[name] = []
        return _FakeColl(self._collections[name])


def test_persisted_registry_bind_roundtrip(monkeypatch):
    """FR-10: bind writes the row, get reads it back, conflicts are rejected."""
    import asyncio
    from app.im_gateway.bindings import PersistedSessionBindingRegistry, BindingError

    colls: dict[str, list[dict]] = {}
    db = _FakeDB(colls)
    monkeypatch.setattr("app.core.db.get_db", lambda: db)

    reg = PersistedSessionBindingRegistry()
    binding = asyncio.run(reg.bind(
        channel="feishu", conversation_id="c-1",
        movo_session_id="s-1", tenant_id="t-1",
    ))
    assert binding.channel_conversation_id == "c-1"
    # The row is persisted.
    rows = colls.get("im_session_bindings", [])
    assert len(rows) == 1 and rows[0]["movo_session_id"] == "s-1"
    # get() reads the persisted row back.
    loaded = asyncio.run(reg.get("feishu", "c-1", tenant_id="t-1"))
    assert loaded is not None and loaded.movo_session_id == "s-1"
    # First binder wins (FR-14): a second channel for the same session fails.
    with pytest.raises(BindingError):
        asyncio.run(reg.bind(
            channel="dingtalk", conversation_id="c-2",
            movo_session_id="s-1", tenant_id="t-1",
        ))


def test_persisted_registry_disable_enable_channel(monkeypatch):
    """FR-9: disable marks bindings read-only and records the channel switch;
    enable restores them. Channel switch state is persisted in im_channels."""
    import asyncio
    from app.im_gateway.bindings import PersistedSessionBindingRegistry

    colls: dict[str, list[dict]] = {}
    db = _FakeDB(colls)
    monkeypatch.setattr("app.core.db.get_db", lambda: db)

    reg = PersistedSessionBindingRegistry()
    asyncio.run(reg.bind(channel="feishu", conversation_id="c-1",
                         movo_session_id="s-1", tenant_id="t-1"))
    disabled_rows = colls.get("im_channels", [])
    assert asyncio.run(reg.is_channel_enabled("feishu", tenant_id="t-1")) is True
    affected = asyncio.run(reg.disable_channel("feishu", tenant_id="t-1"))
    assert affected == 1
    binding_row = colls["im_session_bindings"][0]
    assert binding_row["read_only"] is True
    assert asyncio.run(reg.is_channel_enabled("feishu", tenant_id="t-1")) is False
    restored = asyncio.run(reg.enable_channel("feishu", tenant_id="t-1"))
    assert restored == 1
    assert colls["im_session_bindings"][0]["read_only"] is False
    assert asyncio.run(reg.is_channel_enabled("feishu", tenant_id="t-1")) is True


def test_persisted_registry_degrades_without_db(monkeypatch):
    """DB unavailable → in-memory degradation, no fabricated rows, no crash."""
    import asyncio
    from app.im_gateway.bindings import PersistedSessionBindingRegistry

    def _no_db():
        raise RuntimeError("mongo down")

    monkeypatch.setattr("app.core.db.get_db", _no_db)
    reg = PersistedSessionBindingRegistry()
    binding = asyncio.run(reg.bind(channel="feishu", conversation_id="c-1",
                                   movo_session_id="s-1", tenant_id="t-1"))
    assert binding.movo_session_id == "s-1"
    assert asyncio.run(reg.get("feishu", "c-1", tenant_id="t-1")) is None
    assert asyncio.run(reg.disable_channel("feishu", tenant_id="t-1")) == 0
    assert asyncio.run(reg.is_channel_enabled("feishu", tenant_id="t-1")) is True


# --- 013 P1 残项：DingTalk / WeCom / Slack / Teams adapters (续五十五) ---


def test_build_adapter_returns_dingtalk() -> None:
    adapter = build_adapter("dingtalk")
    assert isinstance(adapter, DingtalkAdapter)
    assert adapter.channel == "dingtalk"


def test_build_adapter_returns_wecom() -> None:
    adapter = build_adapter("wecom")
    assert isinstance(adapter, WecomAdapter)
    assert adapter.channel == "wecom"


def test_build_adapter_returns_slack() -> None:
    adapter = build_adapter("slack")
    assert isinstance(adapter, SlackAdapter)
    assert adapter.channel == "slack"


def test_build_adapter_returns_teams() -> None:
    adapter = build_adapter("teams")
    assert isinstance(adapter, TeamsAdapter)
    assert adapter.channel == "teams"


def test_build_adapter_rejects_unknown_channel() -> None:
    with pytest.raises(ChannelError):
        build_adapter("telegram")


def test_dingtalk_parse_inbound_text() -> None:
    adapter = DingtalkAdapter()
    msg = adapter.parse_inbound({
        "msgtype": "text",
        "text": {"content": "你好"},
        "conversationId": "conv-1",
        "senderStaffId": "staff-1",
        "conversationType": "2",  # group
    })
    assert msg.channel == "dingtalk"
    assert msg.channel_conversation_id == "conv-1"
    assert msg.sender_id == "staff-1"
    assert msg.text == "你好"
    assert msg.is_group is True


def test_dingtalk_parse_inbound_p2p() -> None:
    adapter = DingtalkAdapter()
    msg = adapter.parse_inbound({
        "msgtype": "text",
        "text": {"content": "hi"},
        "conversationId": "conv-2",
        "senderStaffId": "staff-2",
        "conversationType": "1",  # p2p
    })
    assert msg.is_group is False


def test_wecom_parse_inbound() -> None:
    adapter = WecomAdapter()
    msg = adapter.parse_inbound({
        "msgtype": "text",
        "content": "你好",
        "chatid": "group-1",
        "from": "user-x",
    })
    assert msg.channel == "wecom"
    assert msg.channel_conversation_id == "group-1"
    assert msg.sender_id == "user-x"
    assert msg.text == "你好"
    assert msg.is_group is True


def test_slack_parse_inbound() -> None:
    adapter = SlackAdapter()
    msg = adapter.parse_inbound({
        "event": {
            "type": "message",
            "channel": "C123",
            "user": "U456",
            "text": "hello",
            "channel_type": "im",
        }
    })
    assert msg.channel == "slack"
    assert msg.channel_conversation_id == "C123"
    assert msg.sender_id == "U456"
    assert msg.text == "hello"
    assert msg.is_group is False


def test_teams_parse_inbound() -> None:
    adapter = TeamsAdapter()
    msg = adapter.parse_inbound({
        "type": "message",
        "text": "hi team",
        "conversation": {"id": "conv-teams", "conversationType": "Channel"},
        "from": {"id": "user-t"},
    })
    assert msg.channel == "teams"
    assert msg.channel_conversation_id == "conv-teams"
    assert msg.sender_id == "user-t"
    assert msg.text == "hi team"
    assert msg.is_group is True
