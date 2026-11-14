"""T036 消费方侧契约证据校验工具测试（FR-16 / FR-17）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.contract.consumer_refs import (
    NO_CONSUMER_ALLOWLIST,
    _is_no_consumer,
    _path_of,
    check_contract_consumers,
    collect_urls,
    main,
    normalize_url,
    iter_source_files,
)


# ---------- normalize_url / _path_of ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/api/skills", "/api/skills"),
        ("http://127.0.0.1:8200/api/jobs/document-parse", "/api/jobs/document-parse"),
        ("{base_url}/api/jobs/document-parse", "/<p>/api/jobs/document-parse"),
        ("/api/tenants/${id}/admin", "/api/tenants/<p>/admin"),
        ("/api/sessions/search?page=1", "/api/sessions/search"),
        ("/api/documents/parse-markdown#frag", "/api/documents/parse-markdown"),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


def test_path_of_returns_none_without_slash() -> None:
    assert _path_of("hello world") is None
    assert _path_of("no-path") is None


# ---------- collect_urls ----------


def test_collect_urls_skips_short_paths(tmp_path) -> None:
    f = tmp_path / "a.ts"
    f.write_text(
        'const a = "/api/x";\nconst b = "/api";\nconst c = `${base}/api/y`;\nconst d = "plain";\n',
        encoding="utf-8",
    )
    urls = collect_urls(iter_source_files(tmp_path))
    assert "/api/x" in urls
    assert "/api/y" in urls
    assert "/api" not in urls  # 单段路径被过滤
    assert "/api/y".startswith("/api/")  # 后缀命中基础


# ---------- 契约消费方证据校验 ----------


def _contract() -> dict:
    return {
        "name": "demo",
        "version": "1.0.0",
        "provider": "demo",
        "consumers": ["web"],
        "base_path": "/api",
        "interactions": [
            {
                "id": "list_skills",
                "method": "GET",
                "path": "/skills",
                "notes": "apps/admin-web/src/api/skills.ts",
                "responses": [
                    {
                        "status": 200,
                        "fields": {"id": {"type": "str"}, "name": {"type": "str"}},
                    }
                ],
            },
            {
                "id": "get_skill",
                "method": "GET",
                "path": "/skills/{skill_id}",
                "responses": [{"status": 200, "fields": {"id": {"type": "str"}}}],
            },
            {
                "id": "orphan_endpoint",
                "method": "POST",
                "path": "/orphan",
                "notes": "管理端端点，当前无消费方",
                "responses": [{"status": 200, "fields": {"id": {"type": "str"}}}],
            },
        ],
    }


def _write_source(tmp_path) -> Path:
    src = tmp_path / "apps" / "web" / "src"
    src.mkdir(parents=True)
    (src / "skills.ts").write_text(
        'export async function listSkills() { return client.get("/api/skills"); }\n'
        'export async function getSkill(id: string) { return client.get(`/askai-api/api/skills/${id}`); }\n',
        encoding="utf-8",
    )
    return src


def test_all_interactions_have_consumer_evidence(tmp_path) -> None:
    src = _write_source(tmp_path)
    ok, report = check_contract_consumers(_contract(), [src], "demo")
    assert ok, report
    assert not any(line.startswith("[error]") for line in report)


def test_orphan_endpoint_without_note_is_error(tmp_path) -> None:
    src = _write_source(tmp_path)
    contract = _contract()
    contract["interactions"][2]["notes"] = ""  # 移除零消费方标注
    ok, report = check_contract_consumers(contract, [src], "demo")
    assert not ok
    assert any("无调用证据" in line for line in report)


def test_orphan_endpoint_marked_no_consumer_is_warn(tmp_path) -> None:
    src = _write_source(tmp_path)
    ok, report = check_contract_consumers(_contract(), [src], "demo")
    assert ok
    assert any("[warn]" in line and "不阻断" in line for line in report)


def test_allowlist_exempts_id(tmp_path) -> None:
    src = _write_source(tmp_path)
    contract = _contract()
    contract["interactions"][2]["notes"] = ""
    ok, report = check_contract_consumers(contract, [src], "demo")
    assert not ok  # 未登记白名单 → error
    contract2 = _contract()
    contract2["interactions"][2]["notes"] = ""
    contract2["interactions"][2]["id"] = "orphan_endpoint"
    # 临时把 orphan_endpoint 加入白名单（demo 服务）
    NO_CONSUMER_ALLOWLIST.setdefault("demo", set()).add("orphan_endpoint")
    try:
        ok2, report2 = check_contract_consumers(contract2, [src], "demo")
    finally:
        NO_CONSUMER_ALLOWLIST["demo"].discard("orphan_endpoint")
        if not NO_CONSUMER_ALLOWLIST["demo"]:
            del NO_CONSUMER_ALLOWLIST["demo"]
    assert ok2
    assert any("不阻断" in line for line in report2)


def test_missing_source_dir_is_error(tmp_path) -> None:
    ok, report = check_contract_consumers(_contract(), [tmp_path / "nope"], "demo")
    assert not ok
    assert any("源码目录为空" in line for line in report)


def test_missing_notes_file_is_error(tmp_path) -> None:
    src = _write_source(tmp_path)
    contract = _contract()
    contract["interactions"][0]["notes"] = "apps/web/src/does_not_exist.ts"
    ok, report = check_contract_consumers(contract, [src], "demo")
    assert not ok
    assert any("消费方文件不存在" in line for line in report)


# ---------- _is_no_consumer ----------


@pytest.mark.parametrize(
    "note",
    [
        "零消费方，保留登记",
        "本端点无消费方，待接线",
        "no front-end consumer yet",
    ],
)
def test_is_no_consumer_true(note: str) -> None:
    assert _is_no_consumer({"id": "x", "notes": note, "responses": []})


def test_is_no_consumer_false() -> None:
    assert not _is_no_consumer({"id": "x", "notes": "apps/web/src/api.ts", "responses": []})


def test_is_no_consumer_in_response_notes() -> None:
    item = {"id": "x", "responses": [{"status": 200, "notes": "当前无消费方，仅登记"}]}
    assert _is_no_consumer(item)


# ---------- CLI ----------

REPO = Path(__file__).resolve().parents[2]


def test_main_all_real_contracts_pass() -> None:
    rc = main(["--all"])
    assert rc == 0, "三份真实契约的消费方证据应齐备（或已登记零消费方）"


def test_main_service_ok() -> None:
    assert main(["--service", "admin-api"]) == 0
    assert main(["--service", "chat-api"]) == 0
    assert main(["--service", "document-parser"]) == 0


def test_main_missing_source_exits_one() -> None:
    assert main(["--service", "admin-api", "--source", str(REPO / "nope-src")]) == 1
