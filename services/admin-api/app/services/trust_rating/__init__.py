"""036 trust-rating domain module (L1-L4).

``ratings`` holds the pure policy + persistence; ``downgrade_scanner`` drives the
periodic re-evaluation. The module deliberately lives outside ``governance`` so it
can consume 016/032 without creating a governance -> service dependency.
"""

from __future__ import annotations

from .ratings import *  # noqa: F401,F403
from .ratings import __all__ as _ratings_all
from .downgrade_scanner import TrustRatingDowngradeScanner, run_downgrade_scan

__all__ = list(_ratings_all) + ["TrustRatingDowngradeScanner", "run_downgrade_scan"]