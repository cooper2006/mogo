"""Execution placement is a server policy, never a model argument.

The installed DSH bundle format does not prove that a plugin is a standalone
program. A future standalone format must carry a verified execution contract
before it can use the task executor.
"""

from __future__ import annotations

from enum import Enum
from typing import Mapping, Any


class ExecutionTarget(str, Enum):
    SHARED_RUNTIME = "shared_runtime"
    TASK_CONTAINER = "task_container"
    PLUGIN_RUNTIME_CONTAINER = "plugin_runtime_container"


_CODE_CAPABILITIES = frozenset({"data.run_script@v1", "file.run_script_plugin"})
_TRUSTED_CAPABILITIES = frozenset({
    "artifact.export@v1", "artifact.table_generate@v1", "browser.task@v1",
    "content.produce@v1", "data.compute_metrics@v1", "document.annotate@v1",
    "document.extract_resources@v1", "document.fill_form@v1", "document.parse@v1",
    "document.pdf_retain_pages@v1", "document.review_source@v1",
    "document.transform@v1", "image.generate@v1", "knowledge.read_document@v1",
    "knowledge.search@v1", "presentation.create@v1", "research.collect_url@v1",
    "research.progressive@v1", "research.search_web@v1",
    "skills.install_skillhub@v1", "vision.extract_facts@v1",
})


def route_capability(capability_ref: str) -> ExecutionTarget:
    """Classify a known tool at invocation time, not its Skill package."""
    if capability_ref in _CODE_CAPABILITIES:
        return ExecutionTarget.TASK_CONTAINER
    if capability_ref in _TRUSTED_CAPABILITIES:
        return ExecutionTarget.SHARED_RUNTIME
    raise ValueError("Capability execution route is not registered")


def route_plugin(installation: Mapping[str, Any]) -> ExecutionTarget:
    """Fail closed for unknown formats and unverified standalone executables."""
    engine = str(installation.get("engine") or "")
    if engine == "dsh":
        return ExecutionTarget.PLUGIN_RUNTIME_CONTAINER
    if engine == "standalone" and installation.get("execution_contract_verified") is True:
        return ExecutionTarget.TASK_CONTAINER
    raise ValueError("Plugin execution format is not verified")
