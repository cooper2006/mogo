"""Session versioning (feature 002).

Commit / log / resume / share / co-presence over session state, plus low-entropy
secret detection with reversible placeholders.

This package holds the dependency-light, unit-testable core:

* ``secrets``   — low-entropy secret detection (entropy + prefix dual check);
* ``placeholder`` — reversible placeholder substitution and dereference;
* ``timeline``  — linear-timeline invariants (seq monotonic, resume never forks).

The Mongo-backed store (``session_snapshots``) and the HTTP endpoints live in the
wider session pipeline; these modules stay free of DB-driver imports so they can
be tested anywhere.
"""

from __future__ import annotations

from .placeholder import dereference, reference
from .secrets import SecretMatch, detect_secrets
from .timeline import LinearTimelineError, Timeline

__all__ = [
    "SecretMatch",
    "detect_secrets",
    "reference",
    "dereference",
    "Timeline",
    "LinearTimelineError",
]
