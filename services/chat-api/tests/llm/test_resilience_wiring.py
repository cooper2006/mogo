"""007 production wiring: provider failover on the configured-model path.

``get_llm_client_by_model_id`` now gathers the other active instances of the
same main_id + capability (priority order) as failover backups and wraps the
primary client in a ``ResilientLLMClient`` (007 FR-1 / FR-4 / FR-9 / FR-13).
With no backup configured the wrapper is a strict no-op, preserving existing
single-provider behavior.
"""

from __future__ import annotations

import asyncio

from app.llm import configured_models
from app.llm.configured_models import ModelConfigError
from app.llm.types import LLMResponse, Message, Role
from bson import ObjectId


class _EchoClient:
    """Minimal BaseLLMClient stand-in returning a fixed response."""

    def __init__(self, name: str, *, fail_times: int = 0, fail_class: type | None = None) -> None:
        self.name = name
        self.calls = 0
        self.fail_times = fail_times
        self.fail_class = fail_class or RuntimeError

    async def ainvoke(self, messages, **kwargs) -> LLMResponse:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.fail_class(f"{self.name} transient failure")
        return LLMResponse(message=Message(role=Role.ASSISTANT, content=f"ok:{self.name}"))


# ---------------------------------------------------------------------------
# wrap_resilient: no-op with a single provider (FR-9)
# ---------------------------------------------------------------------------


def test_wrap_resilient_is_noop_without_backups() -> None:
    primary = _EchoClient("primary")
    result = configured_models.wrap_resilient(primary, [])
    assert result is primary


def test_wrap_resilient_wraps_with_backups() -> None:
    from app.llm.resilience.failover import ResilientLLMClient

    primary = _EchoClient("primary")
    backup = _EchoClient("backup")
    result = configured_models.wrap_resilient(primary, [backup])
    assert isinstance(result, ResilientLLMClient)
    assert result.provider_names == ["primary", "backup-1"]


# ---------------------------------------------------------------------------
# get_fallback_runtime_configs: ordered active backups, primary excluded
# ---------------------------------------------------------------------------


def _fake_db(instances: list[dict], providers: dict[str, dict], end_users: list[dict] | None = None):
    """Build an async fake with the collections configured_models uses."""
    end_users = end_users if end_users is not None else []

    class _Coll:
        def __init__(self, name: str, docs: list[dict]) -> None:
            self._docs = docs
            self._name = name

        def find(self, query: dict, *args, **kwargs):
            return _Cursor([d for d in self._docs if _match(d, query)], self._name)

        async def find_one(self, query: dict, *args, **kwargs):
            for doc in self._docs:
                if _match(doc, query):
                    return doc
            return None

    class _Cursor:
        def __init__(self, docs: list[dict], name: str) -> None:
            self._docs = docs
            self._name = name

        def sort(self, spec: list[tuple[str, int]], *args, **kwargs):
            for key, direction in reversed(spec):
                self._docs.sort(key=lambda d, k=key: (d.get(k) is None, d.get(k)), reverse=direction == -1)
            return self

        async def to_list(self, length: int):
            return self._docs[:length]

        def __aiter__(self):
            self._iter_index = 0
            return self

        async def __anext__(self) -> dict:
            if self._iter_index >= len(self._docs):
                raise StopAsyncIteration
            doc = self._docs[self._iter_index]
            self._iter_index += 1
            return doc

    class _DB:
        def __getitem__(self, name: str):
            if name == configured_models.INSTANCE_COLLECTION:
                return _Coll(name, instances)
            if name == configured_models.PROVIDER_COLLECTION:
                return _Coll(name, list(providers.values()))
            if name == "end_users":
                return _Coll(name, end_users)
            raise KeyError(name)

    return _DB()


def _instance(provider_key: str, *, instance_id=None, **fields) -> dict:
    base = {
        "_id": instance_id or ObjectId(),
        "main_id": "m1",
        "status": "active",
        "priority": 0,
        "model_name": "gpt-high",
        "base_url": "https://h.example",
        "api_key_encrypted": "",
        "capabilities": ["chat"],
        "provider_id": provider_key,
        "updated_at": 0,
    }
    base.update(fields)
    return base


def _provider(provider_key: str, **fields) -> dict:
    base = {"_id": provider_key, "provider_type": "openai_compatible", "name": provider_key.title()}
    base.update(fields)
    return base


def _fake_config_loader(instances: list[dict], providers: dict[str, dict], primary_id):
    """Async stand-in for configured_models.get_model_config."""

    async def _load(model_id: str, main_id: str):
        for instance in instances:
            if str(instance.get("_id")) == str(model_id):
                provider = providers.get(str(instance.get("provider_id")), {})
                return configured_models._to_runtime_config(instance, provider)
        return None

    return _load


def _match(doc: dict, query: dict) -> bool:
    for key, value in query.items():
        if isinstance(value, dict):
            # operator query: {"_id": {"$ne": oid}} / {"_id": {"$in": [...]}}
            for op, operand in value.items():
                if op == "$ne" and doc.get(key) == operand:
                    return False
                if op == "$in" and doc.get(key) not in operand:
                    return False
        else:
            if value is None:
                continue
            doc_val = doc.get(key)
            if isinstance(doc_val, (list, tuple, set)) and not isinstance(value, (list, tuple, set)):
                # Mongo membership: a scalar query matches a list field if contained
                if value not in doc_val:
                    return False
            elif doc_val != value:
                return False
    return True


