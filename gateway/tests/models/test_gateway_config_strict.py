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


def test_a_valid_config_is_accepted():
    GatewayConfig.model_validate(_with_guardrail(_judge()))


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


def test_free_form_fields_accept_any_key():
    GatewayConfig.model_validate(
        {'chat_models': [{**GPT, 'params': {'anything': 1}}], 'routes': {}}
    )


# References


def test_route_guardrail_names_are_case_sensitive():
    raw = _with_guardrail(_judge())
    raw['routes']['chat']['guardrails'] = ['J']

    [(_, msg)] = _errors(raw)

    assert (
        'guardrails not declared in top-level config (names are case-sensitive): J'
        in msg
    )


@pytest.mark.parametrize('field', ['model_id', 'fallback_model_id'])
def test_judge_model_must_be_a_chat_model(field):
    [(_, msg)] = _errors(_with_guardrail(_judge(**{field: 'missing'})))

    assert (
        "Guardrail 'j': judge model 'missing' not declared in top-level chat_models."
        in msg
    )


def test_judge_model_cannot_be_a_decision_model():
    [(_, msg)] = _errors(_with_guardrail(_judge(model_id='jev'), decision_models=[JEV]))

    assert "judge model 'jev' not declared in top-level chat_models" in msg


def test_decision_judge_model_must_be_a_decision_model():
    raw = _with_guardrail(
        {
            'name': 'dj',
            'type': 'decision_judge',
            'parameters': {'model_id': 'gpt', 'instructions': 'Off topic?'},
        },
        decision_models=[JEV],
    )

    [(_, msg)] = _errors(raw)

    assert "decision judge model 'gpt' not declared in top-level decision_models" in msg


# Parameter values


def test_invalid_regex_is_rejected():
    raw = _with_guardrail(
        {'name': 'r', 'type': 'regex', 'parameters': {'values': ['ok', '[unclosed']}}
    )

    [(_, msg)] = _errors(raw)

    assert "Invalid regex '[unclosed'" in msg


def test_unsupported_presidio_language_is_rejected():
    raw = _with_guardrail(
        {
            'name': 'pii',
            'type': 'presidio_analyzer',
            'parameters': {'entities': ['EMAIL_ADDRESS'], 'language': 'fr'},
        }
    )

    [(_, msg)] = _errors(raw)

    assert "Language 'fr' is not supported, use one of: en, it." in msg


def test_ahds_backend_requires_an_endpoint():
    raw = _with_guardrail(
        {
            'name': 'pii',
            'type': 'presidio_analyzer',
            'parameters': {'entities': ['EMAIL_ADDRESS'], 'backend': 'ahds'},
        }
    )

    [(_, msg)] = _errors(raw)

    assert "ahds.endpoint must be set when backend is 'ahds'." in msg


# Route limiting


@pytest.mark.parametrize(
    ('route', 'expected'),
    [
        (
            {'rate_limiting': {'window_size': '1 minute', 'max_tokens': 10}},
            'max_requests must be set for rate limiting.',
        ),
        (
            {
                'token_limiting': {
                    'input': {'window_size': '1 minute', 'max_requests': 1}
                }
            },
            'input.max_tokens must be set for token limiting.',
        ),
        (
            {'budget_limiting': {'window_size': '1 day'}},
            'max_budget must be set for budget limiting.',
        ),
    ],
)
def test_limiting_without_its_max_field_is_rejected(route, expected):
    [(_, msg)] = _errors(_with_route(**route))

    assert expected in msg


def test_zero_budget_is_allowed():
    GatewayConfig.model_validate(
        _with_route(budget_limiting={'window_size': '1 day', 'max_budget': 0})
    )


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


def test_output_guardrail_on_route_with_chat_models_is_accepted():
    guardrail = {
        'name': 'g',
        'type': 'contains',
        'where': 'output',
        'parameters': {'values': ['x']},
    }

    GatewayConfig.model_validate(_with_guardrail(guardrail))
