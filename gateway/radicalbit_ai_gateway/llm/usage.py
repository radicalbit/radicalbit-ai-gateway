"""Cached-token counts of a reply, read from the usage its model reports.

A reply carries its usage as ``usage_metadata`` (``input_token_details``:
``cache_read``, ``cache_creation`` and its TTL breakdown) and, for the
OpenAI-family adapters, also the provider's raw usage under
``response_metadata['token_usage']``: the legacy place of
``prompt_tokens_details.cached_tokens``.
"""

from collections.abc import Callable, Iterator, Mapping
from decimal import Decimal
from typing import Any, NamedTuple

from radicalbit_ai_gateway.llm.messages import (
    InputTokenDetails,
    OutputTokenDetails,
    UsageMetadata,
)


class CacheTokens(NamedTuple):
    """Cached input tokens: read, and written with a 5-minute or 1-hour TTL.

    Each is None when the reply does not report it.
    """

    read: int | None
    creation_5m: int | None
    creation_1h: int | None


def legacy_cached_tokens(response_metadata: Mapping[str, Any] | None) -> int | None:
    """Return the cached tokens of the raw OpenAI usage in ``response_metadata``."""
    if response_metadata is None or len(response_metadata) == 0:
        return None
    token_usage = response_metadata.get('token_usage')
    if not token_usage:
        return None
    prompt_tokens_details = token_usage.get('prompt_tokens_details')
    if not prompt_tokens_details:
        return None
    cached_tokens = prompt_tokens_details.get('cached_tokens')
    return cached_tokens if isinstance(cached_tokens, int) else None


def cache_tokens(
    usage_metadata: Mapping[str, Any] | None,
    response_metadata: Mapping[str, Any] | None,
) -> CacheTokens:
    """Return a reply's cached input tokens.

    Cache reads come from ``usage_metadata``, else from the legacy OpenAI
    usage. Cache writes prefer the TTL breakdown; without one, the total
    write counts as a 5-minute one.
    """
    read: int | None = None
    creation_5m: int | None = None
    creation_1h: int | None = None

    details = (usage_metadata or {}).get('input_token_details')
    if details:
        cache_read = details.get('cache_read')
        if cache_read and isinstance(cache_read, int):
            read = cache_read
        ephemeral_5m = details.get('ephemeral_5m_input_tokens')
        ephemeral_1h = details.get('ephemeral_1h_input_tokens')
        if ephemeral_5m or ephemeral_1h:
            if ephemeral_5m and isinstance(ephemeral_5m, int):
                creation_5m = ephemeral_5m
            if ephemeral_1h and isinstance(ephemeral_1h, int):
                creation_1h = ephemeral_1h
        else:
            cache_creation = details.get('cache_creation')
            if cache_creation and isinstance(cache_creation, int):
                creation_5m = cache_creation

    if read is None:
        read = legacy_cached_tokens(response_metadata)
    return CacheTokens(read, creation_5m, creation_1h)


class StreamUsage:
    """The token counts of a stream, updated with each chunk's usage.

    Output tokens add up. Cache counts are the last reported. The input
    count, without the cached tokens, is the last non-zero one reported.
    """

    def __init__(self) -> None:
        self.input = 0
        self.output = 0
        self.cached = 0
        self.cache_creation_5m = 0
        self.cache_creation_1h = 0

    def add(
        self,
        usage_metadata: Mapping[str, Any] | None,
        response_metadata: Mapping[str, Any] | None,
    ) -> None:
        """Count a chunk's usage."""
        if usage_metadata is None or len(usage_metadata) == 0:
            return
        input_tokens = usage_metadata.get('input_tokens') or 0
        self.output += usage_metadata.get('output_tokens') or 0
        read, creation_5m, creation_1h = cache_tokens(usage_metadata, response_metadata)
        if read is not None:
            self.cached = read
        if creation_5m is not None:
            self.cache_creation_5m = creation_5m
        if creation_1h is not None:
            self.cache_creation_1h = creation_1h
        if input_tokens:
            self.input = (
                input_tokens
                - (self.cached or 0)
                - (self.cache_creation_5m or 0)
                - (self.cache_creation_1h or 0)
            )

    def counts(self) -> tuple[Any, ...]:
        """Return input, output, cached, 5-minute and 1-hour write counts."""
        return (
            self.input,
            self.output,
            self.cached,
            self.cache_creation_5m,
            self.cache_creation_1h,
        )


def responses_token_counts(usage: dict[str, Any] | None) -> tuple[int, int, int]:
    """Return ``(input, cached input, output)`` tokens of a Responses usage."""
    if usage is None or len(usage) == 0:
        return 0, 0, 0
    cached = _token_count(usage.get('input_tokens_details'), 'cached_tokens')
    return (
        _token_count(usage, 'input_tokens'),
        cached,
        _token_count(usage, 'output_tokens'),
    )


