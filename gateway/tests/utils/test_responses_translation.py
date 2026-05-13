"""Unit tests for the Responses API translation utilities."""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from openai.types.chat.chat_completion import ChatCompletion, Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)
from openai.types.completion_usage import CompletionUsage
import pytest

from radicalbit_ai_gateway.utils.exceptions import GatewayBadRequest
from radicalbit_ai_gateway.utils.responses_translation import (
    chat_completion_to_response,
    input_to_langchain_messages,
    responses_tools_to_chat_completions_tools,
    translate_tool_choice,
)

# ── input_to_langchain_messages ────────────────────────────────────────────────


class TestInputToLangchainMessages:
    def test_string_input(self):
        msgs = input_to_langchain_messages('Hello')
        assert msgs == [HumanMessage(content='Hello')]

    def test_string_input_with_instructions(self):
        msgs = input_to_langchain_messages('Hello', instructions='Be brief.')
        assert msgs == [
            SystemMessage(content='Be brief.'),
            HumanMessage(content='Hello'),
        ]

    def test_list_user_message(self):
        msgs = input_to_langchain_messages(
            [
                {'role': 'user', 'content': 'Hi', 'type': 'message'},
            ]
        )
        assert msgs == [HumanMessage(content='Hi')]

    def test_list_system_message(self):
        msgs = input_to_langchain_messages(
            [
                {'role': 'system', 'content': 'You are helpful.', 'type': 'message'},
                {'role': 'user', 'content': 'Tell me something.', 'type': 'message'},
            ]
        )
        assert msgs == [
            SystemMessage(content='You are helpful.'),
            HumanMessage(content='Tell me something.'),
        ]

    def test_developer_role_maps_to_system(self):
        msgs = input_to_langchain_messages(
            [
                {
                    'role': 'developer',
                    'content': 'You are a code assistant.',
                    'type': 'message',
                },
            ]
        )
        assert msgs == [SystemMessage(content='You are a code assistant.')]

    def test_assistant_message(self):
        msgs = input_to_langchain_messages(
            [
                {'role': 'assistant', 'content': 'Sure!', 'type': 'message'},
            ]
        )
        assert msgs == [AIMessage(content='Sure!')]

    def test_function_call_output(self):
        msgs = input_to_langchain_messages(
            [
                {
                    'type': 'function_call_output',
                    'call_id': 'call_abc123',
                    'output': '{"result": 42}',
                },
            ]
        )
        assert len(msgs) == 1
        assert isinstance(msgs[0], ToolMessage)
        assert msgs[0].tool_call_id == 'call_abc123'
        assert msgs[0].content == '{"result": 42}'

    def test_function_call_output_missing_call_id_raises(self):
        with pytest.raises(GatewayBadRequest, match='call_id'):
            input_to_langchain_messages(
                [
                    {'type': 'function_call_output', 'output': 'result'},
                ]
            )

    def test_instructions_prepended_before_list_items(self):
        msgs = input_to_langchain_messages(
            [{'role': 'user', 'content': 'Hi', 'type': 'message'}],
            instructions='Be concise.',
        )
        assert msgs == [
            SystemMessage(content='Be concise.'),
            HumanMessage(content='Hi'),
        ]

    def test_multipart_content_text(self):
        msgs = input_to_langchain_messages(
            [
                {
                    'role': 'user',
                    'type': 'message',
                    'content': [{'type': 'input_text', 'text': 'What is this?'}],
                }
            ]
        )
        assert len(msgs) == 1
        assert isinstance(msgs[0], HumanMessage)

    def test_multipart_content_image_url(self):
        msgs = input_to_langchain_messages(
            [
                {
                    'role': 'user',
                    'type': 'message',
                    'content': [
                        {'type': 'input_text', 'text': 'Describe this image'},
                        {
                            'type': 'input_image',
                            'image_url': 'https://example.com/img.jpg',
                            'detail': 'auto',
                        },
                    ],
                }
            ]
        )
        assert len(msgs) == 1
        assert isinstance(msgs[0], HumanMessage)
        # The content should be a list with 2 parts
        assert isinstance(msgs[0].content, list)
        assert len(msgs[0].content) == 2

    def test_unknown_item_types_are_skipped(self):
        msgs = input_to_langchain_messages(
            [
                {'type': 'computer_call_output', 'call_id': 'x', 'output': {}},
                {'role': 'user', 'content': 'Hello', 'type': 'message'},
            ]
        )
        # computer_call_output is silently skipped
        assert msgs == [HumanMessage(content='Hello')]

    def test_invalid_input_type_raises(self):
        with pytest.raises(GatewayBadRequest):
            input_to_langchain_messages(12345)  # type: ignore[arg-type]


# ── responses_tools_to_chat_completions_tools ─────────────────────────────────


