"""Feature-name normalisation for product comparison."""

from __future__ import annotations

import re
from typing import Iterable, Mapping


def normalize_feature(name: str) -> str:
    """Lower-case and collapse a feature label into a comparable key."""
    value = str(name or "").strip().lower()
    value = re.sub(r"[\s_\-]+", "", value)
    return value


def build_feature_index(features: Iterable[Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
    """Index features by normalised name (last wins on collision)."""
    index: dict[str, Mapping[str, object]] = {}
    for feature in features:
        key = normalize_feature(str(feature.get("name") or ""))
        if key:
            index[key] = feature
    return index


def diff_features(
    ours: Iterable[Mapping[str, object]],
    theirs: Iterable[Mapping[str, object]],
) -> dict[str, list[str]]:
    """Compare two feature sets, returning shared / ours-only / theirs-only keys."""
    a = build_feature_index(ours)
    b = build_feature_index(theirs)
    return {
        "shared": sorted(set(a) & set(b)),
        "ours_only": sorted(set(a) - set(b)),
        "theirs_only": sorted(set(b) - set(a)),
    }
