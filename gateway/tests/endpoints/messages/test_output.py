from anthropic.types import Message
import pytest

from tests.common.gateway_harness import build_routes
from tests.common.scope import scope_of

from radicalbit_ai_gateway.endpoints.messages.guardrails import (
    MessagesReply,
    screen_output,
)
from radicalbit_ai_gateway.endpoints.messages.output import (
    MessagesOutput,
    gateway_message,
    with_text,
)
from radicalbit_ai_gateway.guardrails.guardrails import GuardrailFlags
from radicalbit_ai_gateway.llm.messages import AIMessage
from radicalbit_ai_gateway.utils.exceptions import GatewayInternalError

THINKING = {'type': 'thinking', 'thinking': 'Let me see.', 'signature': 'sig=='}
TOOL_USE = {
    'type': 'tool_use',
    'id': 'toolu_1',
    'name': 'read',
    'input': {'path': 'a.py'},
}
USAGE = {
    'input_tokens': 21,
    'output_tokens': 7,
    'cache_creation_input_tokens': 3,
    'cache_read_input_tokens': 5,
}


def _text(text: str, **fields) -> dict:
    return {'type': 'text', 'text': text, **fields}


def _message(content: list, **fields) -> dict:
    return {
        'id': 'msg_provider_1',
        'type': 'message',
        'role': 'assistant',
        'model': 'claude-sonnet-4-5',
        'content': content,
        'stop_reason': 'end_turn',
        'stop_sequence': None,
        'usage': USAGE,
        **fields,
    }


class TestMessagesOutput:
    def test_the_only_text_block_reads_as_one_message(self):
        output = MessagesOutput(_message([THINKING, _text('Hello'), TOOL_USE]))

        assert output.messages() == [AIMessage(content='Hello')]

    def test_many_text_blocks_read_as_the_parts_of_one_message(self):
        output = MessagesOutput(_message([_text('One'), TOOL_USE, _text('Two')]))

        assert output.messages() == [AIMessage(content=[_text('One'), _text('Two')])]

    def test_an_answer_with_no_text_has_no_messages(self):
        output = MessagesOutput(_message([THINKING, TOOL_USE]))

        assert output.messages() == []
        output.write_back([])
        assert output.message['content'] == [THINKING, TOOL_USE]

    def test_an_answer_with_no_content_has_no_messages(self):
        assert MessagesOutput(_message(None)).messages() == []

    def test_changed_text_is_written_back_in_a_copy(self):
        message = _message([_text('My card is 4111')])
        output = MessagesOutput(message)

        output.write_back([AIMessage(content='My card is <CARD>')])

        assert output.message['content'] == [_text('My card is <CARD>')]
        assert message['content'] == [_text('My card is 4111')]

    def test_write_back_keeps_block_order_and_every_other_field(self):
        citations = [{'type': 'char_location', 'cited_text': 'x'}]
        output = MessagesOutput(
            _message(
                [
                    THINKING,
                    _text('Call 555', citations=citations),
                    TOOL_USE,
                    _text('Ok'),
                ]
            )
        )

        output.write_back([AIMessage(content=[_text('Call <PHONE>'), _text('Ok')])])

        assert output.message == _message(
            [
                THINKING,
                _text('Call <PHONE>', citations=citations),
                TOOL_USE,
                _text('Ok'),
            ]
        )

    @pytest.mark.parametrize(
        'messages',
        [
            [],
            [AIMessage(content='a'), AIMessage(content='b')],
            [AIMessage(content=[_text('a'), _text('b')])],
        ],
    )
    def test_write_back_refuses_a_changed_structure(self, messages):
        output = MessagesOutput(_message([_text('Hello')]))

        with pytest.raises(GatewayInternalError):
            output.write_back(messages)

    def test_usage_is_the_answer_usage(self):
        assert MessagesOutput(_message([_text('Hi')])).usage() == USAGE

    def test_usage_is_empty_when_the_answer_has_none(self):
        assert MessagesOutput(_message([_text('Hi')], usage=None)).usage() == {}


