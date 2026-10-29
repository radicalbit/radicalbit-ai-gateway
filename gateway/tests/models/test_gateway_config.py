import pytest

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


def test_cache_validation_fail():
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
    }

    with pytest.raises(
        ValueError,
        match='Configure cache of the gateway if caching for a route is enabled',
    ):
        GatewayConfig.model_validate(raw_data)


def test_invalid_cron_raises_error():
    raw = {
        'chat_models': [
            {
                'model_id': 'm1',
                'model': 'openai/gpt-4o',
                'credentials': {'api_key': 'sk-dummy'},
            },
        ],
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
        'routes': {
            'r': {'chat_models': ['m1'], 'routing': 'bad_time'},
        },
    }
    with pytest.raises(ValueError, match='invalid cron expression'):
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


def test_route_without_any_model_category_rejected():
    raw = {
        'chat_models': [{'model_id': 'c1', 'model': 'openai/gpt-4o-mini'}],
        'routes': {
            'r': {},
        },
    }
    with pytest.raises(
        ValueError,
        match='must reference at least one of chat_models, embedding_models, '
        'transcription_models, or decision_models',
    ):
        GatewayConfig.model_validate(raw)


def test_transcription_models_reject_missing_route_reference():
    raw = {
        'chat_models': [{'model_id': 'c1', 'model': 'openai/gpt-4o-mini'}],
        'transcription_models': [{'model_id': 'w1', 'model': 'openai/whisper-1'}],
        'routes': {
            'r': {'chat_models': ['c1'], 'transcription_models': ['unknown']},
        },
    }
    with pytest.raises(
        ValueError,
        match='transcription_models not declared in top-level transcription_models',
    ):
        GatewayConfig.model_validate(raw)


def test_transcription_models_reject_duplicate_ids_across_categories():
    raw = {
        'chat_models': [{'model_id': 'dup', 'model': 'openai/gpt-4o-mini'}],
        'transcription_models': [{'model_id': 'dup', 'model': 'openai/whisper-1'}],
    }
    with pytest.raises(
        ValueError,
        match='chat_models and transcription_models must have globally unique model_id',
    ):
        GatewayConfig.model_validate(raw)


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


def test_transcription_fallback_rejects_target_outside_route_transcription_models():
    raw = {
        'transcription_models': [
            {'model_id': 'gpt4o', 'model': 'openai/gpt-4o-transcribe'},
            {'model_id': 'gpt4o-mini', 'model': 'openai/gpt-4o-mini-transcribe'},
        ],
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
    }
    with pytest.raises(ValueError, match='must be present in the transcription models'):
        GatewayConfig.model_validate(raw)


def test_transcription_models_reject_duplicate_ids_within_list():
    raw = {
        'chat_models': [{'model_id': 'c1', 'model': 'openai/gpt-4o-mini'}],
        'transcription_models': [
            {'model_id': 'w1', 'model': 'openai/whisper-1'},
            {'model_id': 'w1', 'model': 'openai/whisper-1'},
        ],
    }
    with pytest.raises(
        ValueError, match='All transcription_models must have unique model_id'
    ):
        GatewayConfig.model_validate(raw)


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
    duration_limiter = route.get_duration_limiter(
        '2f1c6d4e-0000-4000-8000-0000000000aa'
    )
    assert duration_limiter.limiter is not None


def test_duration_limiting_rejected_without_transcription_models():
    raw = {
        'chat_models': [{'model_id': 'c1', 'model': 'openai/gpt-4o-mini'}],
        'routes': {
            'r': {
                'chat_models': ['c1'],
                'duration_limiting': {
                    'max_duration_seconds': 300,
                    'window_size': '1 minute',
                },
            },
        },
    }
    with pytest.raises(
        ValueError,
        match='duration_limiting requires at least one transcription model',
    ):
        GatewayConfig.model_validate(raw)


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


def test_token_limiting_rejected_on_transcription_only_route():
    raw = {
        'transcription_models': [{'model_id': 'w1', 'model': 'openai/whisper-1'}],
        'routes': {
            'r': {
                'transcription_models': ['w1'],
                'token_limiting': {
                    'input': {'max_tokens': 1000, 'window_size': '1 minute'},
                },
            },
        },
    }
    with pytest.raises(
        ValueError,
        match='token_limiting requires at least one chat, embedding or decision model',
    ):
        GatewayConfig.model_validate(raw)


