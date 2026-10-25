"""023 T091 — 重试退避（FR-23）。

验证指数退避 + ±10% 抖动、可重试状态码（429/5xx）与不可重试（401/403）。
"""
from __future__ import annotations

import pytest

from app.common.dependency_guard import (
    RETRY_BASE_SECONDS,
    RETRY_MAX_SECONDS,
    backoff_delay,
    is_retryable_status,
    retry_sync,
)


def test_backoff_base_is_007_aligned():
    """与 007 既有实现对齐：base 1.5s、上限 30s。"""
    assert RETRY_BASE_SECONDS == 1.5
    assert RETRY_MAX_SECONDS == 30.0


def test_backoff_delay_grows_exponentially_then_caps():
    raw = [backoff_delay(n) for n in (1, 2, 3, 4, 5)]
    assert raw[0] == pytest.approx(1.5, rel=0.20)
    assert raw[1] == pytest.approx(3.0, rel=0.20)
    assert raw[3] == pytest.approx(12.0, rel=0.20)
    assert all(v <= RETRY_MAX_SECONDS * 1.10 for v in raw)


def test_backoff_delay_has_jitter_within_ten_percent():
    samples = {round(backoff_delay(2), 6) for _ in range(30)}
    assert len(samples) > 1, "抖动缺失：多次取到同一值"
    for value in samples:
        assert abs(value - 3.0) <= 3.0 * 0.10 + 1e-9


def test_backoff_delay_rejects_non_positive_attempt():
    with pytest.raises(ValueError):
        backoff_delay(0)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retryable_statuses(status):
    assert is_retryable_status(status) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_non_retryable_statuses(status):
    assert is_retryable_status(status) is False


def test_retry_sync_stops_after_success():
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("blip")
        return "ok"

    assert retry_sync(flaky, max_attempts=3, sleep=lambda _s: None) == "ok"
    assert calls["n"] == 3


def test_retry_sync_gives_up_and_reraises_last_error():
    def always_down() -> str:
        raise ConnectionError("still down")

    with pytest.raises(ConnectionError):
        retry_sync(always_down, max_attempts=2, sleep=lambda _s: None)
