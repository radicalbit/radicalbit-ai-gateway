"""Tests for adapting a Responses ``input`` to the model about to receive it.

A client that keeps its own history replays items other providers produced;
each model gets them reduced to what it accepts.
"""

import copy

from httpx_aiohttp import HttpxAiohttpClient
import pytest

from tests.responses.test_native import OPENCODE_TURN, FakeChatModel

from radicalbit_ai_gateway.llm.factory import init_chat_model
from radicalbit_ai_gateway.llm.providers.deepseek import REASONING_PLACEHOLDER

USER = {
    'type': 'message',
    'role': 'user',
    'content': [{'type': 'input_text', 'text': 'Add 17 and 25'}],
}

OPENAI_REASONING = {
    'type': 'reasoning',
    'id': 'rs_0885e027',
    'summary': [],
    'content': [],
    'encrypted_content': 'gAAAAABq5FSq',
}
OPENAI_CALL = {
    'type': 'function_call',
    'id': 'fc_0885e027',
    'call_id': 'call_X1vh94',
    'name': 'add',
    'arguments': '{"a":17,"b":25}',
    'status': 'completed',
}
OPENAI_MESSAGE = {
    'type': 'message',
    'id': 'msg_0885e027',
    'role': 'assistant',
    'phase': 'final_answer',
    'content': [{'type': 'output_text', 'text': '42', 'annotations': []}],
}

DEEPSEEK_REASONING = {
    'type': 'reasoning',
    'id': 'ce06e802-50fe-452d-8b69-b36ce889fb67',
    'status': 'completed',
    'summary': [],
    'content': [{'type': 'reasoning_text', 'text': 'The user asked to add.'}],
    'encrypted_content': '87fd24ba-194b-4029-9ef8-ec63c5d4ef99-0',
}
DEEPSEEK_CALL = {
    'type': 'function_call',
    'id': 'e4868a76-61f5-46e3-8c7f-a57487063529',
    'status': 'completed',
    'call_id': 'call_00_Yno9gEtLiOMkWNVJ8p162087',
    'name': 'add',
    'arguments': '{"a": 2, "b": 3}',
}
DEEPSEEK_MESSAGE = {
    'type': 'message',
    'id': '32c96251-2bc3-4fbf-ae86-e6907afe666d',
    'status': 'completed',
    'role': 'assistant',
    'content': [{'type': 'output_text', 'text': '5', 'annotations': []}],
}
CALL_OUTPUT = {
    'type': 'function_call_output',
    'call_id': 'call_00_Yno9gEtLiOMkWNVJ8p162087',
    'output': '5',
}
# OpenRouter's items: OpenAI-like ids, plus fields OpenAI rejects on reasoning.
OPENROUTER_LUNA_REASONING = {
    'type': 'reasoning',
    'id': 'rs_0a6e36574c2ae183',
    'status': 'completed',
    'format': 'openai-responses-v1',
    'summary': [],
    'encrypted_content': 'gAAAAABq5Fxx',
}
OPENROUTER_DEEPSEEK_REASONING = {
    'type': 'reasoning',
    'id': 'rs_tmp_qogh7s7',
    'status': 'completed',
    'format': 'unknown',
    'summary': [],
    'content': [{'type': 'reasoning_text', 'text': 'The user wants to add.'}],
}
OPENROUTER_HAIKU_REASONING = {
    'type': 'reasoning',
    'id': 'rs_tmp_0qnndwt',
    'status': 'completed',
    'format': 'anthropic-claude-v1',
    'signature': 'EqQBCkYI',
    'summary': [],
    'content': [{'type': 'reasoning_text', 'text': 'Adding.'}],
}
OPENROUTER_CALL = {
    'type': 'function_call',
    'id': 'fc_tmp_xa64ghzdhaj',
    'status': 'completed',
    'call_id': 'call_8c8j56YeoQi7KVOx0JRsK2yV',
    'name': 'add',
    'arguments': '{"a":17,"b":25}',
}
OPENROUTER_MESSAGE = {
    'type': 'message',
    'id': 'msg_tmp_4kq2',
    'status': 'completed',
    'role': 'assistant',
    'content': [{'type': 'output_text', 'text': '42', 'annotations': []}],
}
PLACEHOLDER = {
    'type': 'reasoning',
    'summary': [],
    'content': [{'type': 'reasoning_text', 'text': REASONING_PLACEHOLDER}],
}


