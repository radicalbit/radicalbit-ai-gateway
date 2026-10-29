"""DecisionRouter.select_model with Typesafe mocked over HTTP."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pook
import pytest

from tests.common.decision_routing import (
    BACKOFF_SLEEP,
    CHINESE,
    EMAILS,
    INSTRUCTIONS,
    JEV,
    JEV_BACKUP,
    QUESTION_ID,
    ROUTER_SPAN,
    TYPESAFE_KEY,
    TYPESAFE_URL,
    USER_TEXT,
)

from radicalbit_ai_gateway.invocation.decision_model_invoker import DecisionModelInvoker
from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.routing import DecisionRoutingConfig
from radicalbit_ai_gateway.routing.decision_router import DecisionRouter
from radicalbit_ai_gateway.services.cost_service import CostService

OPTIONS = {'option_1': EMAILS, 'option_2': CHINESE}

JEV_MODEL = Model.model_validate(JEV)
JEV_BACKUP_MODEL = Model.model_validate(JEV_BACKUP)
GPT_4O = Model.model_validate({'model_id': 'gpt-4o', 'model': 'openai/gpt-4o'})
GPT_5 = Model.model_validate({'model_id': 'gpt-5', 'model': 'openai/gpt-5'})
MINI = Model.model_validate({'model_id': 'mini', 'model': 'openai/gpt-4o-mini'})


def _config(**overrides) -> DecisionRoutingConfig:
    return DecisionRoutingConfig.model_validate(
        {
            'name': 'by-task',
            'type': 'decision',
            'decision_model_id': 'jev',
            'instructions': INSTRUCTIONS,
            'default_model_id': 'mini',
            'output_mapping': [
                {'model_id': 'gpt-4o', 'description': EMAILS},
                {'model_id': 'gpt-5', 'description': CHINESE},
            ],
            **overrides,
        }
    )


def _router(**overrides) -> DecisionRouter:
    decision_models = [JEV_MODEL, JEV_BACKUP_MODEL]
    invoker = DecisionModelInvoker(
        models=decision_models,
        cost_service=CostService(
            decision_models_by_id={m.model_id: m for m in decision_models}
        ),
    )
    return DecisionRouter(
        config=_config(**overrides),
        models_by_id={m.model_id: m for m in (GPT_4O, GPT_5, MINI)},
        invoker=invoker,
    )


def _answer(**fields) -> dict:
    """Build a Jev response whose Choice answer has exactly these fields."""
    return {
        'model': 'jev-1.13.0',
        'answers': {QUESTION_ID: {'type': 'choice', **fields}},
        'usage': {'input_tokens': 280, 'output_tokens': 0},
    }


def _choice_answer(probabilities: dict, confidence: float | None = None) -> dict:
    """Jev's answer for these probabilities: the top option, its confidence."""
    top = max(probabilities, key=probabilities.get)
    return _answer(
        choice=top,
        confidence=probabilities[top] if confidence is None else confidence,
        probabilities=probabilities,
    )


def _mock_typesafe(
    choice=None,
    *,
    body=None,
    state: str = USER_TEXT,
    model: str = 'jev-latest',
    status: int = 200,
    times: int = 1,
    options: dict = OPTIONS,
):
    mock = (
        pook.post(TYPESAFE_URL)
        .header('Authorization', f'Bearer {TYPESAFE_KEY}')
        .json(
            {
                'model': model,
                'state': state,
                'questions': {
                    QUESTION_ID: {
                        'type': 'choice',
                        'instructions': INSTRUCTIONS,
                        'criteria': options,
                    }
                },
            }
        )
        .times(times)
    )
    mock.reply(status).json(body if body is not None else _choice_answer(choice))
    return mock


@pytest.fixture(autouse=True)
def _http():
    with patch(BACKOFF_SLEEP, new=AsyncMock()):
        pook.on()
        try:
            yield
        finally:
            pook.off()


@pytest.fixture
def span():
    span = MagicMock()
    span.is_recording.return_value = True
    with patch(ROUTER_SPAN, return_value=span):
        yield span


def _attributes(span) -> dict:
    return {c.args[0]: c.args[1] for c in span.set_attribute.call_args_list}


async def test_the_chosen_option_selects_its_model():
    mock = _mock_typesafe({'option_1': 0.1, 'option_2': 0.85})

    model = await _router().select_model([HumanMessage(content=USER_TEXT)])

    assert model is GPT_5
    assert mock.isdone()


