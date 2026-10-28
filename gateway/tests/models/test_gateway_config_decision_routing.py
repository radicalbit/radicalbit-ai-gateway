from pydantic import TypeAdapter
import pytest

from tests.common.decision_routing import JEV, JEV_BACKUP

from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_config_out import (
    AnyRoutingConfigOut,
    DecisionRoutingConfigOut,
)
from radicalbit_ai_gateway.models.guardrails import GuardrailMessageRole
from radicalbit_ai_gateway.models.routing import DecisionRoutingConfig

GPT_4O = {'model_id': 'gpt-4o', 'model': 'openai/gpt-4o'}
GPT_5 = {'model_id': 'gpt-5', 'model': 'openai/gpt-5'}


def _routing(**overrides) -> dict:
    return {
        'name': 'by-task',
        'type': 'decision',
        'decision_model_id': 'jev',
        'instructions': 'Choose the model best suited to answer this request.',
        'default_model_id': 'gpt-4o',
        'output_mapping': [
            {'model_id': 'gpt-4o', 'description': 'Emails and business documents'},
            {'model_id': 'gpt-5', 'description': 'Translation to Chinese'},
        ],
        **overrides,
    }


def _config(routing: dict, route: dict | None = None) -> GatewayConfig:
    return GatewayConfig.model_validate(
        {
            'chat_models': [GPT_4O, GPT_5],
            'decision_models': [JEV, JEV_BACKUP],
            'routing': [routing],
            'routes': {
                'chat': route
                or {'chat_models': ['gpt-4o', 'gpt-5'], 'routing': 'by-task'}
            },
        }
    )


def test_a_decision_routing_loads_with_its_defaults():
    routing = _config(_routing()).routing[0]

    assert isinstance(routing, DecisionRoutingConfig)
    assert routing.history == 'last'
    assert routing.min_confidence is None
    assert routing.fallback_model_id is None
    assert routing.message_roles is None
    assert [e.description for e in routing.output_mapping] == [
        'Emails and business documents',
        'Translation to Chinese',
    ]


def test_a_full_decision_routing_loads():
    routing = _config(
        _routing(
            fallback_model_id='jev-backup',
            min_confidence=0.6,
            history='all',
            message_roles=['user', 'assistant'],
        )
    ).routing[0]

    assert routing.fallback_model_id == 'jev-backup'
    assert routing.min_confidence == 0.6
    assert routing.message_roles == [
        GuardrailMessageRole.USER,
        GuardrailMessageRole.ASSISTANT,
    ]


def test_a_decision_routing_that_no_route_uses_still_loads():
    config = GatewayConfig.model_validate(
        {
            'chat_models': [GPT_4O, GPT_5],
            'decision_models': [JEV],
            'routing': [_routing()],
            'routes': {'chat': {'chat_models': ['gpt-4o']}},
        }
    )

    assert config.routing_by_name['by-task'].decision_model_id == 'jev'


@pytest.mark.parametrize(
    ('overrides', 'match'),
    [
        pytest.param(
            {'decision_model_id': 'nope'},
            "routing 'by-task': decision model 'nope' not declared in top-level "
            'decision_models',
            id='unknown decision model',
        ),
        pytest.param(
            {'decision_model_id': 'gpt-4o'},
            "routing 'by-task': decision model 'gpt-4o' not declared in top-level "
            'decision_models',
            id='chat model as decision model',
        ),
        pytest.param(
            {'fallback_model_id': 'nope'},
            "routing 'by-task': fallback model 'nope' not declared in top-level "
            'decision_models',
            id='unknown fallback model',
        ),
        pytest.param(
            {'instructions': '  '}, 'instructions must not be empty', id='instructions'
        ),
        pytest.param(
            {
                'output_mapping': [
                    {'model_id': 'gpt-4o', 'description': 'Emails'},
                    {'model_id': 'gpt-5', 'description': ''},
                ]
            },
            'description must not be empty',
            id='empty description',
        ),
        pytest.param(
            {'output_mapping': [{'model_id': 'gpt-4o', 'description': 'Emails'}]},
            'decision routing needs at least 2 output_mapping entries',
            id='one entry',
        ),
        pytest.param(
            {'output_mapping': [{'model_id': 'gpt-4o', 'conditions': ['x']}] * 2},
            'description',
            id='conditions instead of description',
        ),
        pytest.param(
            {'message_roles': ['user']},
            'message_roles needs history: all',
            id='message_roles with history last',
        ),
        pytest.param({'history': 'some'}, "'last' or 'all'", id='unknown history'),
        pytest.param(
            {'min_confidence': 1.5}, 'min_confidence', id='min_confidence > 1'
        ),
        pytest.param(
            {'min_confidence': -0.1}, 'min_confidence', id='min_confidence < 0'
        ),
        pytest.param(
            {'history': 'all', 'message_roles': ['robot']},
            'message_roles',
            id='unknown role',
        ),
    ],
)
def test_a_bad_decision_routing_is_rejected(overrides, match):
    with pytest.raises(ValueError, match=match):
        _config(_routing(**overrides))


def test_an_unknown_decision_model_is_rejected_even_when_no_route_uses_it():
    with pytest.raises(ValueError, match="decision model 'nope'"):
        GatewayConfig.model_validate(
            {
                'chat_models': [GPT_4O, GPT_5],
                'decision_models': [JEV],
                'routing': [_routing(decision_model_id='nope')],
                'routes': {'chat': {'chat_models': ['gpt-4o']}},
            }
        )


@pytest.mark.parametrize(
    ('route', 'match'),
    [
        pytest.param(
            {'chat_models': ['gpt-5'], 'routing': 'by-task'},
            "default_model_id 'gpt-4o' not in route chat_models",
            id='default not on the route',
        ),
        pytest.param(
            {'chat_models': ['gpt-4o'], 'routing': 'by-task'},
            "model_id 'gpt-5' not in route chat_models",
            id='mapping model not on the route',
        ),
    ],
)
def test_the_existing_route_rules_still_apply(route, match):
    with pytest.raises(ValueError, match=match):
        _config(_routing(), route=route)


@pytest.mark.parametrize(
    'overrides',
    [
        pytest.param({'default_model_id': 'jev'}, id='default'),
        pytest.param(
            {
                'output_mapping': [
                    {'model_id': 'gpt-4o', 'description': 'Emails'},
                    {'model_id': 'jev', 'description': 'Decisions'},
                ]
            },
            id='output_mapping',
        ),
    ],
)
def test_decision_models_cannot_be_routed_to(overrides):
    with pytest.raises(
        ValueError, match="routing cannot reference decision model 'jev'"
    ):
        _config(
            _routing(**overrides),
            route={
                'chat_models': ['gpt-4o', 'gpt-5'],
                'decision_models': ['jev'],
                'routing': 'by-task',
            },
        )


def test_the_routing_out_dto_accepts_a_decision_routing():
    routing = _config(_routing(history='all', message_roles=['user'])).routing[0]

    out = TypeAdapter(AnyRoutingConfigOut).validate_python(routing.model_dump())

    assert isinstance(out, DecisionRoutingConfigOut)
    dumped = out.model_dump(by_alias=True)
    assert dumped['decisionModelId'] == 'jev'
    assert dumped['outputMapping'][0]['description'] == 'Emails and business documents'