def _model(name: str):
    return init_chat_model(name, api_key='sk', http_async_client=HttpxAiohttpClient())


def _without(item: dict, *keys: str) -> dict:
    return {k: v for k, v in item.items() if k not in keys}


def _assert_adapted(model, items: list, expected: list) -> None:
    """Assert the adapted input is ``expected`` and the items are not mutated."""
    before = copy.deepcopy(items)

    assert model.adapt_responses_input(items) == expected
    assert items == before


def _summarised(*texts: str) -> dict:
    return {
        **OPENAI_REASONING,
        'summary': [{'type': 'summary_text', 'text': t} for t in texts],
    }


def _reasoning_text(text: str) -> dict:
    return {
        'type': 'reasoning',
        'summary': [],
        'content': [{'type': 'reasoning_text', 'text': text}],
    }


_SECOND_CALL = {**OPENAI_CALL, 'id': 'fc_2', 'call_id': 'call_2'}
_SECOND_OUTPUT = {**CALL_OUTPUT, 'call_id': 'call_2'}


def _same(items: list) -> tuple[list, list]:
    return items, items


@pytest.mark.parametrize(
    ('items', 'expected'),
    [
        pytest.param(*_same([OPENAI_REASONING]), id='own-reasoning-kept'),
        pytest.param(
            *_same([_without(OPENAI_REASONING, 'encrypted_content')]),
            id='own-reasoning-without-blob-kept',
        ),
        pytest.param(
            *_same([_without(OPENAI_REASONING, 'id')]), id='own-blob-without-id-kept'
        ),
        pytest.param(
            [USER, DEEPSEEK_REASONING], [USER], id='deepseek-reasoning-dropped'
        ),
        pytest.param(
            [DEEPSEEK_CALL],
            [_without(DEEPSEEK_CALL, 'id', 'status')],
            id='foreign-call-loses-id-status',
        ),
        pytest.param(
            [DEEPSEEK_MESSAGE],
            [_without(DEEPSEEK_MESSAGE, 'id', 'status')],
            id='foreign-message-loses-id-status',
        ),
        pytest.param(
            *_same([USER, OPENAI_REASONING, OPENAI_CALL, CALL_OUTPUT, OPENAI_MESSAGE]),
            id='own-items-unchanged',
        ),
        pytest.param(*_same(OPENCODE_TURN), id='openai-only-history-unchanged'),
        pytest.param(*_same(['raw', USER]), id='non-dicts-unchanged'),
        pytest.param(
            [USER, DEEPSEEK_REASONING, DEEPSEEK_CALL, CALL_OUTPUT, DEEPSEEK_MESSAGE],
            [
                USER,
                _without(DEEPSEEK_CALL, 'id', 'status'),
                CALL_OUTPUT,
                _without(DEEPSEEK_MESSAGE, 'id', 'status'),
            ],
            id='deepseek-turn',
        ),
        # OpenAI -> DeepSeek, which calls a tool, then back to OpenAI.
        pytest.param(
            [
                USER,
                OPENAI_REASONING,
                OPENAI_MESSAGE,
                USER,
                DEEPSEEK_REASONING,
                DEEPSEEK_CALL,
                CALL_OUTPUT,
            ],
            [
                USER,
                OPENAI_REASONING,
                OPENAI_MESSAGE,
                USER,
                _without(DEEPSEEK_CALL, 'id', 'status'),
                CALL_OUTPUT,
            ],
            id='switch-mid-tool-loop-keeps-visible-history',
        ),
        pytest.param(
            [
                USER,
                OPENROUTER_LUNA_REASONING,
                OPENROUTER_DEEPSEEK_REASONING,
                OPENROUTER_HAIKU_REASONING,
            ],
            [USER],
            id='openrouter-reasoning-dropped-even-with-openai-blob',
        ),
        pytest.param(
            *_same([USER, OPENROUTER_CALL, CALL_OUTPUT, OPENROUTER_MESSAGE]),
            id='openrouter-calls-and-messages-unchanged',
        ),
    ],
)
def test_openai_target(items, expected):
    _assert_adapted(_model('openai:gpt-6-luna'), items, expected)


OPENROUTER = 'https://openrouter.ai/api/v1'


