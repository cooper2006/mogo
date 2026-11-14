"""QF-395~396: NoSQL injection guard — prevent operator-based query injection.

Strips MongoDB query operators (``$ne``, ``$gt``, ``$where``, etc.) from
user-supplied filter dictionaries before they reach the database driver.
"""

from __future__ import annotations

# MongoDB query operators that must never appear in user-controlled filters.
_BLOCKED_OPERATORS = frozenset({
    "$where", "$ne", "$gt", "$gte", "$lt", "$lte", "$in", "$nin",
    "$exists", "$regex", "$options", "$size", "$all", "$elemMatch",
    "$mod", "$bitsAllClear", "$bitsAnyClear", "$bitsAllSet", "$bitsAnySet",
    "$type", "$and", "$or", "$nor", "$not", "$pull", "$push", "$addToSet",
    "$pop", "$unset", "$rename", "$inc", "$min", "$max", "$mul", "$div",
    "$currentDate", "$set", "$bit", "$project", "$unwind", "$lookup",
    "$unionWith", "$setWindowFields", "$facet", "$addFields", "$replaceRoot",
    "$replaceWith", "$out", "$merge", "$count", "$skip", "$limit", "$sort",
    "$sample", "$unwind", "$geoNear", "$collStats", "$indexStats",
})


def _strip_operators(value: object) -> object:
    """Recursively remove keys that start with ``$`` from dicts."""
    if isinstance(value, dict):
        return {
            k: _strip_operators(v)
            for k, v in value.items()
            if not (isinstance(k, str) and k.startswith("$"))
        }
    if isinstance(value, list):
        return [_strip_operators(item) for item in value]
    return value


def sanitize_query_filter(filter_dict: dict[str, object]) -> dict[str, object]:
    """Return a copy of *filter_dict* with all ``$``-prefixed keys removed.

    This is a belt-and-suspenders defence: even though Pydantic models enforce
    string types, a malicious payload that somehow reaches the repository layer
    will have its operators stripped before the query is executed.
    """
    if not isinstance(filter_dict, dict):
        return filter_dict
    return _strip_operators(filter_dict)


def is_safe_query_value(value: object) -> bool:
    """Return True if *value* is a primitive type safe for direct query use."""
    return isinstance(value, (str, int, float, bool, type(None)))