def test_token_limiting_valid_on_chat_route():
    raw = {
        'chat_models': [{'model_id': 'c1', 'model': 'openai/gpt-4o-mini'}],
        'routes': {
            'r': {
                'chat_models': ['c1'],
                'token_limiting': {
                    'input': {'max_tokens': 1000, 'window_size': '1 minute'},
                },
            },
        },
    }
    gateway_config = GatewayConfig.model_validate(raw)
    assert gateway_config.routes['r'].token_limiting.input.max_tokens == 1000


def test_token_limiting_valid_on_embedding_route():
    raw = {
        'embedding_models': [
            {'model_id': 'e1', 'model': 'openai/text-embedding-3-small'}
        ],
        'routes': {
            'r': {
                'embedding_models': ['e1'],
                'token_limiting': {
                    'input': {'max_tokens': 1000, 'window_size': '1 minute'},
                },
            },
        },
    }
    gateway_config = GatewayConfig.model_validate(raw)
    assert gateway_config.routes['r'].token_limiting.input.max_tokens == 1000


def test_time_routing_model_id_not_in_route():
    raw = {
        'chat_models': [
            {
                'model_id': 'm1',
                'model': 'openai/gpt-4o',
                'credentials': {'api_key': 'sk-dummy'},
            },
            {
                'model_id': 'm2',
                'model': 'openai/gpt-4o',
                'credentials': {'api_key': 'sk-dummy'},
            },
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
        'routes': {
            'r': {'chat_models': ['m1'], 'routing': 'bad_ref'},
        },
    }
    with pytest.raises(ValueError, match='not in route chat_models'):
        GatewayConfig.model_validate(raw)


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


def test_llm_routing_router_model_not_in_top_level_chat_models():
    with pytest.raises(ValueError, match='not declared in top-level chat_models'):
        GatewayConfig.model_validate(_llm_routing_raw(router_model_id='missing'))


def test_llm_routing_router_model_cannot_be_a_decision_model():
    with pytest.raises(ValueError, match='not declared in top-level chat_models'):
        GatewayConfig.model_validate(_llm_routing_raw(router_model_id='decider'))


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


def test_llm_routing_fallback_model_not_in_top_level_chat_models():
    with pytest.raises(ValueError, match="fallback model 'missing' not declared"):
        GatewayConfig.model_validate(_llm_routing_raw(fallback_model_id='missing'))


def test_llm_routing_duplicate_model_ids():
    raw = _llm_routing_raw(
        output_mapping=[
            {'model_id': 'm2', 'description': 'coding questions'},
            {'model_id': 'm2', 'description': 'math questions'},
        ]
    )
    with pytest.raises(ValueError, match='model_ids must be unique'):
        GatewayConfig.model_validate(raw)


def test_llm_routing_entries_need_a_description():
    raw = _llm_routing_raw(
        output_mapping=[{'model_id': 'm2', 'conditions': ['coding questions']}]
    )
    with pytest.raises(ValueError, match='description'):
        GatewayConfig.model_validate(raw)


def test_llm_routing_description_must_not_be_blank():
    raw = _llm_routing_raw(output_mapping=[{'model_id': 'm2', 'description': '  '}])
    with pytest.raises(ValueError, match='description must not be empty'):
        GatewayConfig.model_validate(raw)


def test_llm_routing_message_roles_need_history_all():
    with pytest.raises(ValueError, match='message_roles needs history: all'):
        GatewayConfig.model_validate(_llm_routing_raw(message_roles=['user']))


def test_llm_routing_message_roles_with_history_all():
    gateway_config = GatewayConfig.model_validate(
        _llm_routing_raw(history='all', message_roles=['user', 'assistant'])
    )
    routing_config = gateway_config.routing_by_name['llm_router']
    assert routing_config.history == 'all'
    assert [r.value for r in routing_config.message_roles] == ['USER', 'ASSISTANT']


def test_llm_routing_threshold_out_of_range():
    with pytest.raises(ValueError):
        GatewayConfig.model_validate(_llm_routing_raw(threshold=1.5))


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
