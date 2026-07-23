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