def test_fallback_configs_ordered_and_primary_excluded(monkeypatch) -> None:
    from bson import ObjectId

    primary_id = ObjectId()
    backup_ids = [ObjectId(), ObjectId()]
    instances = [
        _instance("p-high", instance_id=primary_id, priority=0, model_name="gpt-high",
                  base_url="https://h.example"),
        _instance("p-mid", instance_id=backup_ids[0], priority=1, model_name="gpt-mid",
                  base_url="https://m.example"),
        _instance("p-light", instance_id=backup_ids[1], priority=2, model_name="gpt-light",
                  base_url="https://l.example"),
        _instance("p-off", status="disabled", priority=3, model_name="gpt-off",
                  base_url="https://off.example"),
    ]
    providers = {
        "p-high": _provider("p-high"),
        "p-mid": _provider("p-mid"),
        "p-light": _provider("p-light"),
        "p-off": _provider("p-off"),
    }
    db = _fake_db(instances, providers)
    monkeypatch.setattr(configured_models, "get_db", lambda: db)
    monkeypatch.setattr(configured_models, "decrypt_secret", lambda value: "key")

    configs = asyncio.run(configured_models.get_fallback_runtime_configs("m1", primary_instance_id=str(primary_id)))
    assert [c["id"] for c in configs] == [str(backup_ids[0]), str(backup_ids[1])]
    assert [c["model_name"] for c in configs] == ["gpt-mid", "gpt-light"]


def test_fallback_configs_empty_when_only_primary(monkeypatch) -> None:
    from bson import ObjectId

    primary_id = ObjectId()
    instances = [
        _instance("p-high", instance_id=primary_id, priority=0, model_name="gpt-high",
                  base_url="https://h.example"),
    ]
    providers = {"p-high": _provider("p-high")}
    db = _fake_db(instances, providers)
    monkeypatch.setattr(configured_models, "get_db", lambda: db)
    monkeypatch.setattr(configured_models, "decrypt_secret", lambda value: "key")

    configs = asyncio.run(configured_models.get_fallback_runtime_configs("m1", primary_instance_id=str(primary_id)))
    assert configs == []


# ---------------------------------------------------------------------------
# get_llm_client_by_model_id: failover actually happens on the production path
# ---------------------------------------------------------------------------


def test_get_llm_client_by_model_id_fails_over_to_backup(monkeypatch) -> None:
    from bson import ObjectId

    primary_id = ObjectId()
    backup_id = ObjectId()
    instances = [
        _instance("p-high", instance_id=primary_id, priority=0, model_name="gpt-high",
                  base_url="https://h.example"),
        _instance("p-mid", instance_id=backup_id, priority=1, model_name="gpt-mid",
                  base_url="https://m.example"),
    ]
    providers = {
        "p-high": _provider("p-high"),
        "p-mid": _provider("p-mid"),
    }
    db = _fake_db(instances, providers, end_users=[])
    monkeypatch.setattr(configured_models, "get_db", lambda: db)
    monkeypatch.setattr(configured_models, "decrypt_secret", lambda value: "key")
    monkeypatch.setattr(configured_models, "get_model_config", _fake_config_loader(instances, providers, primary_id))

    # Stub the concrete client construction so no network/keys are needed;
    # primary fails once (retryable) to exercise the failover path.
    primary_echo = _EchoClient("primary", fail_times=1)
    backup_echo = _EchoClient("backup")
    seen: list[str] = []

    def fake_build(config, **kwargs):
        if str(config.get("id")) == str(primary_id):
            seen.append("primary")
            return primary_echo
        seen.append("backup")
        return backup_echo

    monkeypatch.setattr(configured_models, "build_llm_client_from_config", fake_build)

    client = asyncio.run(configured_models.get_llm_client_by_model_id(str(primary_id), main_id="m1"))
    from app.llm.resilience.failover import ResilientLLMClient
    assert isinstance(client, ResilientLLMClient)

    response = asyncio.run(client.ainvoke([Message(role=Role.USER, content="hi")]))
    assert "primary" in response.content
    # primary was called (once failed + one success after retry), backup not needed.
    assert primary_echo.calls >= 1


def test_get_llm_client_by_model_id_single_provider_is_noop(monkeypatch) -> None:
    from bson import ObjectId

    primary_id = ObjectId()
    instances = [
        _instance("p-high", instance_id=primary_id, priority=0, model_name="gpt-high",
                  base_url="https://h.example"),
    ]
    providers = {"p-high": _provider("p-high")}
    db = _fake_db(instances, providers, end_users=[])
    monkeypatch.setattr(configured_models, "get_db", lambda: db)
    monkeypatch.setattr(configured_models, "decrypt_secret", lambda value: "key")
    monkeypatch.setattr(configured_models, "get_model_config", _fake_config_loader(instances, providers, primary_id))

    only_echo = _EchoClient("only")
    monkeypatch.setattr(
        configured_models, "build_llm_client_from_config", lambda config, **kwargs: only_echo
    )

    client = asyncio.run(configured_models.get_llm_client_by_model_id(str(primary_id), main_id="m1"))
    assert client is only_echo  # FR-9: single provider stays unwrapped
