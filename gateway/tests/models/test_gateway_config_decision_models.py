from decimal import Decimal

import pytest

from radicalbit_ai_gateway.models.gateway_config import GatewayConfig

JEV = {
    'model_id': 'jev',
    'model': 'typesafe/jev-latest',
    'credentials': {'api_key': 'ts-dummy'},
}


def test_decision_models_accepted_at_top_level_and_on_route():
    config = GatewayConfig.model_validate(
        {
            'decision_models': [JEV],
            'routes': {'agent': {'decision_models': ['jev']}},
        }
    )

    assert config.decision_models_by_id['jev'].model == 'typesafe/jev-latest'
    assert config.routes['agent'].decision_models == ['jev']


def test_route_can_hold_decision_models_alongside_chat_models():
    config = GatewayConfig.model_validate(
        {
            'chat_models': [{'model_id': 'gpt', 'model': 'openai/gpt-4o-mini'}],
            'decision_models': [JEV],
            'routes': {'agent': {'chat_models': ['gpt'], 'decision_models': ['jev']}},
        }
    )

    assert config.routes['agent'].chat_models == ['gpt']
    assert config.routes['agent'].decision_models == ['jev']


def test_decision_model_id_reused_by_another_category_is_rejected():
    with pytest.raises(
        ValueError,
        match='chat_models and decision_models must have globally unique model_id',
    ):
        GatewayConfig.model_validate(
            {
                'chat_models': [{'model_id': 'jev', 'model': 'openai/gpt-4o-mini'}],
                'decision_models': [JEV],
            }
        )


def test_decision_model_ids_must_be_unique():
    with pytest.raises(ValueError, match='All decision_models must have unique'):
        GatewayConfig.model_validate({'decision_models': [JEV, JEV]})


def test_route_referencing_undeclared_decision_model_is_rejected():
    with pytest.raises(
        ValueError, match='decision_models not declared in top-level decision_models'
    ):
        GatewayConfig.model_validate(
            {
                'decision_models': [JEV],
                'routes': {'agent': {'decision_models': ['missing']}},
            }
        )


def test_decision_model_with_a_non_typesafe_provider_is_rejected():
    with pytest.raises(ValueError, match="decision model 'jev'.*typesafe"):
        GatewayConfig.model_validate(
            {'decision_models': [{'model_id': 'jev', 'model': 'openai/gpt-4o-mini'}]}
        )


@pytest.mark.parametrize(
    ('mapping_model_id', 'default_model_id'),
    [('jev', 'gpt'), ('gpt', 'jev')],
)
def test_decision_models_are_rejected_inside_routing(
    mapping_model_id, default_model_id
):
    with pytest.raises(
        ValueError, match="routing cannot reference decision model 'jev'"
    ):
        GatewayConfig.model_validate(
            {
                'chat_models': [{'model_id': 'gpt', 'model': 'openai/gpt-4o-mini'}],
                'decision_models': [JEV],
                'routing': [
                    {
                        'name': 'by_time',
                        'type': 'deterministic',
                        'default_model_id': default_model_id,
                        'rule': 'time',
                        'output_mapping': [
                            {
                                'model_id': mapping_model_id,
                                'conditions': ['0 9-17 * * 1-5'],
                            }
                        ],
                    }
                ],
                'routes': {
                    'agent': {
                        'chat_models': ['gpt'],
                        'decision_models': ['jev'],
                        'routing': 'by_time',
                    }
                },
            }
        )


def test_jev_default_price_comes_from_the_price_list():
    config = GatewayConfig.model_validate({'decision_models': [JEV]})

    jev = config.decision_models_by_id['jev']
    assert jev.input_cost_per_million_tokens == Decimal('0.042')
    assert jev.output_cost_per_million_tokens == Decimal('0')


def test_jev_input_price_can_be_overridden_and_output_price_is_forced_to_zero():
    config = GatewayConfig.model_validate(
        {
            'decision_models': [
                {
                    **JEV,
                    'input_cost_per_million_tokens': 0.05,
                    'output_cost_per_million_tokens': 3,
                }
            ]
        }
    )

    jev = config.decision_models_by_id['jev']
    assert jev.input_cost_per_million_tokens == Decimal('0.05')
    assert jev.output_cost_per_million_tokens == Decimal('0')


