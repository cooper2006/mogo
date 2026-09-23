"""Dream Cycle self-evolution (feature 011).

Turns friction signals into reusable Skills:

* ``friction``    — detect friction events (failed-then-succeeded, human
  correction, explicit user mark) and capture structured experience fragments;
* ``similarity``  — Jaccard (scene features) + edit distance (action sequences);
* scanning / draft generation / MR creation / deprecation build on these.

This package holds the dependency-light core (friction / similarity / fragment
model), so it is unit-testable without the DSH runtime or a database.
"""

from __future__ import annotations

from .fragment import ExperienceFragment, FragmentStore
from .friction import FrictionKind, FrictionSignal, detect_friction
from .similarity import (
    DEFAULT_JACCARD_THRESHOLD,
    DEFAULT_MIN_SAMPLES,
    edit_distance,
    is_high_confidence,
    jaccard,
    similarity,
)

__all__ = [
    "ExperienceFragment",
    "FragmentStore",
    "FrictionKind",
    "FrictionSignal",
    "detect_friction",
    "jaccard",
    "edit_distance",
    "similarity",
    "is_high_confidence",
    "DEFAULT_JACCARD_THRESHOLD",
    "DEFAULT_MIN_SAMPLES",
]
