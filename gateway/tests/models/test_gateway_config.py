import pytest

from radicalbit_ai_gateway.limiting.limits import RouteLimits
from radicalbit_ai_gateway.limiting.windows import Category
from radicalbit_ai_gateway.models.caching import CacheConfig
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig


def test_route_name_injection_from_dict():
    raw_data = {
        'chat_models': [
            {'model_id': 'prod_model', 'model': 'openai/gpt-4o'},
            {'model_id': 'staging_model', 'model': 'openai/gpt-4o-mini'},
        ],
        'embedding_models': [],
        'routes': {
            'production_route': {'chat_models': ['prod_model']},
            'staging_route': {'chat_models': ['staging_model']},
        },
    }

    # Create Gateways object from raw data - the before validator should inject route names
    gateway_config = GatewayConfig.model_validate(raw_data)

    assert len(gateway_config.routes) == 2
    assert gateway_config.routes['production_route'].route_name == 'production_route'
    assert gateway_config.routes['staging_route'].route_name == 'staging_route'

    assert gateway_config.routes['production_route'].chat_models == ['prod_model']
    assert gateway_config.routes['staging_route'].chat_models == ['staging_model']


def test_cache_validation_pass():
    raw_data = {
        'chat_models': [
            {'model_id': 'prod_model', 'model': 'openai/gpt-4o'},
            {'model_id': 'staging_model', 'model': 'openai/gpt-4o-mini'},
        ],
        'embedding_models': [],
        'routes': {
            'production_route': {
                'chat_models': ['prod_model'],
                'caching': {'enabled': True, 'ttl': 60, 'type': 'exact'},
            },
            'staging_route': {'chat_models': ['staging_model']},
        },
        'cache': {'redis_host': 'localhost', 'redis_port': 6379},
    }

    gateway_config = GatewayConfig.model_validate(raw_data)

    assert gateway_config.cache == CacheConfig(redis_host='localhost', redis_port=6379)


_CHAT_C1 = [{'model_id': 'c1', 'model': 'openai/gpt-4o-mini'}]
_WHISPER_W1 = [{'model_id': 'w1', 'model': 'openai/whisper-1'}]
_DURATION = {'max_duration_seconds': 300, 'window_size': '1 minute'}
_INPUT_TOKENS = {'input': {'max_tokens': 1000, 'window_size': '1 minute'}}
_DUMMY_GPT4O = {'model': 'openai/gpt-4o', 'credentials': {'api_key': 'sk-dummy'}}
_TRANSCRIBE_MODELS = [
    {'model_id': 'gpt4o', 'model': 'openai/gpt-4o-transcribe'},
    {'model_id': 'gpt4o-mini', 'model': 'openai/gpt-4o-mini-transcribe'},
]


