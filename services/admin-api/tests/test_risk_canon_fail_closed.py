"""059 T007 — ``risk._canon`` 未知单元 → deny（fail-closed）。

未知 (level, risk) 单元在自治矩阵中查不到，必须默认拒绝（deny），
不允许 silently allow。
"""

from __future__ import annotations

import pytest

import app.governance.risk as risk_mod
from app.governance.risk import _canon


def test_unknown_cell_denied() -> None:
    assert _canon("no_such_level", "no_such_risk") == "deny"


def test_unknown_level_all_rows_denied() -> None:
    # level=None 会遍历整个矩阵；用一个矩阵键中不可能存在的 risk 仍应 deny
    assert _canon(None, "zzz_no_such_risk_zzz") == "deny"


def test_known_cell_returns_decision() -> None:
    matrix = getattr(risk_mod, "AUTONOMY_MATRIX", None)
    if matrix is None:
        pytest.skip("AUTONOMY_MATRIX 不可用")
    level = next(iter(matrix))
    risk_key = next(iter(matrix[level]))
    assert _canon(level, risk_key) in ("allow", "deny", "ask")
