from pydantic import ValidationError
import pytest

from radicalbit_ai_gateway.models.gateway_config import GatewayConfig

GPT = {'model_id': 'gpt', 'model': 'openai/gpt-4o-mini'}
JEV = {'model_id': 'jev', 'model': 'typesafe/jev-latest'}


def _with_guardrail(guardrail: dict, **top_level) -> dict:
    return {
        'chat_models': [GPT],
        'guardrails': [guardrail],
        'routes': {'chat': {'chat_models': ['gpt'], 'guardrails': [guardrail['name']]}},
        **top_level,
    }


def _with_route(**route) -> dict:
    return {'chat_models': [GPT], 'routes': {'chat': {'chat_models': ['gpt'], **route}}}


def _judge(**parameters) -> dict:
    return {
        'name': 'j',
        'type': 'judge',
        'parameters': {'model_id': 'gpt', 'prompt': 'hi', **parameters},
    }


def _errors(raw: dict) -> list[tuple[str, str]]:
    with pytest.raises(ValidationError) as exc_info:
        GatewayConfig.model_validate(raw)
    return [
        ('.'.join(str(p) for p in e['loc']), e['msg']) for e in exc_info.value.errors()
    ]


# Unknown fields


@pytest.mark.parametrize(
    ('raw', 'loc'),
    [
        (
            _with_guardrail(_judge(temprature=0.2)),
            'guardrails.0.parameters.JUDGE.temprature',
        ),
        (
            {'chat_models': [{**GPT, 'retry_attemps': 5}], 'routes': {}},
            'chat_models.0.retry_attemps',
        ),
        (
            {
                'chat_models': [{**GPT, 'credentials': {'api_kye': 'x'}}],
                'routes': {},
            },
            'chat_models.0.credentials.api_kye',
        ),
        (
            _with_route(
                rate_limiting={
                    'window_size': '1 minute',
                    'max_requests': 5,
                    'windowsize': 1,
                }
            ),
            'routes.chat.rate_limiting.windowsize',
        ),
    ],
)
def test_unknown_field_is_rejected(raw, loc):
    assert _errors(raw) == [(loc, 'Extra inputs are not permitted')]


# One clear error per invalid value


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        pytest.param(
            {
                **_with_guardrail(_judge()),
                'routes': {'chat': {'chat_models': ['gpt'], 'guardrails': ['J']}},
            },
            'guardrails not declared in top-level config (names are case-sensitive): J',
            id='route-guardrail-names-case-sensitive',
        ),
        pytest.param(
            _with_guardrail(_judge(model_id='missing')),
            "Guardrail 'j': judge model 'missing' not declared in top-level chat_models.",
            id='judge-model-not-a-chat-model',
        ),
        pytest.param(
            _with_guardrail(_judge(fallback_model_id='missing')),
            "Guardrail 'j': judge model 'missing' not declared in top-level chat_models.",
            id='judge-fallback-model-not-a-chat-model',
        ),
        pytest.param(
            _with_guardrail(_judge(model_id='jev'), decision_models=[JEV]),
            "judge model 'jev' not declared in top-level chat_models",
            id='judge-model-is-a-decision-model',
        ),
        pytest.param(
            _with_guardrail(
                {
                    'name': 'dj',
                    'type': 'decision_judge',
                    'parameters': {'model_id': 'gpt', 'instructions': 'Off topic?'},
                },
                decision_models=[JEV],
            ),
            "decision judge model 'gpt' not declared in top-level decision_models",
            id='decision-judge-model-not-a-decision-model',
        ),
        pytest.param(
            _with_guardrail(
                {
                    'name': 'r',
                    'type': 'regex',
                    'parameters': {'values': ['ok', '[unclosed']},
                }
            ),
            "Invalid regex '[unclosed'",
            id='invalid-regex',
        ),
        pytest.param(
            _with_guardrail(
                {
                    'name': 'pii',
                    'type': 'presidio_analyzer',
                    'parameters': {'entities': ['EMAIL_ADDRESS'], 'language': 'fr'},
                }
            ),
            "Language 'fr' is not supported, use one of: en, it.",
            id='unsupported-presidio-language',
        ),
        pytest.param(
            _with_guardrail(
                {
                    'name': 'pii',
                    'type': 'presidio_analyzer',
                    'parameters': {'entities': ['EMAIL_ADDRESS'], 'backend': 'ahds'},
                }
            ),
            "ahds.endpoint must be set when backend is 'ahds'.",
            id='ahds-backend-without-endpoint',
        ),
        pytest.param(
            _with_route(rate_limiting={'window_size': '1 minute', 'max_tokens': 10}),
            'max_requests must be set for rate limiting.',
            id='rate-limiting-without-max-requests',
        ),
        pytest.param(
            _with_route(
                token_limiting={'input': {'window_size': '1 minute', 'max_requests': 1}}
            ),
            'input.max_tokens must be set for token limiting.',
            id='token-limiting-without-max-tokens',
        ),
        pytest.param(
            _with_route(budget_limiting={'window_size': '1 day'}),
            'max_budget must be set for budget limiting.',
            id='budget-limiting-without-max-budget',
        ),
    ],
)
def test_invalid_value_is_rejected_with_one_error(raw, expected):
    [(_, msg)] = _errors(raw)

    assert expected in msg


