"""Tests for adapting a Responses ``input`` to the model about to receive it.

A client that keeps its own history replays items other providers produced;
each model gets them reduced to what it accepts.
"""

import copy

from httpx_aiohttp import HttpxAiohttpClient

from tests.test_responses_native import OPENCODE_TURN, FakeChatModel

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


class TestOpenAITarget:
    def setup_method(self):
        self.model = _model('openai:gpt-6-luna')

    def test_own_reasoning_is_kept(self):
        assert self.model.adapt_responses_input([OPENAI_REASONING]) == [
            OPENAI_REASONING
        ]

    def test_own_reasoning_without_a_blob_is_kept(self):
        stored = _without(OPENAI_REASONING, 'encrypted_content')

        assert self.model.adapt_responses_input([stored]) == [stored]

    def test_own_blob_without_an_id_is_kept(self):
        blob_only = _without(OPENAI_REASONING, 'id')

        assert self.model.adapt_responses_input([blob_only]) == [blob_only]

    def test_deepseek_reasoning_is_dropped(self):
        assert self.model.adapt_responses_input([USER, DEEPSEEK_REASONING]) == [USER]

    def test_foreign_function_call_loses_id_and_status(self):
        assert self.model.adapt_responses_input([DEEPSEEK_CALL]) == [
            _without(DEEPSEEK_CALL, 'id', 'status')
        ]

    def test_foreign_message_loses_id_and_status(self):
        assert self.model.adapt_responses_input([DEEPSEEK_MESSAGE]) == [
            _without(DEEPSEEK_MESSAGE, 'id', 'status')
        ]

    def test_own_items_are_unchanged(self):
        items = [USER, OPENAI_REASONING, OPENAI_CALL, CALL_OUTPUT, OPENAI_MESSAGE]

        assert self.model.adapt_responses_input(items) == items

    def test_an_openai_only_history_is_unchanged(self):
        assert self.model.adapt_responses_input(OPENCODE_TURN) == OPENCODE_TURN

    def test_non_dict_items_are_unchanged(self):
        assert self.model.adapt_responses_input(['raw', USER]) == ['raw', USER]

    def test_the_callers_items_are_not_mutated(self):
        items = [USER, DEEPSEEK_REASONING, DEEPSEEK_CALL, CALL_OUTPUT, DEEPSEEK_MESSAGE]
        before = copy.deepcopy(items)

        self.model.adapt_responses_input(items)

        assert items == before

    def test_a_switch_mid_tool_loop_keeps_the_visible_history(self):
        # OpenAI → DeepSeek, which calls a tool, then back to OpenAI.
        items = [
            USER,
            OPENAI_REASONING,
            OPENAI_MESSAGE,
            USER,
            DEEPSEEK_REASONING,
            DEEPSEEK_CALL,
            CALL_OUTPUT,
        ]

        assert self.model.adapt_responses_input(items) == [
            USER,
            OPENAI_REASONING,
            OPENAI_MESSAGE,
            USER,
            _without(DEEPSEEK_CALL, 'id', 'status'),
            CALL_OUTPUT,
        ]

    def test_openrouter_reasoning_is_dropped_even_with_an_openai_blob(self):
        items = [
            USER,
            OPENROUTER_LUNA_REASONING,
            OPENROUTER_DEEPSEEK_REASONING,
            OPENROUTER_HAIKU_REASONING,
        ]

        assert self.model.adapt_responses_input(items) == [USER]

    def test_openrouter_calls_and_messages_are_unchanged(self):
        items = [USER, OPENROUTER_CALL, CALL_OUTPUT, OPENROUTER_MESSAGE]

        assert self.model.adapt_responses_input(items) == items


def _compatible(base_url: str):
    return init_chat_model(
        'openai:openai/gpt-6-luna',
        api_key='sk',
        base_url=base_url,
        http_async_client=HttpxAiohttpClient(),
    )


class TestOpenRouterTarget:
    def setup_method(self):
        self.model = _compatible('https://openrouter.ai/api/v1')

    def test_its_own_reasoning_is_kept_whatever_model_produced_it(self):
        items = [
            USER,
            OPENROUTER_LUNA_REASONING,
            OPENROUTER_DEEPSEEK_REASONING,
            OPENROUTER_HAIKU_REASONING,
            OPENROUTER_CALL,
            CALL_OUTPUT,
        ]

        assert self.model.adapt_responses_input(items) == items

    def test_other_providers_reasoning_is_dropped(self):
        items = [USER, OPENAI_REASONING, DEEPSEEK_REASONING, OPENROUTER_MESSAGE]

        assert self.model.adapt_responses_input(items) == [USER, OPENROUTER_MESSAGE]

    def test_foreign_ids_are_removed_as_for_openai(self):
        assert self.model.adapt_responses_input([DEEPSEEK_CALL]) == [
            _without(DEEPSEEK_CALL, 'id', 'status')
        ]


