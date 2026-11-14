from __future__ import annotations

from fastapi.testclient import TestClient

from app import main


def test_queue_setting_requires_manager_token(monkeypatch) -> None:
    monkeypatch.setenv("MOGO_SANDBOX_MANAGER_TOKEN", "a" * 64)
    client = TestClient(main.app)
    assert client.put("/v1/settings", json={"max_pending": 3}).status_code == 401


def test_queue_setting_is_validated_and_applied(monkeypatch) -> None:
    monkeypatch.setenv("MOGO_SANDBOX_MANAGER_TOKEN", "a" * 64)

    class JobsFake:
        def set_max_pending(self, value):
            return {"max_pending": value}

    monkeypatch.setattr(main, "jobs", lambda: JobsFake())
    client = TestClient(main.app)
    headers = {"Authorization": f"Bearer {'a' * 64}"}
    assert client.put("/v1/settings", json={"max_pending": 101}, headers=headers).status_code == 422
    response = client.put("/v1/settings", json={"max_pending": 3}, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"max_pending": 3}
