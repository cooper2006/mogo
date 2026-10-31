"""Linear-time literal keyword matching without an external model call."""

from __future__ import annotations

from collections import deque
import unicodedata
from typing import Any


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def matching_rule(text: str, rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    edges: list[dict[str, int]] = [{}]
    failure = [0]
    output: list[int | None] = [None]

    for rule_index, rule in enumerate(rules):
        for entry in rule.get("terms") or []:
            for raw in [entry.get("keyword"), *(entry.get("synonyms") or [])]:
                token = normalize(str(raw or "").strip())
                if not token:
                    continue
                state = 0
                for char in token:
                    next_state = edges[state].get(char)
                    if next_state is None:
                        next_state = len(edges)
                        edges[state][char] = next_state
                        edges.append({})
                        failure.append(0)
                        output.append(None)
                    state = next_state
                if output[state] is None:
                    output[state] = rule_index

    pending = deque(edges[0].values())
    while pending:
        state = pending.popleft()
        for char, next_state in edges[state].items():
            pending.append(next_state)
            fallback = failure[state]
            while fallback and char not in edges[fallback]:
                fallback = failure[fallback]
            failure[next_state] = edges[fallback].get(char, 0)
            if output[next_state] is None:
                output[next_state] = output[failure[next_state]]

    state = 0
    for char in normalize(text):
        while state and char not in edges[state]:
            state = failure[state]
        state = edges[state].get(char, 0)
        if output[state] is not None:
            return rules[output[state]]
    return None
