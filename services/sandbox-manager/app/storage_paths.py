"""Writable sandbox-manager paths, separate from the DSH Runtime volume."""

from __future__ import annotations

import os
from pathlib import Path


def workspace_root() -> Path:
    return Path(os.environ.get("MOGO_SANDBOX_WORKSPACE_ROOT", "/workspaces"))


def manager_state_root() -> Path:
    return workspace_root() / ".manager-state"


def legacy_runtime_root() -> Path:
    return Path(os.environ.get("MOGO_SANDBOX_RUNTIME_ROOT", "/runtime-data"))