class MessagesUsage(NamedTuple):
    """The token counts of a Messages API usage, in gateway terms.

    ``input`` includes the cache reads and writes, as a chat reply's does:
    Anthropic's ``input_tokens`` leaves them out. The cache counts are kept
    apart too, because each has its own price.
    """

    input: int
    output: int
    cache_read: int
    cache_creation_5m: int
    cache_creation_1h: int

    @property
    def uncached_input(self) -> int:
        """The input tokens that were neither read from the cache nor written."""
        return (
            self.input
            - self.cache_read
            - self.cache_creation_5m
            - self.cache_creation_1h
        )


# What prices the token counts of a Messages API call, in dollars.
MessagesCost = Callable[[MessagesUsage], Decimal]


def _token_count(source: Any, key: str) -> int:
    """Return a token count of a usage, given as a dict or as an SDK object."""
    if source is None:
        return 0
    value = source.get(key) if isinstance(source, Mapping) else getattr(source, key, 0)
    return value if isinstance(value, int) else 0


def messages_usage(usage: Any) -> MessagesUsage:
    """Return the gateway's token counts of a Messages API ``usage``.

    The one place that knows the rule, for the native Messages path (a dict)
    and for the chat path translated to Anthropic (the SDK's object). A cache
    write counts once: by its TTL breakdown when there is one, else the total
    counts as a 5-minute write.
    """
    if isinstance(usage, Mapping):
        breakdown = usage.get('cache_creation')
    else:
        breakdown = getattr(usage, 'cache_creation', None)
    cache_read = _token_count(usage, 'cache_read_input_tokens')
    creation_5m = _token_count(breakdown, 'ephemeral_5m_input_tokens')
    creation_1h = _token_count(breakdown, 'ephemeral_1h_input_tokens')
    if not creation_5m and not creation_1h:
        creation_5m = _token_count(usage, 'cache_creation_input_tokens')
    return MessagesUsage(
        input=_token_count(usage, 'input_tokens')
        + cache_read
        + creation_5m
        + creation_1h,
        output=_token_count(usage, 'output_tokens'),
        cache_read=cache_read,
        cache_creation_5m=creation_5m,
        cache_creation_1h=creation_1h,
    )


def messages_token_counts(usage: dict[str, Any] | None) -> tuple[int, int]:
    """Return ``(input, output)`` tokens of a Messages API usage.

    The input includes the cache reads and writes (see ``messages_usage``).
    """
    counts = messages_usage(usage)
    return counts.input, counts.output


# ── Usage metadata ───────────────────────────────────────────────────────────


def input_token_details(counts: Mapping[str, int | None]) -> InputTokenDetails:
    """Return the input token details a provider reported: None is left out."""
    details: InputTokenDetails = {}
    for key, count in counts.items():
        if count is not None:
            details[key] = count
    return details


def output_token_details(counts: Mapping[str, int | None]) -> OutputTokenDetails:
    """Return the output token details a provider reported: None is left out."""
    details: OutputTokenDetails = {}
    for key, count in counts.items():
        if count is not None:
            details[key] = count
    return details


_ZERO_USAGE = UsageMetadata(input_tokens=0, output_tokens=0, total_tokens=0)


def _combined(
    left: Mapping[str, int], right: Mapping[str, int], op: Callable[[int, int], int]
) -> Iterator[tuple[str, int]]:
    """Each count of either side, ``left``'s keys first: a missing one is 0."""
    for key in [*left, *(k for k in right if k not in left)]:
        yield key, op(left.get(key, 0), right.get(key, 0))


def _combine_usage(
    left: UsageMetadata, right: UsageMetadata, op: Callable[[int, int], int]
) -> UsageMetadata:
    combined = UsageMetadata(
        input_tokens=op(left['input_tokens'], right['input_tokens']),
        output_tokens=op(left['output_tokens'], right['output_tokens']),
        total_tokens=op(left['total_tokens'], right['total_tokens']),
    )
    if 'input_token_details' in left or 'input_token_details' in right:
        combined['input_token_details'] = input_token_details(
            dict(
                _combined(
                    left.get('input_token_details', {}),
                    right.get('input_token_details', {}),
                    op,
                )
            )
        )
    if 'output_token_details' in left or 'output_token_details' in right:
        combined['output_token_details'] = output_token_details(
            dict(
                _combined(
                    left.get('output_token_details', {}),
                    right.get('output_token_details', {}),
                    op,
                )
            )
        )
    return combined


def add_usage(left: UsageMetadata | None, right: UsageMetadata | None) -> UsageMetadata:
    """Return the sum of two usages; with one missing, the other; with neither, zero."""
    if not left:
        return right or UsageMetadata(**_ZERO_USAGE)
    if not right:
        return left
    return _combine_usage(left, right, lambda a, b: a + b)


def subtract_usage(
    left: UsageMetadata | None, right: UsageMetadata | None
) -> UsageMetadata:
    """Return ``left`` less ``right``, each count floored at 0.

    With one missing, the other; with neither, zero.
    """
    if not left:
        return right or UsageMetadata(**_ZERO_USAGE)
    if not right:
        return left
    return _combine_usage(left, right, lambda a, b: max(a - b, 0))
