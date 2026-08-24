"""Parsing and validation of the ``X-RB-Tags`` request header.

Clients label a request with their own business dimensions (cost centre,
environment, application) as comma-separated ``key=value`` pairs::

    X-RB-Tags: cost_center=retail,env=prod,app=leonardo-clm

The header is gateway-owned: it is consumed by
:class:`~radicalbit_ai_gateway.middleware.request_event_middleware.RequestEventMiddleware`
and never forwarded upstream.

Parsing is order-independent: pairs are deduplicated and sorted, so the same
set of tags in any header order produces byte-identical ClickHouse rows.
"""

import re

from radicalbit_ai_gateway.utils.exceptions import (
    TagsHeaderMalformed,
    TagsHeaderTooLarge,
    TagsKeyInvalid,
    TagsValueInvalid,
)

TAGS_HEADER = 'x-rb-tags'

# Whatever arrives here is copied into every ClickHouse row the request
# produces (one request_event row plus one event row per metric), so the
# header size bounds per-row storage. It also implicitly bounds the tag count.
MAX_TAGS_HEADER_BYTES = 4096
MAX_TAG_KEY_LENGTH = 64
MAX_TAG_VALUE_LENGTH = 256

_PAIR_SEPARATOR = ','
_KEY_VALUE_SEPARATOR = '='

_KEY_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:\-]*$')
# Printable ASCII; ',' never survives the split and '=' is rejected in the
# value check below, so 'key=value' round-trips.
_VALUE_PATTERN = re.compile(r'^[\x20-\x7e]+$')

# Offending input is echoed back to the caller to make failures diagnosable;
# truncated so an oversized segment cannot bloat the error body.
_SEGMENT_PREVIEW_LENGTH = 64


def _preview(segment: str) -> str:
    if len(segment) <= _SEGMENT_PREVIEW_LENGTH:
        return segment
    return segment[:_SEGMENT_PREVIEW_LENGTH] + '...'


def parse_tags_header(raw: str | None) -> tuple[str, ...]:
    """Parse ``X-RB-Tags`` into canonical ``key=value`` entries.

    Returns a sorted, deduplicated tuple. A missing or blank header yields an
    empty tuple. The same key may appear more than once with different values;
    an identical key and value appearing twice is collapsed into one entry.

    Raises a :class:`~radicalbit_ai_gateway.utils.exceptions.TagsHeaderError`
    subclass for the first offending segment, left to right.
    """
    if raw is None or not raw.strip():
        return ()

    size = len(raw.encode('utf-8'))
    if size > MAX_TAGS_HEADER_BYTES:
        raise TagsHeaderTooLarge(size, MAX_TAGS_HEADER_BYTES)

    tags: set[str] = set()
    segments = raw.split(_PAIR_SEPARATOR)
    for position, segment in enumerate(segments, start=1):
        pair = segment.strip()
        if not pair:
            raise TagsHeaderMalformed(_preview(segment), position, 'empty tag')
        if _KEY_VALUE_SEPARATOR not in pair:
            raise TagsHeaderMalformed(_preview(pair), position, "missing '='")

        raw_key, _, raw_value = pair.partition(_KEY_VALUE_SEPARATOR)
        key = raw_key.strip()
        value = raw_value.strip()

        if not key:
            raise TagsHeaderMalformed(_preview(pair), position, 'empty key')
        if not value:
            raise TagsHeaderMalformed(_preview(pair), position, 'empty value')

        if len(key) > MAX_TAG_KEY_LENGTH:
            raise TagsKeyInvalid(
                _preview(key),
                position,
                f'longer than {MAX_TAG_KEY_LENGTH} characters',
            )
        if not _KEY_PATTERN.match(key):
            raise TagsKeyInvalid(
                _preview(key),
                position,
                'must start with a letter or digit and contain only '
                'letters, digits, and the characters _ . : -',
            )

        if len(value) > MAX_TAG_VALUE_LENGTH:
            raise TagsValueInvalid(
                _preview(value),
                position,
                f'longer than {MAX_TAG_VALUE_LENGTH} characters',
            )
        if _KEY_VALUE_SEPARATOR in value or not _VALUE_PATTERN.match(value):
            raise TagsValueInvalid(
                _preview(value),
                position,
                "must be printable ASCII without ',' or '='",
            )

        tags.add(f'{key}{_KEY_VALUE_SEPARATOR}{value}')

    return tuple(sorted(tags))
