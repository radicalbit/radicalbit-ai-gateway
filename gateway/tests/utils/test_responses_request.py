import copy

import pytest

from tests.test_responses_native import OPENCODE_TURN

from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from radicalbit_ai_gateway.models.responses import ResponsesSettings
from radicalbit_ai_gateway.utils.exceptions import (
    GatewayBadRequest,
    GatewayInternalError,
)
from radicalbit_ai_gateway.utils.responses_request import (
    ResponsesRequest,
    apply_governance,
    cache_signature,
    last_user_text,
    references_stored_state,
)


def _body(**fields):
    return {
        'model': 'route',
        'instructions': 'You are opencode.',
        'input': copy.deepcopy(OPENCODE_TURN),
        **fields,
    }


class TestResponsesRequest:
    def test_texts_read_as_messages(self):
        messages = ResponsesRequest(_body()).messages()

        assert [type(m) for m in messages] == [
            SystemMessage,
            HumanMessage,
            AIMessage,
            ToolMessage,
            ToolMessage,
        ]
        assert [m.content for m in messages] == [
            'You are opencode.',
            'Implement the task',
            'I will read the files first.',
            'print(1)',
            'a.py',
        ]
        assert [m.tool_call_id for m in messages[3:]] == ['call_A', 'call_B']

    def test_string_input_is_a_user_message(self):
        messages = ResponsesRequest({'input': 'Hi'}).messages()

        assert messages == [HumanMessage(content='Hi')]

    def test_several_text_parts_read_as_one_message(self):
        body = {
            'input': [
                {
                    'role': 'user',
                    'content': [
                        {'type': 'input_text', 'text': 'Look'},
                        {'type': 'input_image', 'image_url': 'data:image/png;base64,x'},
                        {'type': 'input_text', 'text': 'here'},
                    ],
                }
            ]
        }

        (message,) = ResponsesRequest(body).messages()

        assert message.content == [
            {'type': 'text', 'text': 'Look'},
            {'type': 'text', 'text': 'here'},
        ]

    def test_changed_texts_are_written_back_and_nothing_else(self):
        body = _body()
        request = ResponsesRequest(body)
        messages = [
            m.model_copy(update={'content': m.content.upper()})
            for m in request.messages()
        ]

        request.write_back(messages)

        assert request.body['instructions'] == 'YOU ARE OPENCODE.'
        items = request.body['input']
        assert items[0]['content'][0]['text'] == 'IMPLEMENT THE TASK'
        assert items[2]['content'][0]['text'] == 'I WILL READ THE FILES FIRST.'
        assert items[5]['output'] == 'PRINT(1)'
        # Items without text, and the client's own body, are untouched
        assert items[1] == OPENCODE_TURN[1]
        assert items[3:5] == OPENCODE_TURN[3:5]
        assert body == _body()

    def test_texts_of_several_parts_are_written_back_in_place(self):
        body = {
            'input': [
                {
                    'role': 'user',
                    'content': [
                        {'type': 'input_text', 'text': 'a'},
                        {'type': 'input_image', 'image_url': 'x'},
                        {'type': 'input_text', 'text': 'b'},
                    ],
                }
            ]
        }
        request = ResponsesRequest(body)

        request.write_back(
            [
                HumanMessage(
                    content=[
                        {'type': 'text', 'text': 'A'},
                        {'type': 'text', 'text': 'B'},
                    ]
                )
            ]
        )

        assert request.body['input'][0]['content'] == [
            {'type': 'input_text', 'text': 'A'},
            {'type': 'input_image', 'image_url': 'x'},
            {'type': 'input_text', 'text': 'B'},
        ]

    def test_a_changed_structure_is_refused(self):
        request = ResponsesRequest(_body())

        with pytest.raises(GatewayInternalError):
            request.write_back(request.messages()[1:])

    def test_configured_prompt_goes_first(self):
        request = ResponsesRequest({'input': 'Hi'})

        request.insert_prompt(SystemMessage(content='Be brief'), 'developer')

        assert request.body['input'] == [
            {'type': 'message', 'role': 'developer', 'content': 'Be brief'},
            {'type': 'message', 'role': 'user', 'content': 'Hi'},
        ]


class TestGovernance:
    def test_no_settings_change_nothing(self):
        body = _body(tools=[{'type': 'web_search'}], previous_response_id='resp_0')

        apply_governance(body, None, 'route')

        assert body == _body(
            tools=[{'type': 'web_search'}], previous_response_id='resp_0'
        )

    def test_hosted_tool_not_allowed_is_refused_by_name(self):
        settings = ResponsesSettings(allowed_hosted_tools=['file_search'])
        body = _body(tools=[{'type': 'file_search'}, {'type': 'web_search'}])

        with pytest.raises(GatewayBadRequest, match='web_search'):
            apply_governance(body, settings, 'route')

    def test_client_tools_are_always_allowed(self):
        settings = ResponsesSettings(allowed_hosted_tools=[])
        tools = [{'type': 'function', 'name': 'read'}, {'type': 'custom', 'name': 'x'}]

        apply_governance(_body(tools=tools), settings, 'route')

    def test_forced_store_false(self):
        settings = ResponsesSettings(force_store_false=True)
        body = _body(store=True)
        body['input'].append({'type': 'reasoning', 'id': 'rs_stored', 'summary': []})

        apply_governance(body, settings, 'route')

        assert body['store'] is False
        # Reasoning only the provider's storage could resolve is dropped,
        # encrypted reasoning is kept
        reasoning = [item for item in body['input'] if item['type'] == 'reasoning']
        assert reasoning == [OPENCODE_TURN[1]]

    @pytest.mark.parametrize(
        'fields',
        [
            {'previous_response_id': 'resp_0'},
            {'conversation': 'conv_0'},
            {'input': [{'type': 'item_reference', 'id': 'msg_0'}]},
        ],
    )
    def test_stored_state_is_refused_when_store_is_forced_false(self, fields):
        settings = ResponsesSettings(force_store_false=True)

        with pytest.raises(GatewayBadRequest, match='does not store responses'):
            apply_governance(_body(**fields), settings, 'route')

        assert references_stored_state(_body(**fields))

    def test_full_context_needs_no_stored_state(self):
        assert not references_stored_state(_body(store=True))


class TestCache:
    def test_signature_starts_at_the_last_user_message(self):
        body = _body(stream=True, temperature=0.1)
        body['input'] = [
            {'role': 'user', 'content': 'first'},
            {'role': 'assistant', 'content': 'answer'},
            *body['input'],
        ]

        signature = cache_signature(body)

        assert signature['input'] == OPENCODE_TURN
        assert signature['params'] == {'model': 'route', 'temperature': 0.1}
        # Streaming does not change the reply
        assert signature == cache_signature({**body, 'stream': False})

    def test_no_user_message_no_signature(self):
        assert cache_signature({'input': [OPENCODE_TURN[2]]}) is None

    def test_last_user_text(self):
        assert last_user_text(_body()) == 'Implement the task'
        assert last_user_text({'input': 'Hi'}) == 'Hi'
