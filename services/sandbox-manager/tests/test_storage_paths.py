from __future__ import annotations

import json
from pathlib import Path

from app.lease_store import LeaseStore
from app.settings_store import SettingsStore


def test_manager_state_writes_outside_dsh_runtime_volume(tmp_path: Path) -> None:
    runtime = tmp_path / "dsh-runtime"
    runtime.mkdir()
    workspace = tmp_path / "sandbox-workspaces" / ".manager-state"
    settings = SettingsStore(workspace, legacy_root=runtime)
    leases = LeaseStore(workspace, legacy_root=runtime)
    settings.save_max_pending(4)
    leases.save({"lease": {"container_id": "container"}})
    assert settings.max_pending(8) == 4
    assert leases.load()["lease"]["container_id"] == "container"
    assert list(runtime.iterdir()) == []


def test_legacy_state_is_read_without_writing_to_legacy_volume(tmp_path: Path) -> None:
    runtime = tmp_path / "dsh-runtime"
    runtime.mkdir()
    (runtime / "sandbox-settings.json").write_text(json.dumps({"max_pending": 3}))
    (runtime / "sandbox-plugin-leases.json").write_text(json.dumps({"old": {"container_id": "old"}}))
    workspace = tmp_path / "sandbox-workspaces" / ".manager-state"
    assert SettingsStore(workspace, legacy_root=runtime).max_pending(8) == 3
    assert LeaseStore(workspace, legacy_root=runtime).load()["old"]["container_id"] == "old"
    assert not workspace.exists()
