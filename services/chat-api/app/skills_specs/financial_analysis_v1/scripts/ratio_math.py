"""Deterministic financial-ratio helpers (no external data source)."""

from __future__ import annotations

from typing import Mapping


def safe_div(numerator: float, denominator: float) -> float | None:
    """Divide, returning ``None`` when the denominator is zero."""
    try:
        if denominator == 0:
            return None
        return float(numerator) / float(denominator)
    except (TypeError, ValueError):
        return None


def gross_margin(revenue: float, cost_of_revenue: float) -> float | None:
    return safe_div(revenue - cost_of_revenue, revenue)


def net_margin(net_income: float, revenue: float) -> float | None:
    return safe_div(net_income, revenue)


def debt_to_equity(total_debt: float, equity: float) -> float | None:
    return safe_div(total_debt, equity)


def compute_ratios(statement: Mapping[str, float]) -> dict[str, float | None]:
    """Compute the ratio set used by the financial sub-agent."""
    revenue = statement.get("revenue") or 0.0
    return {
        "gross_margin": gross_margin(revenue, statement.get("cost_of_revenue") or 0.0),
        "net_margin": net_margin(statement.get("net_income") or 0.0, revenue),
        "debt_to_equity": debt_to_equity(
            statement.get("total_debt") or 0.0, statement.get("equity") or 0.0
        ),
    }


def enterprise_value(market_cap: float, total_debt: float, cash: float) -> float:
    """EV = market cap + total debt - cash."""
    return float(market_cap) + float(total_debt) - float(cash)
