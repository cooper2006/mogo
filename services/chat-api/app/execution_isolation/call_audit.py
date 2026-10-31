"""Per-call records kept with the task workspace for later audit archiving."""

from __future__ import annotations

import json
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .script_backend import task_workspace


def record_call(
    call_dir: Path, *, action_id: str, skill_digest: str, duration_ms: int,
    status: str, stdout: str = "", stderr: str = "", error: str = "",
    started_ns: int = 0, image_ref: str = "",
) -> None:
    task_root = call_dir.parents[2]
    audit_dir = task_root / "audit" / call_dir.name
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "stdout.log").write_text(stdout, encoding="utf-8")
    (audit_dir / "stderr.log").write_text(stderr, encoding="utf-8")
    snapshots: list[dict] = []
    total = 0
    for path in sorted((task_root / "work").rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        if call_dir not in path.parents and path.stat().st_mtime_ns < started_ns:
            continue
        relative = path.relative_to(task_root / "work")
        size = path.stat().st_size
        total += size
        if total > 512 * 1024 * 1024:
            raise ValueError("Call audit snapshot exceeds the size limit")
        target = audit_dir / "files" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        snapshots.append({"path": relative.as_posix(), "size": size,
                          "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    (audit_dir / "audit.json").write_text(json.dumps({
        "action_id": action_id,
        "skill_digest": skill_digest,
        "image_ref": image_ref,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": duration_ms,
        "status": status,
        "error": error[:8000],
        "files": snapshots,
    }, ensure_ascii=False), encoding="utf-8")


def record_rejected_code(message_id: str, action_id: str, code: str, error: str) -> None:
    workspace = task_workspace(message_id)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "work").mkdir(exist_ok=True)
    call_dir = workspace / "work" / "calls" / uuid4().hex
    call_dir.mkdir(parents=True)
    (call_dir / "source.py").write_text(code, encoding="utf-8")
    record_call(call_dir, action_id=action_id, skill_digest="", duration_ms=0,
                status="rejected", error=error)
