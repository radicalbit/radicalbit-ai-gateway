"""Shared tag-filter condition builder for the ClickHouse `TAGS` array column.

Both `event` and `request_event` store tags as canonical ``key=value`` strings
in a flat `Array(String)` column, so `EventDAO` and `RequestEventDAO` filter on
it identically. This is the one place that logic lives.
"""

from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.sql import ColumnElement


def add_tags_filter(
    conditions: list, tags_column: ColumnElement, tags: list[str] | None
) -> None:
    """Append Google-style facet tag-filter conditions to `conditions`.

    Values for the same key are OR-ed together (`hasAny`); different keys end
    up as separate entries in `conditions`, which `.where(*conditions)` ANDs.
    """
    if not tags:
        return
    by_key: dict[str, list[str]] = defaultdict(list)
    for tag in tags:
        by_key[tag.partition('=')[0]].append(tag)
    conditions.extend(
        func.hasAny(tags_column, key_tags) for key_tags in by_key.values()
    )
