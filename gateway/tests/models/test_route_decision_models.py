"""A route calls a decision model when it serves it, when a decision judge asks
it, or when a decision routing asks it. Usage cost and the route's models list
must see all three (AG-1126, AG-1127).
"""

import pytest

from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.services.event_service import EventService


def _decision_model(model_id: str) -> dict:
    return {
        'model_id': model_id,
        'model': 'typesafe/jev-latest',
        'credentials': {'api_key': 'ts-dummy'},
    }


CONFIG = {
    'chat_models': [
        {'model_id': 'chat-a', 'model': 'openai/gpt-4o-mini'},
        {'model_id': 'chat-b', 'model': 'openai/gpt-4o'},
    ],
    'decision_models': [
        _decision_model('jev'),
        _decision_model('jev-judge-backup'),
        _decision_model('jev-router-backup'),
    ],
    'guardrails': [
        {
            'name': 'dj',
            'type': 'decision_judge',
            'where': 'input',
            'behavior': 'block',
            'parameters': {
                'model_id': 'jev',
                'fallback_model_id': 'jev-judge-backup',
                'instructions': 'Is the user asking about something other than billing?',
            },
            'response_message': 'Blocked.',
        },
        {
            'name': 'no-secrets',
            'type': 'regex',
            'where': 'input',
            'behavior': 'block',
            'parameters': {'values': ['secret']},
            'response_message': 'Blocked.',
        },
    ],
    'routing': [
        {
            'name': 'by-task',
            'type': 'decision',
            'decision_model_id': 'jev',
            'fallback_model_id': 'jev-router-backup',
            'instructions': 'Pick the model best suited to the request.',
            'default_model_id': 'chat-a',
            'output_mapping': [
                {'model_id': 'chat-a', 'description': 'Short questions.'},
                {'model_id': 'chat-b', 'description': 'Complex reasoning.'},
            ],
        },
    ],
    'routes': {
        'served': {'decision_models': ['jev']},
        'judged': {'chat_models': ['chat-a'], 'guardrails': ['no-secrets', 'dj']},
        'routed': {'chat_models': ['chat-a', 'chat-b'], 'routing': 'by-task'},
        'all': {
            'chat_models': ['chat-a', 'chat-b'],
            'decision_models': ['jev'],
            'guardrails': ['dj'],
            'routing': 'by-task',
        },
        'plain': {'chat_models': ['chat-a'], 'guardrails': ['no-secrets']},
    },
}


@pytest.fixture(scope='module')
def config() -> GatewayConfig:
    return GatewayConfig.model_validate(CONFIG)


@pytest.mark.parametrize(
    ('route', 'expected'),
    [
        ('served', ['jev']),
        ('judged', ['jev', 'jev-judge-backup']),
        ('routed', ['jev', 'jev-router-backup']),
        ('all', ['jev', 'jev-judge-backup', 'jev-router-backup']),
        ('plain', []),
    ],
)
def test_route_decision_model_ids(config, route, expected):
    assert config.route_decision_model_ids(config.routes[route]) == expected


@pytest.mark.parametrize(
    ('route', 'expected'),
    [
        ('served', True),
        ('judged', True),
        ('routed', True),
        ('plain', False),
    ],
)
def test_decision_cost_is_shown_for_every_way_a_route_calls_a_decision_model(
    config, route, expected
):
    *_, has_decision_models = config.get_route_feature_flags(config.routes[route])

    assert has_decision_models is expected


@pytest.mark.parametrize(
    ('route', 'served', 'all_used'),
    [
        ('served', ['jev'], ['jev']),
        ('judged', None, ['jev', 'jev-judge-backup']),
        ('routed', None, ['jev', 'jev-router-backup']),
        ('plain', None, []),
    ],
)
def test_route_out_lists_all_decision_models_and_keeps_served_ones_apart(
    config, route, served, all_used
):
    out = EventService._build_route_config_out(config.routes[route], config)

    served_ids = (
        None
        if out.decision_models is None
        else [m.model_id for m in out.decision_models]
    )
    assert served_ids == served
    assert [m.model_id for m in out.all_decision_models] == all_used
    assert 'allDecisionModels' in out.model_dump(by_alias=True)