class TestOtherCompatibleTarget:
    def test_openai_rules_without_the_check_on_extra_fields(self):
        model = _compatible('http://vllm:8000/v1')
        items = [USER, OPENROUTER_LUNA_REASONING, DEEPSEEK_REASONING, OPENROUTER_CALL]

        assert model.adapt_responses_input(items) == [
            USER,
            OPENROUTER_LUNA_REASONING,
            OPENROUTER_CALL,
        ]


class TestDeepSeekTarget:
    def setup_method(self):
        self.model = _model('deepseek:deepseek-flash')

    def test_own_reasoning_is_kept(self):
        assert self.model.adapt_responses_input([DEEPSEEK_REASONING]) == [
            DEEPSEEK_REASONING
        ]

    def test_openai_blob_without_summary_is_dropped(self):
        assert self.model.adapt_responses_input([USER, OPENAI_REASONING]) == [USER]

    def test_openai_blob_with_summary_becomes_reasoning_text(self):
        summarised = {
            **OPENAI_REASONING,
            'summary': [
                {'type': 'summary_text', 'text': 'Adding two numbers.'},
                {'type': 'summary_text', 'text': 'Calling add.'},
            ],
        }

        assert self.model.adapt_responses_input([summarised]) == [
            {
                'type': 'reasoning',
                'summary': [],
                'content': [
                    {
                        'type': 'reasoning_text',
                        'text': 'Adding two numbers.\n\nCalling add.',
                    }
                ],
            }
        ]

    def test_openai_messages_and_calls_are_unchanged(self):
        items = [USER, OPENAI_CALL, CALL_OUTPUT, OPENAI_MESSAGE, USER]

        assert self.model.adapt_responses_input(items) == items

    def test_current_call_without_reasoning_gets_a_placeholder(self):
        items = [USER, OPENAI_REASONING, OPENAI_CALL, CALL_OUTPUT]

        assert self.model.adapt_responses_input(items) == [
            USER,
            PLACEHOLDER,
            OPENAI_CALL,
            CALL_OUTPUT,
        ]

    def test_each_round_of_the_current_turn_gets_one_placeholder(self):
        second_call = {**OPENAI_CALL, 'id': 'fc_2', 'call_id': 'call_2'}
        second_output = {**CALL_OUTPUT, 'call_id': 'call_2'}
        items = [USER, OPENAI_CALL, second_call, CALL_OUTPUT, second_output]
        items += [OPENAI_CALL, CALL_OUTPUT]

        assert self.model.adapt_responses_input(items) == [
            USER,
            PLACEHOLDER,
            OPENAI_CALL,
            second_call,
            CALL_OUTPUT,
            second_output,
            PLACEHOLDER,
            OPENAI_CALL,
            CALL_OUTPUT,
        ]

    def test_current_call_after_reasoning_gets_no_placeholder(self):
        summarised = {
            **OPENAI_REASONING,
            'summary': [{'type': 'summary_text', 'text': 'Calling add.'}],
        }
        own = [USER, DEEPSEEK_REASONING, DEEPSEEK_CALL, CALL_OUTPUT]

        assert self.model.adapt_responses_input(own) == own
        assert PLACEHOLDER not in self.model.adapt_responses_input(
            [USER, summarised, OPENAI_CALL, CALL_OUTPUT]
        )

    def test_the_callers_items_are_not_mutated(self):
        items = [USER, OPENAI_REASONING, OPENAI_CALL, OPENAI_MESSAGE]
        before = copy.deepcopy(items)

        self.model.adapt_responses_input(items)

        assert items == before


class TestBaseClass:
    def test_reasoning_is_dropped_and_the_rest_unchanged(self):
        items = [
            USER,
            OPENAI_REASONING,
            OPENAI_CALL,
            DEEPSEEK_REASONING,
            DEEPSEEK_MESSAGE,
            'raw',
        ]

        assert FakeChatModel().adapt_responses_input(items) == [
            USER,
            OPENAI_CALL,
            DEEPSEEK_MESSAGE,
            'raw',
        ]
