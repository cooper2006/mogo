from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from bson import BSON

from app.enterprise_capabilities.artifacts.document_result import public_document_parse_result
from app.enterprise_capabilities.data.script import run_script
from app.enterprise_capabilities.runtime.contracts import CapabilityExecutionContext
from app.enterprise_capabilities.tools.persistence_codec import restore_json_field, store_json_field
from app.enterprise_capabilities.tools.repository import EnterpriseToolRepository
from app.services.runtime_parse_service import RuntimeParseService


def _context(**turn_context) -> CapabilityExecutionContext:
    return CapabilityExecutionContext(
        tenant_id="tenant-a",
        user_id="user-a",
        conversation_id="conversation-a",
        kernel_session_id="session-a",
        profile_version="profile-a",
        action_id="action-a",
        turn_context=turn_context,
    )


def test_tool_receipt_json_field_round_trips_mongo_unsafe_parser_data() -> None:
    unsafe_result = {
        "structured_content": {
            "body": {"children": [{"$ref": "#/texts/0"}]},
            "origin": {"binary_hash": 10941865328962521312},
        }
    }
    row = store_json_field(
        {
            "schema_version": "askai.enterprise-action-receipt.v1",
            "action_id": "action-a",
            "idempotency_key": "idem-a",
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "conversation_id": "conversation-a",
            "kernel_session_id": "session-a",
            "profile_version": "profile-a",
            "tool_name": "document_parse",
            "status": "succeeded",
            "result": unsafe_result,
            "error": "",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        },
        "result",
    )

    BSON.encode(row)
    assert restore_json_field(row, "result")["result"] == unsafe_result
    assert EnterpriseToolRepository._receipt(row).result == unsafe_result


def test_document_result_hides_docling_tree_but_keeps_markdown_contract() -> None:
    raw = {
        "parsed_documents": [{
            "filename": "invoice.pdf",
            "markdown": "# 发票\n金额 216.40 元",
            "structured_content": {"body": {"children": [{"$ref": "#/texts/0"}]}},
            "parse_quality": {"score": 1.0},
        }],
        "documents": {"parsed_documents": [{
            "filename": "invoice.pdf",
            "markdown": "# 发票\n金额 216.40 元",
            "structured_content": {"origin": {"binary_hash": 2**80}},
        }]},
        "active_document_markdown": "# 发票\n金额 216.40 元",
    }

    projected = public_document_parse_result(raw)

    assert projected["parsed_documents"][0]["markdown"].endswith("216.40 元")
    assert "structured_content" not in projected["parsed_documents"][0]
    assert "parsed_documents" not in projected["documents"]
    assert "active_document_markdown" not in projected["documents"]


def test_object_path_alone_is_recognized_and_normalized_as_document() -> None:
    artifact = {"object_path": "user-a/2026/08/invoice.pdf"}
    assert RuntimeParseService._looks_like_document(artifact) is True
    assert RuntimeParseService._normalize_file(artifact)["filename"] == "invoice.pdf"


def test_every_script_invocation_inherits_turn_file_and_prints_utf8(monkeypatch) -> None:
    content = "中文附件内容：金额 216.40 元"
    monkeypatch.setattr(
        "app.enterprise_capabilities.data.script_engine.executor.AliyunOSSUploader.read_bytes",
        lambda _self, object_path: content.encode("utf-8"),
    )
    context = _context(documents=[{
        "object_path": "user-a/2026/08/invoice.txt",
        "filename": "中文发票.txt",
        "content_type": "text/plain",
    }])
    arguments = {
        "code": "with open(input_files[0]['local_path'], encoding='utf-8') as f:\n    print(f.read())",
    }

    first = asyncio.run(run_script(arguments, context))
    second = asyncio.run(run_script(arguments, context))

    assert first["plugin_result"]["data"]["stdout"] == [content]
    assert second["plugin_result"]["data"]["stdout"] == [content]


def test_script_error_summary_preserves_actionable_exception_tail(monkeypatch) -> None:
    from app.enterprise_capabilities.data.script_engine.error_summary import execution_error_summary

    error = RuntimeError("prefix " + "x" * 1200 + "\nFileNotFoundError: inputs/invoice.pdf")
    summary = execution_error_summary(error, max_chars=300)

    assert len(summary) <= 300
    assert summary.endswith("FileNotFoundError: inputs/invoice.pdf")


def _stub_uploader(monkeypatch, content: bytes) -> None:
    monkeypatch.setattr(
        "app.enterprise_capabilities.data.script_engine.executor.AliyunOSSUploader.read_bytes",
        lambda _self, object_path: content,
    )


def _file_context() -> CapabilityExecutionContext:
    return _context(documents=[{
        "object_path": "user-a/2026/08/in.txt",
        "filename": "in.txt",
        "content_type": "text/plain",
    }])