async def test_a_transient_error_is_retried_on_the_same_model():
    pook.post(TYPESAFE_URL).times(1).reply(503).json({'error': 'busy'})
    _mock_typesafe({'option_1': 0.9, 'option_2': 0.1})

    model = await _router().select_model([HumanMessage(content=USER_TEXT)])

    assert model is GPT_4O


async def test_an_error_after_retries_without_fallback_uses_the_default(span):
    mock = _mock_typesafe(body={'error': 'busy'}, status=503, times=4)

    model = await _router().select_model([HumanMessage(content=USER_TEXT)])

    assert model is MINI
    assert mock.isdone()
    attributes = _attributes(span)
    assert attributes['routing.decision.default_used'] is True
    assert attributes['routing.decision.default_reason'] == 'error'
    assert attributes['routing.decision.fallback_used'] is False


async def test_a_network_error_goes_to_the_fallback(span):
    pook.post(TYPESAFE_URL).times(4).error(httpx.ConnectError('refused'))
    fallback = _mock_typesafe({'option_1': 0.2, 'option_2': 0.7}, model='jev-backup')

    model = await _router(fallback_model_id='jev-backup').select_model(
        [HumanMessage(content=USER_TEXT)]
    )

    assert model is GPT_5
    assert fallback.isdone()
    attributes = _attributes(span)
    assert attributes['routing.decision.model_id'] == 'jev-backup'
    assert attributes['routing.decision.fallback_used'] is True
    assert attributes['routing.decision.default_used'] is False


async def test_a_failing_fallback_uses_the_default(span):
    _mock_typesafe(body={'error': 'busy'}, status=503, times=4)
    _mock_typesafe(body={'error': 'busy'}, status=503, times=4, model='jev-backup')

    model = await _router(fallback_model_id='jev-backup').select_model(
        [HumanMessage(content=USER_TEXT)]
    )

    assert model is MINI
    attributes = _attributes(span)
    assert attributes['routing.decision.fallback_used'] is True
    assert attributes['routing.decision.default_reason'] == 'error'


async def test_a_non_retriable_4xx_goes_to_the_fallback():
    primary = _mock_typesafe(body={'error': 'bad request'}, status=400)
    _mock_typesafe({'option_1': 0.6, 'option_2': 0.4}, model='jev-backup')

    model = await _router(fallback_model_id='jev-backup').select_model(
        [HumanMessage(content=USER_TEXT)]
    )

    assert model is GPT_4O
    # Not retried: one call only.
    assert primary.calls == 1


async def test_a_non_retriable_4xx_without_fallback_uses_the_default(span):
    _mock_typesafe(body={'error': 'unauthorized'}, status=401)

    model = await _router().select_model([HumanMessage(content=USER_TEXT)])

    assert model is MINI
    assert _attributes(span)['routing.decision.default_reason'] == 'error'


@pytest.mark.parametrize(
    'body',
    [
        pytest.param({'answers': {}}, id='missing answer'),
        pytest.param(_answer(), id='no choice'),
        pytest.param(_answer(choice='option_3'), id='option not offered'),
        pytest.param(_answer(choice='gpt-5'), id='model id instead of option'),
        pytest.param(_answer(choice=1), id='choice not a string'),
        pytest.param(
            _answer(choice={'option_1': 0.1, 'option_2': 0.9}),
            id='probabilities in choice',
        ),
        pytest.param(
            _answer(choice='option_2', confidence='high'),
            id='non-number confidence',
        ),
        pytest.param(_answer(choice='option_2', confidence=True), id='bool confidence'),
        pytest.param(['not', 'a', 'dict'], id='not an object'),
    ],
)
async def test_a_malformed_answer_uses_the_default_without_fallback(span, body):
    _mock_typesafe(body=body)
    fallback = _mock_typesafe({'option_1': 0.9, 'option_2': 0.1}, model='jev-backup')

    model = await _router(fallback_model_id='jev-backup').select_model(
        [HumanMessage(content=USER_TEXT)]
    )

    assert model is MINI
    assert not fallback.isdone()
    assert _attributes(span)['routing.decision.default_reason'] == 'unknown_option'


