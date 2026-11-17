from types import SimpleNamespace

import pytest

from radicalbit_ai_gateway.llm.usage import (
    CacheTokens,
    MessagesUsage,
    cache_tokens,
    messages_token_counts,
    messages_usage,
)

LEGACY = {'token_usage': {'prompt_tokens_details': {'cached_tokens': 50}}}


@pytest.mark.parametrize(
    ('details', 'response_metadata', 'expected'),
    [
        pytest.param(None, None, CacheTokens(None, None, None), id='no_usage'),
        pytest.param(
            {'cache_read': 100}, None, CacheTokens(100, None, None), id='read_only'
        ),
        pytest.param(
            {'cache_read': 100, 'cache_creation': 40},
            None,
            CacheTokens(100, 40, None),
            id='write_without_ttl_counts_as_5m',
        ),
        pytest.param(
            {
                'cache_read': 100,
                'cache_creation': 70,
                'ephemeral_5m_input_tokens': 30,
                'ephemeral_1h_input_tokens': 40,
            },
            None,
            CacheTokens(100, 30, 40),
            id='ttl_breakdown_wins_over_the_total',
        ),
        pytest.param(
            {'ephemeral_1h_input_tokens': 40},
            None,
            CacheTokens(None, None, 40),
            id='1h_only',
        ),
        pytest.param(None, LEGACY, CacheTokens(50, None, None), id='legacy_openai'),
        pytest.param(
            {'cache_read': 100}, LEGACY, CacheTokens(100, None, None), id='new_wins'
        ),
    ],
)
def test_cache_tokens(details, response_metadata, expected):
    usage = None if details is None else {'input_token_details': details}

    assert cache_tokens(usage, response_metadata) == expected


@pytest.mark.parametrize(
    ('usage', 'expected'),
    [
        pytest.param(None, (0, 0), id='no_usage'),
        pytest.param({'input_tokens': 21, 'output_tokens': 7}, (21, 7), id='uncached'),
        pytest.param(
            {
                'input_tokens': 21,
                'output_tokens': 7,
                'cache_read_input_tokens': 4,
                'cache_creation_input_tokens': 9,
                'cache_creation': {
                    'ephemeral_5m_input_tokens': 5,
                    'ephemeral_1h_input_tokens': 4,
                },
            },
            (34, 7),
            id='ttl_breakdown_counted_once',
        ),
        pytest.param(
            {'input_tokens': 21, 'cache_creation_input_tokens': 9},
            (30, 0),
            id='write_without_ttl',
        ),
    ],
)
def test_messages_token_counts_include_the_cache(usage, expected):
    assert messages_token_counts(usage) == expected


# 21 new input tokens, 4 read from the cache, 9 written: 5 for 5 minutes and
# 4 for 1 hour.
WITH_TTL_BREAKDOWN = {
    'input_tokens': 21,
    'output_tokens': 7,
    'cache_read_input_tokens': 4,
    'cache_creation_input_tokens': 9,
    'cache_creation': {
        'ephemeral_5m_input_tokens': 5,
        'ephemeral_1h_input_tokens': 4,
    },
}


@pytest.mark.parametrize(
    ('usage', 'expected'),
    [
        pytest.param(None, MessagesUsage(0, 0, 0, 0, 0), id='no_usage'),
        pytest.param(
            {'input_tokens': 21, 'output_tokens': 7},
            MessagesUsage(21, 7, 0, 0, 0),
            id='uncached',
        ),
        pytest.param(
            WITH_TTL_BREAKDOWN,
            MessagesUsage(34, 7, 4, 5, 4),
            id='ttl_breakdown_counted_once',
        ),
        pytest.param(
            {
                'input_tokens': 21,
                'output_tokens': 7,
                'cache_read_input_tokens': 4,
                'cache_creation_input_tokens': 9,
            },
            MessagesUsage(34, 7, 4, 9, 0),
            id='write_without_ttl_counts_as_5m',
        ),
        pytest.param(
            {
                'input_tokens': 21,
                'cache_creation_input_tokens': 9,
                'cache_creation': {
                    'ephemeral_5m_input_tokens': 0,
                    'ephemeral_1h_input_tokens': 0,
                },
            },
            MessagesUsage(30, 0, 0, 9, 0),
            id='empty_breakdown_falls_back_to_the_total',
        ),
        pytest.param(
            {'input_tokens': None, 'output_tokens': None, 'cache_creation': None},
            MessagesUsage(0, 0, 0, 0, 0),
            id='nulls',
        ),
    ],
)
def test_messages_usage_keeps_cache_reads_and_writes_apart(usage, expected):
    assert messages_usage(usage) == expected


def test_messages_usage_reads_an_sdk_usage_object_as_it_reads_a_dict():
    as_object = SimpleNamespace(
        **{
            **WITH_TTL_BREAKDOWN,
            'cache_creation': SimpleNamespace(**WITH_TTL_BREAKDOWN['cache_creation']),
        }
    )

    assert messages_usage(as_object) == MessagesUsage(34, 7, 4, 5, 4)


def test_messages_usage_tells_the_input_that_was_not_cached():
    assert messages_usage(WITH_TTL_BREAKDOWN).uncached_input == 21