def test_module_level_file_read_is_guarded_before_plugin_import() -> None:
    """SEC-01: the file guard must be installed before exec_module runs.

    Plugin top-level statements execute at import time. If the guard is
    installed afterwards, a module-level ``open()`` reaches the raw builtin.
    """
    code = (
        "try:\n"
        "    _LEAK = open('/etc/hosts').read()[:16]\n"
        "except Exception as exc:\n"
        "    _LEAK = type(exc).__name__\n"
        "\n"
        "def run(inputs, context):\n"
        "    return {'data': {'toplevel': _LEAK}, 'artifacts': [], 'logs': []}\n"
    )

    result = asyncio.run(run_script({"code": code}, _context()))

    assert result["plugin_result"]["data"]["toplevel"] == "PermissionError"


def test_io_fileio_cannot_escape_work_dir() -> None:
    """SEC-01: patching ``open`` alone is not a boundary; FileIO must be covered."""
    code = (
        "def run(inputs, context):\n"
        "    import _io\n"
        "    import io\n"
        "    out = {}\n"
        "    for label, factory in (('io', io.FileIO), ('_io', _io.FileIO)):\n"
        "        try:\n"
        "            factory('/etc/hosts').read()\n"
        "            out[label] = 'LEAKED'\n"
        "        except Exception as exc:\n"
        "            out[label] = type(exc).__name__\n"
        "    return {'data': out, 'artifacts': [], 'logs': []}\n"
    )

    result = asyncio.run(run_script({"code": code}, _context()))

    data = result["plugin_result"]["data"]
    assert data["io"] == "PermissionError"
    assert data["_io"] == "PermissionError"


def test_os_scandir_cannot_escape_work_dir() -> None:
    """SEC-01: directory enumeration outside work_dir must be refused."""
    code = (
        "def run(inputs, context):\n"
        "    import os\n"
        "    try:\n"
        "        names = [entry.name for entry in os.scandir('/etc')][:3]\n"
        "        listing = 'LEAKED:' + ','.join(names)\n"
        "    except Exception as exc:\n"
        "        listing = type(exc).__name__\n"
        "    return {'data': {'scandir': listing}, 'artifacts': [], 'logs': []}\n"
    )

    result = asyncio.run(run_script({"code": code}, _context()))

    assert result["plugin_result"]["data"]["scandir"] == "PermissionError"


def test_script_plugin_still_reads_inputs_and_writes_outputs(monkeypatch) -> None:
    """The guard must not break legitimate input reads, output writes or imports."""
    _stub_uploader(monkeypatch, "中文内容 216.40".encode("utf-8"))
    code = (
        "import collections, csv, datetime, io, json, math, os, statistics, zipfile\n"
        "with open(input_files[0]['local_path'], encoding='utf-8') as f:\n"
        "    text = f.read()\n"
        "target = os.path.join(context['output_dir'], 'copy.txt')\n"
        "with open(target, 'w', encoding='utf-8') as f:\n"
        "    f.write(text)\n"
        "print(text)\n"
    )

    result = asyncio.run(run_script({"code": code}, _file_context()))

    assert result["plugin_result"]["data"]["stdout"] == ["中文内容 216.40"]
    exported = result["exported_file"]["documents"]
    assert [item["filename"] for item in exported] == ["copy.txt"]


def test_run_style_plugin_reads_input_file_inside_work_dir(monkeypatch) -> None:
    """A ``run``-style plugin keeps read access to materialized inputs."""
    _stub_uploader(monkeypatch, b"payload")
    code = (
        "def run(inputs, context):\n"
        "    with open(inputs['files'][0]['local_path'], encoding='utf-8') as f:\n"
        "        text = f.read()\n"
        "    return {'data': {'text': text}, 'artifacts': [], 'logs': []}\n"
    )

    result = asyncio.run(run_script({"code": code}, _file_context()))

    assert result["plugin_result"]["data"]["text"] == "payload"


def test_allowlisted_libraries_still_import_at_module_level(monkeypatch) -> None:
    """SEC-01 regression: installing the guard before exec_module must not break
    allowlisted library imports.

    ``openpyxl`` reads system config while importing, so a plugin that imports it
    at module level would fail once the guard runs first. The runner therefore
    warms the allowlisted modules before installing the guard.
    """
    _stub_uploader(monkeypatch, b"payload")
    code = (
        "import collections, csv, datetime, docx, math, openpyxl, os, zipfile\n"
        "def run(inputs, context):\n"
        "    wb = openpyxl.Workbook()\n"
        "    wb.active['A1'] = 'ok'\n"
        "    target = os.path.join(context['output_dir'], 'book.xlsx')\n"
        "    wb.save(target)\n"
        "    return {'data': {'sheets': wb.sheetnames, 'size': os.path.getsize(target)},\n"
        "            'artifacts': [{'path': target, 'filename': 'book.xlsx'}], 'logs': []}\n"
    )

    result = asyncio.run(run_script({"code": code}, _file_context()))

    data = result["plugin_result"]["data"]
    assert data["sheets"] == ["Sheet"]
    assert data["size"] > 0
    assert [item["filename"] for item in result["exported_file"]["documents"]] == ["book.xlsx"]
