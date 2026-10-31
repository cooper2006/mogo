"""Crash-safe metadata for reusable script task containers."""

from __future__ import annotations

import json
import os
from pathlib import Path


class TaskLeaseStore:
    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "script-task-leases.json"

    def load(self) -> dict[str, dict]:
        if not self.path.is_file():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    def save(self, leases: dict[str, dict]) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(leases, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.path)