@pytest.mark.parametrize(
    'raw',
    [
        pytest.param(_with_guardrail(_judge()), id='valid-config'),
        pytest.param(
            {'chat_models': [{**GPT, 'params': {'anything': 1}}], 'routes': {}},
            id='free-form-fields-accept-any-key',
        ),
        pytest.param(
            _with_route(budget_limiting={'window_size': '1 day', 'max_budget': 0}),
            id='zero-budget',
        ),
        pytest.param(
            _with_guardrail(
                {
                    'name': 'g',
                    'type': 'contains',
                    'where': 'output',
                    'parameters': {'values': ['x']},
                }
            ),
            id='output-guardrail-on-route-with-chat-models',
        ),
    ],
)
def test_valid_config_is_accepted(raw):
    GatewayConfig.model_validate(raw)


# Guardrail placement

EMB = {'model_id': 'emb', 'model': 'openai/text-embedding-3-small'}
WHISPER = {'model_id': 'whisper', 'model': 'openai/whisper-1'}

_CHATLESS_ROUTES = {
    'embedding': {'embedding_models': ['emb']},
    'transcription': {'transcription_models': ['whisper']},
    'decision': {'decision_models': ['jev']},
}


def _on_chatless_route(kind: str, guardrail: dict) -> dict:
    return {
        'chat_models': [GPT],
        'embedding_models': [EMB],
        'transcription_models': [WHISPER],
        'decision_models': [JEV],
        'guardrails': [guardrail],
        'routes': {
            'r': {**_CHATLESS_ROUTES[kind], 'guardrails': [guardrail['name']]},
        },
    }


_GUARDRAILS_OF_EVERY_TYPE = [
    {'name': 'g', 'type': 'starts_with', 'parameters': {'values': ['x']}},
    {'name': 'g', 'type': 'ends_with', 'parameters': {'values': ['x']}},
    {'name': 'g', 'type': 'contains', 'parameters': {'values': ['x']}},
    {'name': 'g', 'type': 'regex', 'parameters': {'values': ['x']}},
    {
        'name': 'g',
        'type': 'presidio_analyzer',
        'parameters': {'entities': ['EMAIL_ADDRESS']},
    },
    {
        'name': 'g',
        'type': 'presidio_anonymizer',
        'parameters': {'entities': ['EMAIL_ADDRESS']},
    },
    {'name': 'g', 'type': 'judge', 'parameters': {'model_id': 'gpt', 'prompt': 'x'}},
    {
        'name': 'g',
        'type': 'decision_judge',
        'parameters': {'model_id': 'jev', 'instructions': 'x'},
    },
    {'name': 'g', 'type': 'guardrails_ai', 'parameters': {'guard_name': 'x'}},
]


@pytest.mark.parametrize('kind', list(_CHATLESS_ROUTES))
@pytest.mark.parametrize(
    'guardrail', _GUARDRAILS_OF_EVERY_TYPE, ids=lambda g: g['type']
)
def test_output_guardrail_on_route_without_chat_models_is_rejected(kind, guardrail):
    raw = _on_chatless_route(kind, {**guardrail, 'where': 'output'})

    [(_, msg)] = _errors(raw)

    assert (
        "Route 'r': guardrail 'g' has where: output, but the route has no "
        'chat_models. The guardrail would never run.'
    ) in msg


@pytest.mark.parametrize('kind', list(_CHATLESS_ROUTES))
def test_io_guardrail_on_route_without_chat_models_is_accepted(kind):
    guardrail = {'name': 'g', 'type': 'contains', 'parameters': {'values': ['x']}}

    GatewayConfig.model_validate(_on_chatless_route(kind, {**guardrail, 'where': 'io'}))