class TestBuiltAnswer:
    def test_built_answer_is_a_valid_message_with_one_text_block(self):
        message = gateway_message('0000-1111', 'proj/assistant', 'Blocked.')

        assert message == {
            'id': 'msg_00001111',
            'type': 'message',
            'role': 'assistant',
            'model': 'proj/assistant',
            'content': [{'type': 'text', 'text': 'Blocked.'}],
            'stop_reason': 'end_turn',
            'stop_sequence': None,
            'usage': {
                'input_tokens': 0,
                'output_tokens': 0,
                'cache_creation_input_tokens': 0,
                'cache_read_input_tokens': 0,
            },
        }
        Message.model_validate(message, strict=True)

    def test_replaced_answer_keeps_identity_and_usage(self):
        message = _message(
            [THINKING, _text('Bad'), TOOL_USE],
            stop_reason='stop_sequence',
            stop_sequence='END',
        )

        replaced = with_text(message, 'Blocked.')

        assert replaced == _message(
            [{'type': 'text', 'text': 'Blocked.'}],
            stop_reason='end_turn',
            stop_sequence=None,
        )
        assert message['content'] == [THINKING, _text('Bad'), TOOL_USE]


class TestMessagesReply:
    def test_reply_shows_the_answer_text_to_the_guardrails(self):
        reply = MessagesReply.of(_message([_text('Hello')]))

        assert reply.messages() == [AIMessage(content='Hello')]
        assert (reply.skip, reply.windowed, reply.redactable) == (0, True, True)

    def test_reply_with_new_messages_gives_the_changed_answer(self):
        message = _message([_text('My card is 4111'), TOOL_USE])
        reply = MessagesReply.of(message)

        changed = reply.with_messages([AIMessage(content='My card is <CARD>')])

        assert changed.messages() == [AIMessage(content='My card is <CARD>')]
        assert changed.message() == _message([_text('My card is <CARD>'), TOOL_USE])
        assert message['content'][0]['text'] == 'My card is 4111'

    def test_untouched_reply_gives_the_answer_as_it_was(self):
        message = _message([THINKING, _text('Hello'), TOOL_USE])

        assert MessagesReply.of(message).message() == message


GUARDRAILS = [
    {
        'name': 'redact_email',
        'type': 'presidio_anonymizer',
        'behavior': 'block',
        'where': 'io',
        'parameters': {'entities': ['EMAIL_ADDRESS']},
    },
    {
        'name': 'output_soft_block',
        'type': 'contains',
        'behavior': 'soft_block',
        'where': 'output',
        'parameters': {'values': ['secret']},
        'response_message': 'The answer was withheld.',
    },
    {
        'name': 'output_warn',
        'type': 'contains',
        'behavior': 'warn',
        'where': 'output',
        'parameters': {'values': ['secret']},
    },
]


def _scope(*guardrails: str):
    route: dict = {'chat_models': ['claude']}
    if guardrails:
        route['guardrails'] = list(guardrails)
    routes = build_routes(
        {
            'chat_models': [
                {
                    'model_id': 'claude',
                    'model': 'anthropic/claude-sonnet-4-5',
                    'credentials': {'api_key': 'sk-ant-configured'},
                }
            ],
            'guardrails': GUARDRAILS,
            'routes': {'assistant': route},
        }
    )
    return scope_of(routes['proj/assistant'])


class TestScreenOutput:
    async def test_route_with_no_output_guardrails_gives_the_answer_as_it_is(self):
        scope = _scope()
        message = _message([_text('Write to ada@example.com')])

        assert await screen_output(scope, message) is message
        assert scope.flags == GuardrailFlags()

    async def test_redact_masks_every_text_block_and_nothing_else(self):
        scope = _scope('redact_email')
        message = _message(
            [THINKING, _text('Write to ada@example.com'), TOOL_USE, _text('Bye')]
        )

        screened = await screen_output(scope, message)

        assert screened == _message(
            [THINKING, _text('Write to <EMAIL_ADDRESS>'), TOOL_USE, _text('Bye')]
        )
        assert scope.flags == GuardrailFlags(output_warned=True)

    async def test_soft_block_replaces_the_reply_with_its_message(self):
        scope = _scope('output_soft_block')

        screened = await screen_output(
            scope, _message([_text('The secret is 42'), TOOL_USE])
        )

        assert screened == _message([_text('The answer was withheld.')])
        assert scope.flags == GuardrailFlags(output_warned=True, output_blocked=True)

    async def test_warn_flags_the_answer_and_leaves_it(self):
        scope = _scope('output_warn')
        message = _message([_text('The secret is 42')])

        assert await screen_output(scope, message) == message
        assert scope.flags == GuardrailFlags(output_warned=True)

    async def test_answer_with_no_text_passes_the_guardrails(self):
        scope = _scope('redact_email', 'output_soft_block')
        message = _message([THINKING, TOOL_USE], stop_reason='tool_use')

        assert await screen_output(scope, message) == message
        assert scope.flags == GuardrailFlags()