@pytest.mark.parametrize(
    ('raw', 'match'),
    [
        pytest.param(
            {
                'chat_models': [
                    {'model_id': 'prod_model', 'model': 'openai/gpt-4o'},
                    {'model_id': 'staging_model', 'model': 'openai/gpt-4o-mini'},
                ],
                'embedding_models': [],
                'routes': {
                    'production_route': {
                        'chat_models': ['prod_model'],
                        'caching': {'enabled': True, 'ttl': 60, 'type': 'exact'},
                    },
                    'staging_route': {'chat_models': ['staging_model']},
                },
            },
            'Configure cache of the gateway if caching for a route is enabled',
            id='route-caching-without-gateway-cache',
        ),
        pytest.param(
            {
                'chat_models': [{'model_id': 'm1', **_DUMMY_GPT4O}],
                'routing': [
                    {
                        'name': 'bad_time',
                        'type': 'deterministic',
                        'default_model_id': 'm1',
                        'rule': 'time',
                        'output_mapping': [
                            {'model_id': 'm1', 'conditions': ['not-a-cron']},
                        ],
                    }
                ],
                'routes': {'r': {'chat_models': ['m1'], 'routing': 'bad_time'}},
            },
            'invalid cron expression',
            id='invalid-cron',
        ),
        pytest.param(
            {
                'chat_models': [
                    {'model_id': 'm1', **_DUMMY_GPT4O},
                    {'model_id': 'm2', **_DUMMY_GPT4O},
                ],
                'routing': [
                    {
                        'name': 'bad_ref',
                        'type': 'deterministic',
                        'default_model_id': 'm1',
                        'rule': 'time',
                        'output_mapping': [
                            {'model_id': 'm2', 'conditions': ['0 9-17 * * 1-5']},
                        ],
                    }
                ],
                'routes': {'r': {'chat_models': ['m1'], 'routing': 'bad_ref'}},
            },
            'not in route chat_models',
            id='time-routing-model-not-in-route',
        ),
        pytest.param(
            {'chat_models': _CHAT_C1, 'routes': {'r': {}}},
            'must reference at least one of chat_models, embedding_models, '
            'transcription_models, or decision_models',
            id='route-without-any-model-category',
        ),
        pytest.param(
            {
                'chat_models': _CHAT_C1,
                'transcription_models': _WHISPER_W1,
                'routes': {
                    'r': {'chat_models': ['c1'], 'transcription_models': ['unknown']}
                },
            },
            'transcription_models not declared in top-level transcription_models',
            id='transcription-missing-route-reference',
        ),
        pytest.param(
            {
                'chat_models': [{'model_id': 'dup', 'model': 'openai/gpt-4o-mini'}],
                'transcription_models': [
                    {'model_id': 'dup', 'model': 'openai/whisper-1'}
                ],
            },
            'chat_models and transcription_models must have globally unique model_id',
            id='transcription-duplicate-ids-across-categories',
        ),
        pytest.param(
            {
                'chat_models': _CHAT_C1,
                'transcription_models': _WHISPER_W1 * 2,
            },
            'All transcription_models must have unique model_id',
            id='transcription-duplicate-ids-within-list',
        ),
        pytest.param(
            {
                'transcription_models': _TRANSCRIBE_MODELS,
                'routes': {
                    'r': {
                        'transcription_models': ['gpt4o'],
                        'fallback': [
                            {
                                'type': 'TRANSCRIPTION',
                                'target': 'gpt4o-mini',
                                'fallbacks': ['gpt4o'],
                            }
                        ],
                    },
                },
            },
            'must be present in the transcription models',
            id='transcription-fallback-target-outside-route',
        ),
        pytest.param(
            {
                'chat_models': _CHAT_C1,
                'routes': {
                    'r': {'chat_models': ['c1'], 'duration_limiting': _DURATION}
                },
            },
            'duration_limiting requires at least one transcription model',
            id='duration-limiting-without-transcription-models',
        ),
        pytest.param(
            {
                'transcription_models': _WHISPER_W1,
                'routes': {
                    'r': {
                        'transcription_models': ['w1'],
                        'token_limiting': _INPUT_TOKENS,
                    },
                },
            },
            'token_limiting requires at least one chat, embedding or decision model',
            id='token-limiting-on-transcription-only-route',
        ),
    ],
)
def test_invalid_gateway_config_is_rejected(raw, match):
    with pytest.raises(ValueError, match=match):
        GatewayConfig.model_validate(raw)


def test_transcription_models_valid_config():
    raw = {
        'chat_models': [{'model_id': 'c1', 'model': 'openai/gpt-4o-mini'}],
        'transcription_models': [{'model_id': 'w1', 'model': 'openai/whisper-1'}],
        'routes': {
            'r': {'chat_models': ['c1'], 'transcription_models': ['w1']},
        },
    }
    gateway_config = GatewayConfig.model_validate(raw)
    assert list(gateway_config.transcription_models_by_id.keys()) == ['w1']
    assert gateway_config.routes['r'].transcription_models == ['w1']


def test_transcription_only_route_without_chat_models_is_valid():
    raw = {
        'chat_models': [{'model_id': 'c1', 'model': 'openai/gpt-4o-mini'}],
        'transcription_models': [{'model_id': 'w1', 'model': 'openai/whisper-1'}],
        'routes': {
            'r': {'transcription_models': ['w1']},
        },
    }
    gateway_config = GatewayConfig.model_validate(raw)
    assert gateway_config.routes['r'].chat_models is None
    assert gateway_config.routes['r'].transcription_models == ['w1']


def test_transcription_only_gateway_without_top_level_chat_models_is_valid():
    """A whole gateway config with no chat_models declared anywhere (top-level
    included), only transcription_models, is valid end-to-end.
    """
    raw = {
        'transcription_models': [{'model_id': 'w1', 'model': 'openai/whisper-1'}],
        'routes': {
            'r': {'transcription_models': ['w1']},
        },
    }
    gateway_config = GatewayConfig.model_validate(raw)
    assert gateway_config.chat_models is None
    assert gateway_config.chat_models_by_id == {}
    assert gateway_config.routes['r'].transcription_models == ['w1']


