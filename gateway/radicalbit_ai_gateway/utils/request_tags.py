"""Parsing and validation of the ``X-RB-Tags`` request header.

Comma-separated ``key=value`` pairs, e.g.::

    X-RB-Tags: cost_center=retail,env=prod,app=my-app

The header is gateway-owned: consumed by the request event middleware and
never forwarded upstream. Tags are deduplicated and sorted, so header order
never affects the stored rows.
"""

import re
from typing import Annotated

from fastapi import Query

from radicalbit_ai_gateway.utils.exceptions import GatewayBadRequest, TagsHeaderError

TAGS_HEADER = 'x-rb-tags'

MAX_TAGS_HEADER_BYTES = 4096
MAX_TAG_KEY_LENGTH = 64
MAX_TAG_VALUE_LENGTH = 256

_KEY_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:\-]*$')
_VALUE_PATTERN = re.compile(r'^[A-Za-z0-9_.:@/+\-#]+$')


def _invalid_key_reason(key: str) -> str | None:
    """Return why `key` is invalid, or None if it's fine.

    Shared by :func:`parse_tags_header` and :func:`parse_tag_query_value` so the
    two entry points can never drift on what counts as a valid tag key.
    """
    if len(key) > MAX_TAG_KEY_LENGTH or not _KEY_PATTERN.match(key):
        return (
            f'key {key[:MAX_TAG_KEY_LENGTH]!r} must start with a letter or digit '
            f'and contain only letters, digits and _ . : - '
            f'(max {MAX_TAG_KEY_LENGTH} characters)'
        )
    return None


def _invalid_value_reason(value: str) -> str | None:
    """Return why `value` is invalid, or None if it's fine. See `_invalid_key_reason`."""
    if len(value) > MAX_TAG_VALUE_LENGTH or not _VALUE_PATTERN.match(value):
        return (
            f'value {value[:MAX_TAG_VALUE_LENGTH]!r} must contain only letters, '
            f'digits and _ . : @ / + # - '
            f'(max {MAX_TAG_VALUE_LENGTH} characters)'
        )
    return None


def _reject(position: int, reason: str) -> TagsHeaderError:
    return TagsHeaderError(
        f'X-RB-Tags tag {position} is invalid: {reason}. '
        'Expected comma-separated key=value pairs',
        'tags_header_invalid',
    )


def parse_tags_header(raw: str | None) -> tuple[str, ...]:
    """Parse ``X-RB-Tags`` into a sorted, deduplicated ``key=value`` tuple.

    Raises :class:`TagsHeaderError` for the first offending segment.
    """
    if raw is None or not raw.strip():
        return ()

    size = len(raw.encode('utf-8'))
    if size > MAX_TAGS_HEADER_BYTES:
        raise TagsHeaderError(
            f'X-RB-Tags header is {size} bytes, which exceeds the '
            f'{MAX_TAGS_HEADER_BYTES} byte limit',
            'tags_header_too_large',
        )

    tags: set[str] = set()
    for position, segment in enumerate(raw.split(','), start=1):
        key, sep, value = (part.strip() for part in segment.partition('='))
        if not sep or not key or not value:
            raise _reject(position, f'{segment.strip()!r} must be a key=value pair')

        if reason := _invalid_key_reason(key):
            raise _reject(position, reason)

        if reason := _invalid_value_reason(value):
            raise _reject(position, reason)

        tags.add(f'{key}={value}')

    return tuple(sorted(tags))


def parse_tag_query_value(raw: str) -> str:
    """Validate a single ``key=value`` query-param tag, returning it unchanged.

    Used to filter usage/cost data by tag (as opposed to :func:`parse_tags_header`,
    which parses the comma-separated ``X-RB-Tags`` header attached to a request).
    """
    key, sep, value = raw.partition('=')

    if not sep or not key or not value:
        raise GatewayBadRequest(f'Invalid tag {raw!r}: expected a key=value pair')

    if reason := _invalid_key_reason(key):
        raise GatewayBadRequest(f'Invalid tag {raw!r}: {reason}')

    if reason := _invalid_value_reason(value):
        raise GatewayBadRequest(f'Invalid tag {raw!r}: {reason}')

    return raw


def parse_tags_query(
    tags: Annotated[
        list[str] | None,
        Query(
            description=(
                'Filter by one or more key=value tags (repeatable). Values for '
                'the same key are OR-ed together; different keys are AND-ed, '
                'e.g. tags=env=prod&tags=env=staging&tags=cost_center=retail '
                'matches (env=prod OR env=staging) AND cost_center=retail.'
            )
        ),
    ] = None,
) -> list[str] | None:
    """FastAPI dependency validating the repeated ``tags`` query param."""
    return [parse_tag_query_value(tag) for tag in tags] if tags else None
