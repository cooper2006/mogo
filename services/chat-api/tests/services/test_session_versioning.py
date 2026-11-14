"""Tests for session versioning core (feature 002): secrets / placeholders / timeline."""

from __future__ import annotations

import pytest

from app.services.session_versioning.placeholder import (
    DereferenceDenied,
    PlaceholderStore,
    dereference,
    placeholder_ids,
    redacted_text_is_clean,
    reference,
)
from app.services.session_versioning.secrets import (
    ENTROPY_THRESHOLD_BITS_PER_CHAR,
    MIN_SECRET_LENGTH,
    detect_secrets,
    is_high_entropy,
    shannon_entropy,
)
from app.services.session_versioning.timeline import (
    LinearTimelineError,
    Timeline,
    check_and_advance,
    merge_linear,
)

HIGH_ENTROPY = "sk-aB3xK9mQ2pL7wZ4tR8yU1iO6nM5vC0dF"  # long, high entropy, sk- prefix


# --- secrets -----------------------------------------------------------------

def test_shannon_entropy_empty_is_zero() -> None:
    assert shannon_entropy("") == 0.0


def test_shannon_entropy_of_repeated_char_is_zero() -> None:
    assert shannon_entropy("aaaaaaaa") == 0.0


def test_high_entropy_requires_length_and_entropy() -> None:
    assert is_high_entropy(HIGH_ENTROPY)
    assert not is_high_entropy("short")             # too short
    assert not is_high_entropy("a" * MIN_SECRET_LENGTH)  # long but no entropy


def test_detect_secret_by_prefix() -> None:
    matches = detect_secrets(f"token={HIGH_ENTROPY} end")
    assert matches
    assert matches[0].label == "openai_key"


def test_detect_github_and_aws_prefixes() -> None:
    assert detect_secrets("ghp_" + "A1b2C3d4E5f6G7h8I9j0")[0].label == "github_pat"
    assert detect_secrets("AKIAIOSFODNN7EXAMPLE")[0].label == "aws_access_key"


def test_plain_document_id_is_not_flagged() -> None:
    # A long but low-entropy id must not be treated as a secret (dual check).
    assert detect_secrets("document-id-aaaaaaaaaaaaaaaaaaaa") == []


def test_whitelist_suppresses_matches() -> None:
    assert detect_secrets(HIGH_ENTROPY, whitelist=[HIGH_ENTROPY]) == []


def test_manual_mark_suppresses_matches() -> None:
    assert detect_secrets(HIGH_ENTROPY, marked=[HIGH_ENTROPY]) == []


def test_entropy_threshold_constant_matches_clarify() -> None:
    assert ENTROPY_THRESHOLD_BITS_PER_CHAR == 3.5
    assert MIN_SECRET_LENGTH == 16


# --- placeholders ------------------------------------------------------------

def test_reference_replaces_secret_with_placeholder() -> None:
    store = PlaceholderStore()
    text = f"my key is {HIGH_ENTROPY} ok"
    redacted, ids = reference(text, store)
    assert HIGH_ENTROPY not in redacted
    assert ids and placeholder_ids(redacted)


def test_reference_is_reversible_by_owner() -> None:
    store = PlaceholderStore()
    text = f"key {HIGH_ENTROPY} end"
    redacted, _ = reference(text, store)
    restored = dereference(redacted, store, role="owner")
    assert HIGH_ENTROPY in restored


def test_dereference_denied_for_unauthorized_role() -> None:
    store = PlaceholderStore()
    redacted, _ = reference(f"key {HIGH_ENTROPY}", store)
    with pytest.raises(DereferenceDenied):
        dereference(redacted, store, role="member")


def test_dereference_is_audited() -> None:
    store = PlaceholderStore()
    redacted, _ = reference(f"key {HIGH_ENTROPY}", store)
    audit: list[dict] = []
    dereference(redacted, store, role="full_access_admin", audit=audit, actor="u1")
    assert audit and audit[0]["action"] == "dereference"


def test_redacted_text_is_clean_of_plaintext() -> None:
    store = PlaceholderStore()
    redacted, _ = reference(f"key {HIGH_ENTROPY} end", store)
    assert redacted_text_is_clean(redacted, [HIGH_ENTROPY])


# --- timeline ----------------------------------------------------------------

def test_timeline_next_seq_is_monotonic() -> None:
    timeline = Timeline([1, 2, 3])
    assert timeline.next_seq() == 4
    assert timeline.max_seq == 3


def test_resume_continues_after_snapshot_never_resets() -> None:
    timeline = Timeline([1, 2, 3, 4, 5])
    assert timeline.resume_from(3) == 4  # continues, never back to 1


def test_resume_rejects_snapshot_ahead_of_history() -> None:
    timeline = Timeline([1, 2])
    with pytest.raises(LinearTimelineError):
        timeline.resume_from(9)


def test_append_rejects_fork() -> None:
    timeline = Timeline([1, 2, 3])
    with pytest.raises(LinearTimelineError):
        timeline.append(3)  # duplicate
    with pytest.raises(LinearTimelineError):
        timeline.append(2)  # out of order


def test_append_accepts_strictly_increasing() -> None:
    timeline = Timeline([1, 2])
    timeline.append(3)
    assert timeline.max_seq == 3


def test_optimistic_lock_match_succeeds() -> None:
    result = check_and_advance(current_seq=5, expected_seq=5)
    assert result.ok and not result.conflict


def test_optimistic_lock_conflict_detected() -> None:
    result = check_and_advance(current_seq=7, expected_seq=5)
    assert result.conflict and result.actual_seq == 7


def test_optimistic_lock_fails_closed_after_retries() -> None:
    with pytest.raises(LinearTimelineError):
        check_and_advance(current_seq=7, expected_seq=5, max_retries=3, attempts=3)


def test_merge_linear_dedupes_and_sorts() -> None:
    assert merge_linear([1, 3, 5], [2, 3, 4]) == [1, 2, 3, 4, 5]
