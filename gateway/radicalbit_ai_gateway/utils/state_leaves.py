"""String leaves of a decision request's `state` and `questions`, walked
depth first.

Guardrails screen each string leaf as one text. Keys, numbers, booleans and
nulls are never leaves, so they are never checked or redacted.
"""

from collections.abc import Iterator
from typing import Any


def string_leaves(value: Any) -> list[str]:
    """Return the string leaves of `value`, in order."""
    return list(_iter_leaves(value))


def with_string_leaves(value: Any, texts: list[str]) -> Any:
    """Return a copy of `value` with its string leaves replaced, in order."""
    replacements = iter(texts)
    return _replace(value, replacements)


def _iter_leaves(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_leaves(item)


def _replace(value: Any, replacements: Iterator[str]) -> Any:
    if isinstance(value, str):
        return next(replacements)
    if isinstance(value, dict):
        return {key: _replace(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace(item, replacements) for item in value]
    return value
