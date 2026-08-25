"""Parsing and validation of the ``X-RB-Tags`` request header.

Comma-separated ``key=value`` pairs, e.g.::

    X-RB-Tags: cost_center=retail,env=prod,app=leonardo-clm

The header is gateway-owned: consumed by the request event middleware and
never forwarded upstream. Tags are deduplicated and sorted, so header order
never affects the stored rows.
"""

import re

from radicalbit_ai_gateway.utils.exceptions import TagsHeaderError

TAGS_HEADER = 'x-rb-tags'

MAX_TAGS_HEADER_BYTES = 4096
MAX_TAG_KEY_LENGTH = 64
MAX_TAG_VALUE_LENGTH = 256

_KEY_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:\-]*$')
_VALUE_PATTERN = re.compile(r'^[\x20-\x7e]+$')


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

        if len(key) > MAX_TAG_KEY_LENGTH or not _KEY_PATTERN.match(key):
            raise _reject(
                position,
                f'key {key[:MAX_TAG_KEY_LENGTH]!r} must start with a letter or digit '
                f'and contain only letters, digits and _ . : - '
                f'(max {MAX_TAG_KEY_LENGTH} characters)',
            )

        if (
            len(value) > MAX_TAG_VALUE_LENGTH
            or '=' in value
            or not _VALUE_PATTERN.match(value)
        ):
            raise _reject(
                position,
                f'value {value[:MAX_TAG_VALUE_LENGTH]!r} must be printable ASCII '
                f"without ',' or '=' (max {MAX_TAG_VALUE_LENGTH} characters)",
            )

        tags.add(f'{key}={value}')

    return tuple(sorted(tags))