def test_transcription_fallback_valid_config():
    raw = {
        'transcription_models': [
            {'model_id': 'gpt4o', 'model': 'openai/gpt-4o-transcribe'},
            {'model_id': 'gpt4o-mini', 'model': 'openai/gpt-4o-mini-transcribe'},
        ],
        'routes': {
            'r': {
                'transcription_models': ['gpt4o', 'gpt4o-mini'],
                'fallback': [
                    {
                        'type': 'TRANSCRIPTION',
                        'target': 'gpt4o',
                        'fallbacks': ['gpt4o-mini'],
                    }
                ],
            },
        },
    }
    gateway_config = GatewayConfig.model_validate(raw)
    assert gateway_config.routes['r'].fallback[0].target == 'gpt4o'


def test_transcription_route_with_duration_limiting_valid_config():
    raw = {
        'transcription_models': [{'model_id': 'w1', 'model': 'openai/whisper-1'}],
        'routes': {
            'r': {
                'transcription_models': ['w1'],
                'duration_limiting': {
                    'max_duration_seconds': 300,
                    'window_size': '1 minute',
                },
            },
        },
    }
    gateway_config = GatewayConfig.model_validate(raw)
    route = gateway_config.routes['r']
    assert route.duration_limiting.max_duration_seconds == 300
    route_limits = RouteLimits.from_config(
        route, '2f1c6d4e-0000-4000-8000-0000000000aa'
    )
    assert route_limits.window(Category.AUDIO_SECONDS).config.limit == 300


def test_duration_limiting_valid_on_mixed_chat_and_transcription_route():
    raw = {
        'chat_models': [{'model_id': 'c1', 'model': 'openai/gpt-4o-mini'}],
        'transcription_models': [{'model_id': 'w1', 'model': 'openai/whisper-1'}],
        'routes': {
            'r': {
                'chat_models': ['c1'],
                'transcription_models': ['w1'],
                'duration_limiting': {
                    'max_duration_seconds': 300,
                    'window_size': '1 minute',
                },
            },
        },
    }
    gateway_config = GatewayConfig.model_validate(raw)
    assert gateway_config.routes['r'].duration_limiting.max_duration_seconds == 300


@pytest.mark.parametrize(
    ('category', 'model'),
    [
        pytest.param('chat_models', _CHAT_C1[0], id='chat'),
        pytest.param(
            'embedding_models',
            {'model_id': 'e1', 'model': 'openai/text-embedding-3-small'},
            id='embedding',
        ),
    ],
)
def test_token_limiting_valid_on_chat_or_embedding_route(category, model):
    raw = {
        category: [model],
        'routes': {
            'r': {category: [model['model_id']], 'token_limiting': _INPUT_TOKENS},
        },
    }
    gateway_config = GatewayConfig.model_validate(raw)
    assert gateway_config.routes['r'].token_limiting.input.max_tokens == 1000


def _llm_routing_raw(**routing_overrides) -> dict:
    model = {'model': 'openai/gpt-4o', 'credentials': {'api_key': 'sk-dummy'}}
    routing = {
        'name': 'llm_router',
        'type': 'llm',
        'router_model_id': 'router',
        'default_model_id': 'm1',
        'output_mapping': [
            {'model_id': 'm2', 'description': 'coding questions'},
        ],
        **routing_overrides,
    }
    return {
        'chat_models': [
            {'model_id': 'm1', **model},
            {'model_id': 'm2', **model},
            {'model_id': 'router', **model},
            {'model_id': 'router_backup', **model},
        ],
        'decision_models': [
            {
                'model_id': 'decider',
                'model': 'typesafe/jev-latest',
                'credentials': {'api_key': 'ts-dummy'},
            },
        ],
        'routing': [routing],
        'routes': {
            'r': {'chat_models': ['m1', 'm2'], 'routing': 'llm_router'},
        },
    }


def test_llm_routing_valid():
    gateway_config = GatewayConfig.model_validate(_llm_routing_raw())
    routing_config = gateway_config.routing_by_name['llm_router']
    assert routing_config.router_model_id == 'router'
    assert routing_config.threshold == 0.375
    assert routing_config.timeout == 10.0


