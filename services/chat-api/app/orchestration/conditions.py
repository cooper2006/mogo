"""Restricted JSON condition evaluation (010 FR-4 / clarify OQ-1 / OQ-5).

Conditions are **declarative JSON objects**, never code. Supported forms:

* comparison: ``{"op": "==", "left": <expr>, "right": <expr>}`` where the operators
  are ``== != > >= < <= in has``;
* logical: ``{"op": "and"|"or", "operands": [...]}`` and ``{"op": "not", "operand": ...}``;
* a bare literal (truthiness).

Operands may be literals or ``{"var": "path.to.value"}`` references into the
evaluation context. Unknown operators, malformed shapes, or unresolvable variables
raise ``ConditionError``; callers treat that as **fail-closed** (skip + audit, or
abort — configurable, FR-4).
"""

from __future__ import annotations

from typing import Any, Mapping

COMPARISON_OPERATORS = frozenset({"==", "!=", ">", ">=", "<", "<=", "in", "has"})
LOGICAL_OPERATORS = frozenset({"and", "or", "not"})
ALL_OPERATORS = COMPARISON_OPERATORS | LOGICAL_OPERATORS


class ConditionError(ValueError):
    """Raised for an invalid condition object or an unresolvable variable."""


def _resolve(expr: Any, context: Mapping[str, Any]) -> Any:
    """Resolve an operand: a ``{"var": path}`` reference or a literal."""
    if isinstance(expr, dict):
        if "var" in expr and len(expr) == 1:
            path = str(expr["var"])
            if not path:
                raise ConditionError("var path must not be empty")
            current: Any = context
            for part in path.split("."):
                if isinstance(current, Mapping) and part in current:
                    current = current[part]
                else:
                    raise ConditionError(f"unresolved variable: {path}")
            return current
        if "op" in expr:
            return evaluate_condition(expr, context)
        # A plain object without ``var``/``op`` is a literal value (e.g. {"k": 1}).
        return expr
    return expr


def _compare(op: str, left: Any, right: Any) -> bool:
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op == "in":
        try:
            return left in right
        except TypeError as error:
            raise ConditionError(f"'in' requires a container: {error}") from error
    if op == "has":
        if not isinstance(left, Mapping):
            raise ConditionError("'has' requires an object on the left")
        return right in left
    # Ordered comparisons require comparable operands.
    try:
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
    except TypeError as error:
        raise ConditionError(f"cannot compare {left!r} {op} {right!r}: {error}") from error
    raise ConditionError(f"unsupported operator: {op}")


def evaluate_condition(condition: Any, context: Mapping[str, Any] | None = None) -> bool:
    """Evaluate a restricted JSON condition against ``context``.

    Raises ``ConditionError`` for malformed conditions (callers fail closed).
    """
    ctx = context or {}

    if condition is None:
        return True                     # no condition -> always run
    if isinstance(condition, bool):
        return condition
    if not isinstance(condition, dict):
        return bool(condition)          # literals use plain truthiness

    op = condition.get("op")
    if op is None:
        # A bare object is truthy if non-empty (mirrors Python semantics).
        return bool(condition)
    if not isinstance(op, str):
        raise ConditionError("'op' must be a string")
    if op not in ALL_OPERATORS:
        raise ConditionError(f"unsupported operator: {op}")

    if op in ("and", "or"):
        operands = condition.get("operands")
        if not isinstance(operands, list):
            raise ConditionError(f"'{op}' requires an 'operands' list")
        results = [evaluate_condition(item, ctx) for item in operands]
        return all(results) if op == "and" else any(results)

    if op == "not":
        if "operand" not in condition:
            raise ConditionError("'not' requires an 'operand'")
        return not evaluate_condition(condition["operand"], ctx)

    # Comparison operators.
    if "left" not in condition or "right" not in condition:
        raise ConditionError(f"'{op}' requires both 'left' and 'right'")
    left = _resolve(condition["left"], ctx)
    right = _resolve(condition["right"], ctx)
    return _compare(op, left, right)