@pytest.mark.parametrize(
    'messages',
    [
        pytest.param([], id='no messages'),
        pytest.param([HumanMessage(content='')], id='empty human message'),
        pytest.param(
            [SystemMessage(content='be nice'), AIMessage(content='hello')],
            id='no human message',
        ),
    ],
)
async def test_no_text_uses_the_default_without_calling_typesafe(span, messages):
    model = await _router().select_model(messages)

    assert model is MINI
    attributes = _attributes(span)
    assert attributes['routing.decision.default_reason'] == 'no_text'
    assert 'routing.decision.state' not in attributes
    assert 'routing.decision.model_id' not in attributes


@pytest.mark.parametrize(
    ('confidence', 'expected'),
    [
        pytest.param(0.59, MINI, id='below'),
        pytest.param(0.6, GPT_5, id='equal passes'),
        pytest.param(0.61, GPT_5, id='above'),
    ],
)
async def test_min_confidence_boundaries(confidence, expected):
    # Jev's confidence, not the option's probability, is compared.
    _mock_typesafe(
        body=_choice_answer({'option_1': 0.1, 'option_2': 0.9}, confidence=confidence)
    )

    model = await _router(min_confidence=0.6).select_model(
        [HumanMessage(content=USER_TEXT)]
    )

    assert model is expected


async def test_an_answer_without_confidence_is_enough_without_min_confidence():
    _mock_typesafe(body=_answer(choice='option_2'))

    model = await _router().select_model([HumanMessage(content=USER_TEXT)])

    assert model is GPT_5


async def test_an_answer_without_confidence_fails_min_confidence(span):
    _mock_typesafe(body=_answer(choice='option_2'))

    model = await _router(min_confidence=0.5).select_model(
        [HumanMessage(content=USER_TEXT)]
    )

    assert model is MINI
    assert _attributes(span)['routing.decision.default_reason'] == 'unknown_option'


async def test_low_confidence_is_the_default_reason(span):
    _mock_typesafe({'option_1': 0.3, 'option_2': 0.4})

    await _router(min_confidence=0.5).select_model([HumanMessage(content=USER_TEXT)])

    attributes = _attributes(span)
    assert attributes['routing.decision.default_reason'] == 'low_confidence'
    assert attributes['routing.decision.chosen_model_id'] == 'mini'


async def test_history_last_sends_the_last_human_message():
    mock = _mock_typesafe({'option_1': 0.9, 'option_2': 0.1}, state='second')

    await _router().select_model(
        [
            SystemMessage(content='client system'),
            HumanMessage(content='first'),
            AIMessage(content='answer'),
            HumanMessage(content='second'),
            AIMessage(content='trailing'),
        ]
    )

    assert mock.isdone()


CONVERSATION = [
    SystemMessage(content='client system'),
    HumanMessage(content='first'),
    AIMessage(content='answer'),
    ToolMessage(content='tool output', tool_call_id='call_1'),
    HumanMessage(content='second'),
]


async def test_history_all_sends_human_and_ai_messages_by_default():
    mock = _mock_typesafe(
        {'option_1': 0.9, 'option_2': 0.1}, state='first\nanswer\nsecond'
    )

    await _router(history='all').select_model(CONVERSATION)

    assert mock.isdone()


async def test_history_all_filters_by_message_roles():
    mock = _mock_typesafe(
        {'option_1': 0.9, 'option_2': 0.1},
        state='client system\nfirst\ntool output\nsecond',
    )

    router = _router(history='all', message_roles=['user', 'system', 'tool'])
    await router.select_model(CONVERSATION)

    assert mock.isdone()


async def test_the_span_records_the_question_and_the_answer(span):
    _mock_typesafe({'option_1': 0.1, 'option_2': 0.85})

    await _router().select_model([HumanMessage(content=USER_TEXT)])

    attributes = _attributes(span)
    assert attributes['routing.decision.model_id'] == 'jev'
    assert attributes['routing.decision.fallback_used'] is False
    assert attributes['routing.decision.instructions'] == INSTRUCTIONS
    assert json.loads(attributes['routing.decision.options']) == {
        'option_1': {'model_id': 'gpt-4o', 'description': EMAILS},
        'option_2': {'model_id': 'gpt-5', 'description': CHINESE},
    }
    assert attributes['routing.decision.confidence'] == 0.85
    assert json.loads(attributes['routing.decision.probabilities']) == {
        'option_1': 0.1,
        'option_2': 0.85,
    }
    assert attributes['routing.decision.state'] == USER_TEXT
    assert attributes['routing.decision.chosen_model_id'] == 'gpt-5'
    assert attributes['routing.decision.default_used'] is False
    assert 'routing.decision.default_reason' not in attributes
