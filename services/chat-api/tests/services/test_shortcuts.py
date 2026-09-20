import asyncio

from app.services import shortcuts


class Result:
    async def update_one(self, *args, **kwargs):
        return None

    async def find_one(self, query):
        if self.name == shortcuts.SCHEME_COLLECTION:
            return {"entries": [
                {"id": "locked", "categoryKey": "one", "enabled": True, "locked": True},
                {"id": "normal", "categoryKey": "two", "enabled": True, "locked": False},
            ]}
        return {"group_orders": {"one": ["locked"], "two": ["normal"]}}

    def __init__(self, name):
        self.name = name


class Database:
    def __getitem__(self, name):
        return Result(name)


def test_legacy_entry_locks_promote_to_group_locks(monkeypatch) -> None:
    monkeypatch.setattr(shortcuts, "get_db", lambda: Database())
    monkeypatch.setattr("app.product.extensions.get_product_extension", lambda: type("Extension", (), {"shortcut_scheme_resolver": None})())

    async def run():
        result = await shortcuts.ShortcutService().effective("m", "u")
        assert [item["id"] for item in result["entries"]] == ["locked", "normal"]
        assert result["groups"][0]["locked"] is True
        assert result["groups"][1]["locked"] is False

    asyncio.run(run())
