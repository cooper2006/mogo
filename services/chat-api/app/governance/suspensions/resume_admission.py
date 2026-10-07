"""未接线 / NOT WIRED — explicit degradation notice.

Status (QA R5, 2026-10-07): this module is **not an enforced security control**
and must not be cited as evidence that task-resume admission is enforced.

* Zero producers: nothing in the repository calls :func:`trusted_resume_admission`.
* Zero consumers: nothing calls :func:`is_trusted_task_continuation`.
* ``_runtime_resume_only`` has no writer anywhere in the repository.
* Its tests are self-referential (they only assert the ContextVar and the dict
  the test itself builds), so a green suite here says nothing about runtime
  admission.

Why it is degraded instead of wired: the shape of the design is circular.
``output_spec`` is client-controllable (``ChatRequest.output_spec``) and is
constructed by the resume endpoint itself, so a flag written into that dict and
read back inside the same call stack adds no trust boundary. The mechanism
actually in force passes a **server-side parameter** instead —
``trusted_turn_context`` (producer: ``app/api/endpoints/tasks.py::resume_task``;
consumer: ``app/dsh_runtime/chat_service.py::prepare_turn``) — and it is never
copied from ``ChatRequest``.

If a privileged "only during resume" capability is ever needed, implement it as
a sibling server-side parameter, not as a boolean inside a client-controllable
dict. Until then, do not import this module as a guard. See
``docs/pending-review/2026-10-07-full-qa-audit-r5.md`` §九 N4.

Original design intent, kept verbatim for reference:

    The public chat payload is not a trust boundary: clients can submit
    arbitrary ``output_spec`` fields. Only the task-resume endpoint may open
    this context, after it has claimed a real suspension owned by the
    authenticated user.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator


_trusted_resume_admission: ContextVar[bool] = ContextVar(
    "trusted_resume_admission",
    default=False,
)


@contextmanager
def trusted_resume_admission() -> Iterator[None]:
    token = _trusted_resume_admission.set(True)
    try:
        yield
    finally:
        _trusted_resume_admission.reset(token)


def is_trusted_task_continuation(output_spec: Dict[str, Any] | None) -> bool:
    return bool(
        _trusted_resume_admission.get()
        and isinstance(output_spec, dict)
        and output_spec.get("_runtime_resume_only") is True
    )