@pytest.mark.parametrize(
    ('items', 'expected'),
    [
        pytest.param(
            [
                USER,
                OPENAI_REASONING,
                DEEPSEEK_REASONING,
                OPENROUTER_LUNA_REASONING,
                OPENROUTER_HAIKU_REASONING,
            ],
            [USER],
            id='all-reasoning-dropped-its-own-too',
        ),
        pytest.param(
            [OPENAI_CALL, DEEPSEEK_CALL, OPENROUTER_CALL, OPENROUTER_MESSAGE],
            [
                _without(item, 'id', 'status')
                for item in [
                    OPENAI_CALL,
                    DEEPSEEK_CALL,
                    OPENROUTER_CALL,
                    OPENROUTER_MESSAGE,
                ]
            ],
            id='every-item-loses-id-and-status',
        ),
        pytest.param(
            *_same(['raw', USER, CALL_OUTPUT]), id='items-without-ids-and-non-dicts'
        ),
    ],
)
def test_compatible_target(items, expected):
    """An ``openai/`` model with a ``base_url``: any OpenAI-compatible endpoint."""
    model = init_chat_model(
        'openai:openai/gpt-6-luna',
        api_key='sk',
        base_url=OPENROUTER,
        http_async_client=HttpxAiohttpClient(),
    )

    _assert_adapted(model, items, expected)


@pytest.mark.parametrize(
    ('items', 'expected'),
    [
        pytest.param(*_same([DEEPSEEK_REASONING]), id='own-reasoning-kept'),
        pytest.param(
            [USER, OPENAI_REASONING], [USER], id='openai-blob-without-summary-dropped'
        ),
        pytest.param(
            [_summarised('Adding two numbers.', 'Calling add.')],
            [_reasoning_text('Adding two numbers.\n\nCalling add.')],
            id='openai-blob-with-summary-becomes-reasoning-text',
        ),
        pytest.param(
            *_same([USER, OPENAI_CALL, CALL_OUTPUT, OPENAI_MESSAGE, USER]),
            id='openai-messages-and-calls-unchanged',
        ),
        pytest.param(
            [USER, OPENAI_REASONING, OPENAI_CALL, CALL_OUTPUT],
            [USER, PLACEHOLDER, OPENAI_CALL, CALL_OUTPUT],
            id='current-call-without-reasoning-gets-placeholder',
        ),
        pytest.param(
            [
                USER,
                OPENAI_CALL,
                _SECOND_CALL,
                CALL_OUTPUT,
                _SECOND_OUTPUT,
                OPENAI_CALL,
                CALL_OUTPUT,
            ],
            [
                USER,
                PLACEHOLDER,
                OPENAI_CALL,
                _SECOND_CALL,
                CALL_OUTPUT,
                _SECOND_OUTPUT,
                PLACEHOLDER,
                OPENAI_CALL,
                CALL_OUTPUT,
            ],
            id='each-round-of-current-turn-gets-one-placeholder',
        ),
        pytest.param(
            *_same([USER, DEEPSEEK_REASONING, DEEPSEEK_CALL, CALL_OUTPUT]),
            id='current-call-after-own-reasoning-no-placeholder',
        ),
        pytest.param(
            [USER, _summarised('Calling add.'), OPENAI_CALL, CALL_OUTPUT],
            [USER, _reasoning_text('Calling add.'), OPENAI_CALL, CALL_OUTPUT],
            id='current-call-after-summary-no-placeholder',
        ),
        pytest.param(
            [USER, OPENAI_REASONING, OPENAI_CALL, OPENAI_MESSAGE],
            [USER, PLACEHOLDER, OPENAI_CALL, OPENAI_MESSAGE],
            id='openai-turn-with-final-message',
        ),
    ],
)
def test_deepseek_target(items, expected):
    _assert_adapted(_model('deepseek:deepseek-flash'), items, expected)


def test_base_class_drops_reasoning_and_keeps_the_rest():
    items = [
        USER,
        OPENAI_REASONING,
        OPENAI_CALL,
        DEEPSEEK_REASONING,
        DEEPSEEK_MESSAGE,
        'raw',
    ]

    _assert_adapted(
        FakeChatModel(), items, [USER, OPENAI_CALL, DEEPSEEK_MESSAGE, 'raw']
    )
