"""Durable metadata for plugin container leases across manager restarts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4


class LeaseStore:
    def __init__(self, root: Path, *, legacy_root: Path | None = None) -> None:
        self.path = root / "sandbox-plugin-leases.json"
        self.legacy_path = legacy_root / "sandbox-plugin-leases.json" if legacy_root else None

    def load(self) -> dict[str, dict]:
        source = self.path if self.path.exists() else self.legacy_path
        if source is None or not source.exists():
            return {}
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not all(isinstance(item, dict) for item in data.values()):
            raise ValueError("Invalid sandbox plugin lease store")
        return data

    def save(self, leases: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                os.chmod(temporary, 0o600)
                json.dump(leases, stream, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
