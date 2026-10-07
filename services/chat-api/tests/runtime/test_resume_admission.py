"""Self-referential tests for ``resume_admission`` — they prove nothing about runtime trust.

These cases only assert the ContextVar and the dict the *test itself* builds; no
production admission path is exercised, and the whole suite stays green even if
every caller of the module is deleted. Per QA R5 §九 N4 the module is explicitly
degraded as un-wired (see its docstring): read these tests as a description of
the helper's local behaviour, never as evidence that task-resume admission is
enforced.
"""

from app.governance.suspensions.resume_admission import (
    is_trusted_task_continuation,
    trusted_resume_admission,
)


def test_public_resume_flag_is_not_trusted_by_itself():
    assert not is_trusted_task_continuation({"_runtime_resume_only": True})


def test_claimed_resume_context_allows_only_runtime_continuation():
    with trusted_resume_admission():
        assert is_trusted_task_continuation({"_runtime_resume_only": True})
        assert not is_trusted_task_continuation({})
        assert not is_trusted_task_continuation({"_runtime_resume_only": False})

    assert not is_trusted_task_continuation({"_runtime_resume_only": True})