class TestResponsesToolsToChatCompletionsTools:
    def test_empty_tools(self):
        assert responses_tools_to_chat_completions_tools(None) == []
        assert responses_tools_to_chat_completions_tools([]) == []

    def test_function_tool_translated(self):
        tools = [
            {
                'type': 'function',
                'function': {
                    'name': 'get_weather',
                    'description': 'Get current weather',
                    'parameters': {
                        'type': 'object',
                        'properties': {'location': {'type': 'string'}},
                    },
                },
            }
        ]
        result = responses_tools_to_chat_completions_tools(tools)
        assert len(result) == 1
        assert result[0]['type'] == 'function'
        assert result[0]['function']['name'] == 'get_weather'
        assert result[0]['function']['description'] == 'Get current weather'

    def test_builtin_tools_skipped(self):
        tools = [
            {'type': 'file_search'},
            {'type': 'web_search_preview'},
            {'type': 'code_interpreter'},
            {'type': 'computer_use'},
            {'type': 'function', 'function': {'name': 'my_func'}},
        ]
        result = responses_tools_to_chat_completions_tools(tools)
        # Only the function tool should remain
        assert len(result) == 1
        assert result[0]['function']['name'] == 'my_func'

    def test_mixed_tools(self):
        tools = [
            {'type': 'function', 'function': {'name': 'func_a'}},
            {'type': 'function', 'function': {'name': 'func_b', 'description': 'B'}},
        ]
        result = responses_tools_to_chat_completions_tools(tools)
        assert len(result) == 2
        names = [r['function']['name'] for r in result]
        assert 'func_a' in names
        assert 'func_b' in names


# ── translate_tool_choice ──────────────────────────────────────────────────────


class TestTranslateToolChoice:
    def test_none_returns_auto(self):
        assert translate_tool_choice(None) == 'auto'

    def test_string_passthrough(self):
        assert translate_tool_choice('none') == 'none'
        assert translate_tool_choice('auto') == 'auto'
        assert translate_tool_choice('required') == 'required'

    def test_function_object(self):
        result = translate_tool_choice(
            {'type': 'function', 'function': {'name': 'my_tool'}}
        )
        assert result == {'type': 'function', 'function': {'name': 'my_tool'}}

    def test_unknown_dict_falls_back_to_auto(self):
        result = translate_tool_choice({'type': 'some_unknown_type'})
        assert result == 'auto'


# ── chat_completion_to_response ────────────────────────────────────────────────


class TestChatCompletionToResponse:
    def _make_completion(self, content: str, with_usage: bool = True) -> ChatCompletion:
        return ChatCompletion(
            id='chatcmpl-test',
            object='chat.completion',
            created=1700000000,
            model='test-model',
            choices=[
                Choice(
                    index=0,
                    message=ChatCompletionMessage(role='assistant', content=content),
                    finish_reason='stop',
                )
            ],
            usage=CompletionUsage(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            )
            if with_usage
            else None,
        )

    def test_basic_text_response(self):
        completion = self._make_completion('Hello there!')
        response = chat_completion_to_response(completion, route_name='my-route')

        assert response.id == 'chatcmpl-test'
        assert response.object == 'response'
        assert response.model == 'my-route'
        assert response.status == 'completed'
        assert response.created_at == 1700000000.0
        assert len(response.output) == 1

        msg = response.output[0]
        assert msg.type == 'message'
        assert msg.role == 'assistant'
        assert msg.status == 'completed'
        assert len(msg.content) == 1
        assert msg.content[0].type == 'output_text'
        assert msg.content[0].text == 'Hello there!'

    def test_usage_translated(self):
        completion = self._make_completion('Hi', with_usage=True)
        response = chat_completion_to_response(completion, route_name='r')

        assert response.usage is not None
        assert response.usage.input_tokens == 10
        assert response.usage.output_tokens == 5
        assert response.usage.total_tokens == 15

    def test_no_usage_produces_none(self):
        completion = self._make_completion('Hi', with_usage=False)
        response = chat_completion_to_response(completion, route_name='r')
        assert response.usage is None

    def test_tool_call_response(self):
        completion = ChatCompletion(
            id='chatcmpl-tools',
            object='chat.completion',
            created=1700000000,
            model='test-model',
            choices=[
                Choice(
                    index=0,
                    message=ChatCompletionMessage(
                        role='assistant',
                        content=None,
                        tool_calls=[
                            ChatCompletionMessageToolCall(
                                id='call_abc',
                                type='function',
                                function=Function(
                                    name='get_weather',
                                    arguments='{"location": "Paris"}',
                                ),
                            )
                        ],
                    ),
                    finish_reason='tool_calls',
                )
            ],
            usage=None,
        )
        response = chat_completion_to_response(completion, route_name='my-route')

        assert len(response.output) == 1
        tool_call = response.output[0]
        assert tool_call.type == 'function_call'
        assert tool_call.name == 'get_weather'
        assert tool_call.arguments == '{"location": "Paris"}'
        assert tool_call.call_id == 'call_abc'

    def test_empty_choices_produces_empty_output(self):
        completion = ChatCompletion(
            id='chatcmpl-empty',
            object='chat.completion',
            created=1700000000,
            model='test-model',
            choices=[],
            usage=None,
        )
        response = chat_completion_to_response(completion, route_name='r')
        assert response.output == []
