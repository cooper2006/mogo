"""041-connector-market 单测（fake DB，无真实 Mongo 依赖）。

覆盖：
- 模板种子加载/结构校验/疑似真实凭证过滤（T011、FR-006）
- 目录 API 视图（分类、安装计数、已安装标记）
- 从模板创建连接器走**既有** external_tools 存储（FR-004 同构）
- 参数校验失败 → 400
- 凭证托管标记（header 型可托管、URL 型诚实降级）
- 已安装列表区分 template / manual
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

from app.api.routes import connector_market as market
from app.api.routes import tools as tools_module
from app.services import connector_templates as templates_service


@pytest.fixture(autouse=True)
def _kms_dev_key(monkeypatch):
    """034: 凭证加密需要主密钥；单测用开发密钥（仅本地）。"""

    monkeypatch.setenv("MOGO_ALLOW_INSECURE_DEV_KEY", "1")


# --------------------------------------------------------------------- fake db
def _matches(row: dict, query: dict) -> bool:
    return all(row.get(key) == value for key, value in query.items())


class _Cursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def sort(self, key: str, direction: int = 1) -> "_Cursor":
        self._rows.sort(key=lambda row: row.get(key) or "", reverse=direction < 0)
        return self

    def limit(self, count: int) -> "_Cursor":
        self._rows = self._rows[:count]
        return self

    async def to_list(self, length: int = 100) -> list[dict]:
        return list(self._rows[:length])


class Collection:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    async def insert_one(self, doc: dict) -> None:
        doc.setdefault("_id", uuid.uuid4().hex)
        self.rows[str(doc["_id"])] = doc

    async def find_one(self, query: dict) -> dict | None:
        for row in self.rows.values():
            if _matches(row, query):
                return row
        return None

    def find(self, query: dict | None = None) -> _Cursor:
        query = query or {}
        return _Cursor([row for row in self.rows.values() if _matches(row, query)])

    async def update_one(self, query: dict, patch: dict) -> None:
        for row in self.rows.values():
            if _matches(row, query):
                row.update(patch.get("$set") or {})
                return

    async def delete_one(self, query: dict) -> None:
        for key, row in list(self.rows.items()):
            if _matches(row, query):
                del self.rows[key]
                return


class FakeDb:
    def __init__(self) -> None:
        self._collections: dict[str, Collection] = {}

    def __getitem__(self, name: str) -> Collection:
        return self._collections.setdefault(name, Collection())

    def __getattr__(self, name: str) -> Collection:
        return self[name]


def _patch_db(monkeypatch, db) -> None:
    for module in {id(m): m for m in (market, tools_module)}.values():
        monkeypatch.setattr(module, "get_db", lambda _db=db: _db)


def _seed(db: FakeDb, collection: str, doc: dict) -> None:
    """Insert synchronously from test code (Collection.insert_one is async)."""

    asyncio.run(db[collection].insert_one(doc))


def _user(tenant_id: str = "t1") -> dict:
    return {"tenant_id": tenant_id, "username": "alice"}


# ----------------------------------------------------------- template loading
def test_seed_templates_load_cleanly():
    templates = templates_service.load_templates(force=True)
    assert len(templates) >= 15, f"种子模板过少：{len(templates)}"
    assert templates_service.load_issues() == []
    for template in templates.values():
        assert template["name"].get("zh")
        assert template["params"]
        assert template["config_template"]["url"].startswith("http")


def test_template_categories_cover_five_buckets():
    categories = templates_service.template_categories()
    assert {"oa", "erp", "data", "devops", "im"} <= set(categories)


def test_suspected_real_credential_template_is_skipped(monkeypatch, tmp_path: Path):
    good = "id: x\nversion: 1\ncategory: oa\nname: {zh: x, en: x}\ndescription: {zh: x, en: x}\n"
    good += "auth_type: none\nconfig_template: {url: 'https://example.com', method: GET}\n"
    good += "params:\n  - key: token\n    label: {zh: 令牌, en: token}\n    secret: true\n"
    good += "    example: 'AKIA3XJ7K2LMNOPQRSTUVWXYZ0123456789abcdef'\n"
    (tmp_path / "bad.yaml").write_text(good, encoding="utf-8")

    monkeypatch.setattr(templates_service, "TEMPLATES_DIR", tmp_path)
    templates = templates_service.load_templates(force=True)
    assert templates == {}
    issues = templates_service.load_issues()
    assert issues and "疑似真实凭据" in issues[0]


def test_placeholder_credentials_are_accepted(monkeypatch, tmp_path: Path):
    body = "id: ok\nversion: 1\ncategory: oa\nname: {zh: x, en: x}\ndescription: {zh: x, en: x}\n"
    body += "auth_type: bearer\nconfig_template: {url: 'https://example.com', method: GET}\n"
    body += "params:\n  - key: token\n    label: {zh: 令牌, en: token}\n    secret: true\n"
    body += "    example: '<your-token>'\n"
    (tmp_path / "ok.yaml").write_text(body, encoding="utf-8")
    monkeypatch.setattr(templates_service, "TEMPLATES_DIR", tmp_path)
    assert set(templates_service.load_templates(force=True)) == {"ok"}


# --------------------------------------------------------------- render config
def test_render_config_header_credential_goes_to_auth_token():
    template = templates_service.get_template("gitlab-api")
    config = templates_service.render_config(
        template, {"host": "gitlab.example.com", "path": "projects", "token": "t0k3n"}
    )
    assert config["authType"] == "api_key"
    assert config["authToken"] == "t0k3n"
    assert config["apiKeyHeader"] == "PRIVATE-TOKEN"
    assert config["url"] == "https://{host}/api/v4/{path}"
    locations = {node["name"]: node["location"] for node in config["inputSchema"]}
    assert locations["host"] == "Path"
    assert locations["token"] == "Header"


def test_render_config_url_credential_never_lands_in_config():
    template = templates_service.get_template("dingtalk-webhook")
    config = templates_service.render_config(template, {"access_token": "s3cr3t", "text": "hi"})
    assert templates_service.credential_managed(template) is False
    assert "s3cr3t" not in str(config)
    assert "{access_token}" in config["url"]


def test_validate_values_reports_missing_and_type_errors():
    template = templates_service.get_template("gitlab-api")
    errors = templates_service.validate_values(template, {})
    assert any("必填" in item for item in errors)

    jenkins = templates_service.get_template("jenkins-rest")
    template = dict(jenkins)
    template["params"] = list(jenkins["params"]) + [
        {"key": "retries", "label": {"zh": "x", "en": "x"}, "type": "integer", "required": False, "in": "query"}
    ]
    errors = templates_service.validate_values(template, {"retries": "abc"})
    assert any("整数" in item for item in errors)


# -------------------------------------------------------------------- catalog
def test_list_templates_api_returns_catalog_and_counts(monkeypatch):
    db = FakeDb()
    _patch_db(monkeypatch, db)
    _seed(db, market.INSTALLS_COLLECTION, {"_id": "i1", "tenant_id": "t1", "template_id": "gitlab-api", "template_version": 1, "tool_id": "tool-1", "name": "GitLab"})

    result = asyncio.run(market.list_templates(category="", keyword="gitlab", current_user=_user()))
    assert result["categories"]
    assert len(result["templates"]) == 1
    row = result["templates"][0]
    assert row["id"] == "gitlab-api"
    assert row["installCount"] == 1
    assert row["installed"] is True
    assert row["credentialManaged"] is True


def test_get_template_unknown_id_raises_404():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(market.get_template("nope", current_user=_user()))
    assert excinfo.value.status_code == 404


# -------------------------------------------------------------------- install
def test_install_template_reuses_external_tools_storage(monkeypatch):
    db = FakeDb()
    _patch_db(monkeypatch, db)

    result = asyncio.run(
        market.install_template(
            "gitlab-api",
            market.InstallPayload(
                name="GitLab 生产",
                values={"host": "gitlab.example.com", "path": "projects", "token": "t0k3n"},
            ),
            current_user=_user(),
        )
    )
    tool = result["tool"]
    assert result["templateId"] == "gitlab-api"
    assert result["credentialManaged"] is True
    assert tool["status"] == "disabled"

    rows = list(db["external_tools"].rows.values())
    assert len(rows) == 1
    row = rows[0]
    assert row["tenant_id"] == "t1"
    assert row["type"] == "http"
    assert row["config"]["authType"] == "api_key"
    assert row["config"]["inputSchema"]
    assert "connector" in row["tags"]

    installs = list(db[market.INSTALLS_COLLECTION].rows.values())
    assert len(installs) == 1
    assert installs[0]["tool_id"] == tool["id"]
    assert installs[0]["template_id"] == "gitlab-api"


def test_install_template_rejects_missing_required_param(monkeypatch):
    from fastapi import HTTPException

    db = FakeDb()
    _patch_db(monkeypatch, db)
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            market.install_template(
                "gitlab-api",
                market.InstallPayload(values={"host": "h"}),
                current_user=_user(),
            )
        )
    assert excinfo.value.status_code == 400
    assert db["external_tools"].rows == {}


def test_install_template_activate_sets_status(monkeypatch):
    db = FakeDb()
    _patch_db(monkeypatch, db)
    result = asyncio.run(
        market.install_template(
            "dingtalk-webhook",
            market.InstallPayload(values={"access_token": "abc", "text": "hi"}, activate=True),
            current_user=_user(),
        )
    )
    assert result["tool"]["status"] == "active"
    assert result["credentialManaged"] is False


def test_install_counts_are_per_template(monkeypatch):
    db = FakeDb()
    _patch_db(monkeypatch, db)
    for template_id, tool_id in (("gitlab-api", "a"), ("gitlab-api", "b"), ("slack-webhook", "c")):
        _seed(db, market.INSTALLS_COLLECTION, {"_id": tool_id, "tenant_id": "t1", "template_id": template_id, "tool_id": tool_id, "template_version": 1})
    _seed(db, market.INSTALLS_COLLECTION, {"_id": "other", "tenant_id": "t2", "template_id": "gitlab-api", "tool_id": "x", "template_version": 1})
    result = asyncio.run(market.install_counts(current_user=_user()))
    assert result["counts"] == {"gitlab-api": 2, "slack-webhook": 1}
    assert result["total"] == 3


# ------------------------------------------------------------------- installs
def test_list_installs_marks_manual_and_template_sources(monkeypatch):
    db = FakeDb()
    _patch_db(monkeypatch, db)
    _seed(db, market.TOOLS_COLLECTION, {"_id": "manual-1", "tenant_id": "t1", "name": "手工工具", "status": "active",
         "config": {"url": "https://x", "authToken": "secret"}, "created_at": "2026-01-01"})
    _seed(db, market.TOOLS_COLLECTION, {"_id": "tool-2", "tenant_id": "t1", "name": "来自模板", "status": "disabled",
         "config": {"url": "https://y"}, "created_at": "2026-01-02"})
    _seed(db, market.INSTALLS_COLLECTION, {"_id": "i2", "tenant_id": "t1", "template_id": "gitlab-api", "tool_id": "tool-2",
         "template_version": 1, "created_at": "2026-01-02"})

    result = asyncio.run(market.list_installs(current_user=_user()))
    by_id = {item["toolId"]: item for item in result["items"]}
    assert by_id["manual-1"]["source"] == "manual"
    assert by_id["tool-2"]["source"] == "template"
    assert by_id["tool-2"]["templateId"] == "gitlab-api"
    # 凭证在视图里必须脱敏
    assert by_id["manual-1"]["config"]["authToken"] != "secret"
