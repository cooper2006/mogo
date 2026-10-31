import asyncio

from app.dsh_runtime.plugin_management import repository as repository_module
from app.dsh_runtime.plugin_management.invocation import PluginInvocationRecorder, plugin_for_tool


class RecordingRepository:
    def __init__(self):
        self.calls = []

    async def mark_invoked(self, **kwargs):
        self.calls.append(kwargs)


def test_only_unambiguous_loaded_plugin_receives_successful_call():
    plugins = [
        {"name": "enterprise", "version": "1", "spec": "enterprise@1", "source_scope": "organization", "tool_names": ["safe"]},
        {"name": "personal", "version": "2", "spec": "personal@2", "source_scope": "personal", "tool_names": ["own", "duplicate"]},
        {"name": "other", "version": "1", "spec": "other@1", "source_scope": "organization", "tool_names": ["duplicate"]},
    ]
    repository = RecordingRepository()
    asyncio.run(PluginInvocationRecorder(repository).record(
        tenant_id="tenant", user_id="user", plugins=plugins,
        tool_names=["safe", "own", "duplicate", "builtin"],
    ))
    assert plugin_for_tool(plugins, "duplicate") is None
    assert {call["name"] for call in repository.calls} == {"enterprise", "personal"}
    assert next(call for call in repository.calls if call["name"] == "enterprise")["user_id"] == ""
    assert next(call for call in repository.calls if call["name"] == "personal")["user_id"] == "user"


def test_invocation_update_requires_enabled_exact_package_and_successful_session_check(monkeypatch):
    class Collection:
        async def update_one(self, query, update):
            self.query, self.update = query, update

    class Database:
        dsh_plugin_installations = Collection()

    db = Database()
    monkeypatch.setattr(repository_module, "get_db", lambda: db)
    asyncio.run(repository_module.PluginInstallationRepository().mark_invoked(
        tenant_id="tenant", user_id="", name="plugin", version="1", spec="plugin@1", tool_name="test_tool",
    ))
    assert db.dsh_plugin_installations.query["enabled"] is True
    assert db.dsh_plugin_installations.query["availability.status"] == {"$in": ["session_exposed", "verified"]}
    assert db.dsh_plugin_installations.query["tool_names"] == "test_tool"
    assert db.dsh_plugin_installations.update["$set"]["availability.checks.invocation"] is True
