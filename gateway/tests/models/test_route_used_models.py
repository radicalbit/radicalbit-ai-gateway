"""A route uses more models than its own lists: the models its guardrails and
its routing call. Usage cost must count the decision ones (AG-1126) and the
route's Models popover must list them all (AG-1127).
"""

import pytest

from radicalbit_ai_gateway.models.gateway_config import GatewayConfig, RouteModelIds
from radicalbit_ai_gateway.services.event_service import EventService


def _decision_model(model_id: str) -> dict:
    return {
        'model_id': model_id,
        'model': 'typesafe/jev-latest',
        'credentials': {'api_key': 'ts-dummy'},
    }


def _block(name: str, guardrail_type: str, parameters: dict) -> dict:
    return {
        'name': name,
        'type': guardrail_type,
        'where': 'input',
        'behavior': 'block',
        'parameters': parameters,
        'response_message': 'Blocked.',
    }


CONFIG = {
    'cache': {'redis_host': 'localhost', 'redis_port': 6379},
    'chat_models': [
        {'model_id': 'chat-a', 'model': 'openai/gpt-4o-mini'},
        {'model_id': 'chat-b', 'model': 'openai/gpt-4o'},
        {'model_id': 'judge', 'model': 'openai/gpt-4.1-nano'},
        {'model_id': 'router', 'model': 'openai/gpt-4.1-mini'},
    ],
    'embedding_models': [
        {'model_id': 'emb', 'model': 'openai/text-embedding-3-small'},
    ],
    'decision_models': [
        _decision_model('jev'),
        _decision_model('jev-judge-backup'),
        _decision_model('jev-router-backup'),
    ],
    'guardrails': [
        _block(
            'dj',
            'decision_judge',
            {
                'model_id': 'jev',
                'fallback_model_id': 'jev-judge-backup',
                'instructions': 'Is the user asking about something other than billing?',
            },
        ),
        _block('llm-judge', 'judge', {'model_id': 'judge', 'prompt': 'Is it safe?'}),
        _block('no-secrets', 'regex', {'values': ['secret']}),
    ],
    'routing': [
        {
            'name': 'by-decision',
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
        {
            'name': 'by-llm',
            'type': 'llm',
            'router_model_id': 'router',
            'default_model_id': 'chat-a',
            'output_mapping': [
                {'model_id': 'chat-a', 'description': 'Short questions.'},
                {'model_id': 'chat-b', 'description': 'Complex reasoning.'},
            ],
        },
        {
            'name': 'by-meaning',
            'type': 'semantic',
            'embedding_model_id': 'emb',
            'default_model_id': 'chat-a',
            'output_mapping': [
                {'model_id': 'chat-b', 'conditions': ['coding questions']},
            ],
        },
    ],
    'routes': {
        'served': {'decision_models': ['jev']},
        'decision-judged': {
            'chat_models': ['chat-a'],
            'guardrails': ['no-secrets', 'dj'],
        },
        'decision-routed': {
            'chat_models': ['chat-a', 'chat-b'],
            'routing': 'by-decision',
        },
        'llm-judged': {'chat_models': ['chat-a'], 'guardrails': ['llm-judge']},
        'llm-routed': {'chat_models': ['chat-a', 'chat-b'], 'routing': 'by-llm'},
        'semantic-routed': {
            'chat_models': ['chat-a', 'chat-b'],
            'routing': 'by-meaning',
        },
        # Semantic caching must list its embedding model on the route: no repeat.
        'semantic-cached': {
            'chat_models': ['chat-a'],
            'embedding_models': ['emb'],
            'caching': {'type': 'semantic', 'embedding_model_id': 'emb'},
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
        ('served', RouteModelIds([], [], [], ['jev'])),
        (
            'decision-judged',
            RouteModelIds(['chat-a'], [], [], ['jev', 'jev-judge-backup']),
        ),
        (
            'decision-routed',
            RouteModelIds(['chat-a', 'chat-b'], [], [], ['jev', 'jev-router-backup']),
        ),
        ('llm-judged', RouteModelIds(['chat-a', 'judge'], [], [], [])),
        ('llm-routed', RouteModelIds(['chat-a', 'chat-b', 'router'], [], [], [])),
        ('semantic-routed', RouteModelIds(['chat-a', 'chat-b'], ['emb'], [], [])),
        ('semantic-cached', RouteModelIds(['chat-a'], ['emb'], [], [])),
        ('plain', RouteModelIds(['chat-a'], [], [], [])),
    ],
)
def test_route_model_ids(config, route, expected):
    assert config.route_model_ids(config.routes[route]) == expected


@pytest.mark.parametrize(
    ('route', 'expected'),
    [
        ('served', True),
        ('decision-judged', True),
        ('decision-routed', True),
        ('plain', False),
    ],
)
def test_decision_cost_is_shown_for_every_way_a_route_calls_a_decision_model(
    config, route, expected
):
    *_, has_decision_models = config.get_route_feature_flags(config.routes[route])

    assert has_decision_models is expected


@pytest.mark.parametrize(
    ('route', 'expected'),
    [
        ('semantic-routed', True),
        ('semantic-cached', True),
        ('llm-routed', False),
        ('plain', False),
    ],
)
def test_embedding_cost_is_shown_for_every_way_a_route_calls_an_embedding_model(
    config, route, expected
):
    _, _, has_embedding_models, *_ = config.get_route_feature_flags(
        config.routes[route]
    )

    assert has_embedding_models is expected


def test_used_models_carry_names_and_own_lists_stay_as_configured(config):
    out = EventService._build_route_config_out(config.routes['decision-judged'], config)

    assert out.decision_models is None
    assert [m.model for m in out.used_models.chat] == ['openai/gpt-4o-mini']
    assert [m.model_id for m in out.used_models.decision] == ['jev', 'jev-judge-backup']
    assert out.model_dump(by_alias=True)['usedModels']['decision'][0]['model'] == (
        'typesafe/jev-latest'
    )


def test_used_models_list_llm_judge_and_semantic_cache_models(config):
    judged = EventService._build_route_config_out(config.routes['llm-judged'], config)
    cached = EventService._build_route_config_out(
        config.routes['semantic-cached'], config
    )

    assert [m.model_id for m in judged.used_models.chat] == ['chat-a', 'judge']
    assert [m.model_id for m in cached.used_models.embedding] == ['emb']
