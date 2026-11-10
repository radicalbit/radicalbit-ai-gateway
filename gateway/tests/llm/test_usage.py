import pytest

from radicalbit_ai_gateway.llm.usage import CacheTokens, cache_tokens

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