JEV_EU = {**JEV, 'model_id': 'jev-eu'}


def test_decision_fallback_between_decision_models_is_accepted():
    config = GatewayConfig.model_validate(
        {
            'decision_models': [JEV, JEV_EU],
            'routes': {
                'agent': {
                    'decision_models': ['jev', 'jev-eu'],
                    'fallback': [
                        {'target': 'jev', 'fallbacks': ['jev-eu'], 'type': 'decision'}
                    ],
                }
            },
        }
    )

    [fallback] = config.routes['agent'].fallback
    assert fallback.type.value == 'DECISION'


@pytest.mark.parametrize(
    ('fallback', 'label'),
    [
        ({'target': 'jev', 'fallbacks': ['gpt'], 'type': 'decision'}, 'decision'),
        ({'target': 'gpt', 'fallbacks': ['jev'], 'type': 'chat'}, 'chat'),
        ({'target': 'jev', 'fallbacks': ['jev-eu'], 'type': 'chat'}, 'chat'),
    ],
)
def test_fallback_mixing_decision_and_chat_models_is_rejected(fallback, label):
    with pytest.raises(ValueError, match=f'must be present in the {label} models'):
        GatewayConfig.model_validate(
            {
                'chat_models': [{'model_id': 'gpt', 'model': 'openai/gpt-4o-mini'}],
                'decision_models': [JEV, JEV_EU],
                'routes': {
                    'agent': {
                        'chat_models': ['gpt'],
                        'decision_models': ['jev', 'jev-eu'],
                        'fallback': [fallback],
                    }
                },
            }
        )


def test_input_token_limit_is_accepted_on_a_decision_only_route():
    config = GatewayConfig.model_validate(
        {
            'decision_models': [JEV],
            'routes': {
                'agent': {
                    'decision_models': ['jev'],
                    'token_limiting': {'input': {'max_tokens': 1000}},
                }
            },
        }
    )

    assert config.routes['agent'].token_limiting.input.max_tokens == 1000


def test_output_token_limit_on_a_decision_only_route_is_rejected():
    with pytest.raises(ValueError, match='Decision models produce no output tokens'):
        GatewayConfig.model_validate(
            {
                'decision_models': [JEV],
                'routes': {
                    'agent': {
                        'decision_models': ['jev'],
                        'token_limiting': {'output': {'max_tokens': 1000}},
                    }
                },
            }
        )


def test_output_token_limit_is_accepted_when_the_route_also_has_chat_models():
    config = GatewayConfig.model_validate(
        {
            'chat_models': [{'model_id': 'gpt', 'model': 'openai/gpt-4o-mini'}],
            'decision_models': [JEV],
            'routes': {
                'agent': {
                    'chat_models': ['gpt'],
                    'decision_models': ['jev'],
                    'token_limiting': {'output': {'max_tokens': 1000}},
                }
            },
        }
    )

    assert config.routes['agent'].token_limiting.output.max_tokens == 1000


CACHE = {'redis_host': 'localhost', 'redis_port': 6379}


def test_semantic_caching_on_a_decision_only_route_is_rejected():
    with pytest.raises(
        ValueError, match='semantic caching is not allowed on a route with only'
    ):
        GatewayConfig.model_validate(
            {
                'decision_models': [JEV],
                'cache': CACHE,
                'routes': {
                    'agent': {
                        'decision_models': ['jev'],
                        'caching': {
                            'type': 'semantic',
                            'embedding_model_id': 'emb',
                        },
                    }
                },
            }
        )


def test_exact_caching_is_accepted_on_a_decision_only_route():
    config = GatewayConfig.model_validate(
        {
            'decision_models': [JEV],
            'cache': CACHE,
            'routes': {
                'agent': {'decision_models': ['jev'], 'caching': {'type': 'exact'}}
            },
        }
    )

    assert config.routes['agent'].caching.type == 'exact'