@pytest.mark.parametrize(
    ('overrides', 'match'),
    [
        pytest.param(
            {'router_model_id': 'missing'},
            'not declared in top-level chat_models',
            id='router-model-not-in-chat-models',
        ),
        pytest.param(
            {'router_model_id': 'decider'},
            'not declared in top-level chat_models',
            id='router-model-is-a-decision-model',
        ),
        pytest.param(
            {'fallback_model_id': 'missing'},
            "fallback model 'missing' not declared",
            id='fallback-model-not-in-chat-models',
        ),
        pytest.param(
            {
                'output_mapping': [
                    {'model_id': 'm2', 'description': 'coding questions'},
                    {'model_id': 'm2', 'description': 'math questions'},
                ]
            },
            'model_ids must be unique',
            id='duplicate-model-ids',
        ),
        pytest.param(
            {
                'output_mapping': [
                    {'model_id': 'm2', 'conditions': ['coding questions']}
                ]
            },
            'description',
            id='entry-without-description',
        ),
        pytest.param(
            {'output_mapping': [{'model_id': 'm2', 'description': '  '}]},
            'description must not be empty',
            id='blank-description',
        ),
        pytest.param(
            {'message_roles': ['user']},
            'message_roles needs history: all',
            id='message-roles-without-history-all',
        ),
        pytest.param({'threshold': 1.5}, None, id='threshold-out-of-range'),
    ],
)
def test_llm_routing_invalid_config_is_rejected(overrides, match):
    with pytest.raises(ValueError, match=match):
        GatewayConfig.model_validate(_llm_routing_raw(**overrides))


def test_llm_routing_router_model_checked_when_no_route_uses_it():
    raw = _llm_routing_raw(router_model_id='missing')
    raw['routes'] = {'r': {'chat_models': ['m1', 'm2']}}
    with pytest.raises(ValueError, match="LLM routing 'llm_router': router model"):
        GatewayConfig.model_validate(raw)


def test_llm_routing_fallback_model_valid():
    gateway_config = GatewayConfig.model_validate(
        _llm_routing_raw(fallback_model_id='router_backup')
    )
    routing_config = gateway_config.routing_by_name['llm_router']
    assert routing_config.fallback_model_id == 'router_backup'


def test_llm_routing_message_roles_with_history_all():
    gateway_config = GatewayConfig.model_validate(
        _llm_routing_raw(history='all', message_roles=['user', 'assistant'])
    )
    routing_config = gateway_config.routing_by_name['llm_router']
    assert routing_config.history == 'all'
    assert [r.value for r in routing_config.message_roles] == ['USER', 'ASSISTANT']


def test_llm_routing_explicit_null_message_roles():
    gateway_config = GatewayConfig.model_validate(
        _llm_routing_raw(history='all', message_roles=None)
    )
    assert gateway_config.routing_by_name['llm_router'].message_roles is None


def _semantic_routing_raw(**routing_overrides) -> dict:
    model = {'model': 'openai/gpt-4o', 'credentials': {'api_key': 'sk-dummy'}}
    routing = {
        'name': 'semantic_router',
        'type': 'semantic',
        'embedding_model_id': 'emb',
        'default_model_id': 'm1',
        'output_mapping': [
            {'model_id': 'm2', 'conditions': ['coding questions']},
        ],
        **routing_overrides,
    }
    return {
        'chat_models': [
            {'model_id': 'm1', **model},
            {'model_id': 'm2', **model},
        ],
        'embedding_models': [
            {
                'model_id': 'emb',
                'model': 'openai/text-embedding-3-small',
                'credentials': {'api_key': 'sk-dummy'},
            },
        ],
        'routing': [routing],
        'routes': {
            'r': {'chat_models': ['m1', 'm2'], 'routing': 'semantic_router'},
        },
    }


def test_semantic_routing_valid():
    gateway_config = GatewayConfig.model_validate(_semantic_routing_raw())
    routing_config = gateway_config.routing_by_name['semantic_router']
    assert routing_config.embedding_model_id == 'emb'


def test_semantic_routing_embedding_model_not_in_top_level_embedding_models():
    with pytest.raises(ValueError, match='not declared in top-level embedding_models'):
        GatewayConfig.model_validate(
            _semantic_routing_raw(embedding_model_id='missing')
        )


def test_semantic_routing_embedding_model_checked_when_no_route_uses_it():
    raw = _semantic_routing_raw(embedding_model_id='missing')
    raw['routes'] = {'r': {'chat_models': ['m1', 'm2']}}
    with pytest.raises(
        ValueError, match="Semantic routing 'semantic_router': embedding model"
    ):
        GatewayConfig.model_validate(raw)
