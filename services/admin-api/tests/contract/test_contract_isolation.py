"""T039 契约验证环境隔离测试（FR-24, US3-10）。

验证 `tests/contract/` 下的契约测试**不依赖共享可变环境**：
  1. 契约测试源码不 import 任何网络 / 数据库客户端；
  2. 契约测试源码不引用真实外部服务地址（http/https 字面量仅允许出现在注释说明中）；
  3. `conftest.py` 的 `isolated_env`（autouse）清除连接类环境变量并把 cwd 切到临时目录；
  4. 清除连接类环境变量后 `create_app().openapi()` 仍能生成 schema（不发请求、不连库）；
  5. 调用不产生工作区共享状态副作用（不新增 *.db / *.sqlite / *.log）。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
CONTRACT_DIR = REPO / "services" / "admin-api" / "tests" / "contract"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "services" / "admin-api"))

from app.main import create_app  # noqa: E402

# 契约测试禁止出现的 import（真实连接 / 网络客户端）
FORBIDDEN_IMPORTS = (
    "requests",
    "httpx",
    "sqlalchemy",
    "asyncpg",
    "psycopg",
    "psycopg2",
    "redis",
    "motor",
    "pymongo",
    "clickhouse",
    "kafka",
    "aiokafka",
    "openai",
    "boto3",
    "weaviate",
    "elasticsearch",
)

FORBIDDEN_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+(" + "|".join(re.escape(x) for x in FORBIDDEN_IMPORTS) + r")(?:\.|\s|$)",
    re.MULTILINE,
)

# 真实服务地址形态：scheme://host.tld[/path]，避免命中源码里 "http://" 字符串常量本身
LIVE_URL_RE = re.compile(r"(?:https?://|//)[A-Za-z0-9._-]+\.[A-Za-z]{2,}(?:/[^\s\"'`)]*)?")


def _test_files() -> list[Path]:
    return sorted(CONTRACT_DIR.glob("*.py"))


def test_contract_tests_do_not_import_network_db_clients() -> None:
    violations: list[str] = []
    for f in _test_files():
        for line_no, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if FORBIDDEN_IMPORT_RE.search(line):
                violations.append(f"{f.name}:{line_no}: {line.strip()}")
    assert not violations, "契约测试不得 import 网络 / 数据库客户端:\n" + "\n".join(violations)


def test_contract_tests_have_no_live_service_urls() -> None:
    """契约测试源码的**代码行**不得引用真实服务地址（注释与文档字符串允许示例）。"""
    live: list[str] = []
    for f in _test_files():
        in_doc = False
        for line_no, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if s.startswith(('"""', "'''")):
                # 单行文档串（开头和结尾都在同一行）
                if s.count('"""') >= 2 or s.count("'''") >= 2:
                    continue
                in_doc = not in_doc
                continue
            if in_doc or s.startswith("#"):
                continue
            if LIVE_URL_RE.search(line):
                live.append(f"{f.name}:{line_no}: {line.strip()}")
    assert not live, "契约测试不得在代码中引用真实服务地址:\n" + "\n".join(live)


def test_openapi_generates_after_clearing_connection_env(isolated_env) -> None:
    """清除连接类环境变量后 openapi 仍能生成（不连库、不发请求）。"""
    spec = create_app().openapi()
    assert spec.get("openapi", "").startswith("3.")
    assert spec.get("paths"), "openapi 应至少含一条 path"


def test_openapi_does_not_write_shared_state(isolated_env) -> None:
    """openapi 调用不得在工作区根新增 *.db / *.sqlite* / *.log 文件。"""
    before = {p.name for p in REPO.glob("*") if p.suffix in (".db", ".log") or ".sqlite" in p.name}
    create_app().openapi()
    after = {p.name for p in REPO.glob("*") if p.suffix in (".db", ".log") or ".sqlite" in p.name}
    assert after == before, f"契约测试产生共享状态副作用: 新增 {after - before}"


def test_connection_env_prefixes_defined() -> None:
    """conftest 必须登记连接类环境变量前缀（MongoDB/Redis/PanWeiDB/Weaviate 等）。"""
    conftest = CONTRACT_DIR / "conftest.py"
    assert conftest.exists()
    text = conftest.read_text(encoding="utf-8")
    assert "CONNECTION_ENV_PREFIXES" in text
    for prefix in ("MONGODB_", "REDIS_", "PANWEIDB_", "WEAVIATE_", "OTEL_", "KMS_"):
        assert prefix in text, f"conftest 未登记连接类前缀 {prefix}"
    assert "autouse=True" in text


def test_isolated_env_chdirs_to_tmp(isolated_env) -> None:
    """isolated_env fixture 把 cwd 切到临时目录（避免读写工作区共享文件）。"""
    assert isolated_env.is_dir()
    assert Path.cwd() == isolated_env
    assert isolated_env != REPO
