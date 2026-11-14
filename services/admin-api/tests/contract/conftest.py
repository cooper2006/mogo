"""T039 契约验证环境隔离 fixture（FR-24, US3-10）。

契约测试只使用 FastAPI 内建的 `app.openapi()` 生成 schema，**不连数据库、不发起真实
HTTP 请求、不依赖共享可变环境**（DB/Redis 状态、外部服务可达性、环境变量）。

本 conftest 对 `tests/contract/` 下所有测试自动生效：
  1. 清除可能触发真实连接/外部依赖的环境变量（MongoDB / Redis / PanWeiDB / Weaviate /
     KMS / OTEL / OSS / 上游服务地址）；
  2. 把当前工作目录切到临时目录，避免读写工作区内的共享文件；
  3. monkeypatch 在测试结束后自动恢复，不影响其他测试套件。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# 与「真实连接 / 外部服务」相关的环境变量前缀。这些变量的存在不会影响 openapi 生成，
# 但可能触发连接池初始化或外部请求，契约测试应与其无关。
CONNECTION_ENV_PREFIXES = (
    "MONGODB_",
    "REDIS_",
    "PANWEIDB_",
    "WEAVIATE_",
    "ASKAI_ADMIN_",
    "MOGO_DOC_PROCESSING_",
    "MOGO_DATA_",
    "MOGO_KMS_",
    "MOGO_TTL_",
    "OSS_",
    "OTEL_",
    "KAFKA_",
    "RABBITMQ_",
    "NATS_",
    "DATABASE_",
    "DB_",
    "POSTGRES_",
    "MYSQL_",
    "ADMIN_BACKEND_",
    "ASKAI_API_",
    "GATE_",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """清除连接类环境变量并把 cwd 切到临时目录（FR-24 环境隔离）。"""
    for key in list(os.environ.keys()):
        if key.startswith(CONNECTION_ENV_PREFIXES):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path
