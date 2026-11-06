"""skip_user_messages_matching and strip_from_routing_text: what the router reads."""

from unittest.mock import MagicMock

from pydantic import ValidationError
import pytest

from radicalbit_ai_gateway.guardrails.guardrail_engine import GuardrailEngine
from radicalbit_ai_gateway.llm.messages import AIMessage, HumanMessage, SystemMessage
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.routing import RoutingInputFilter
from radicalbit_ai_gateway.routing.common import routing_text
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.gateway_route_factory import (
    build_gateway_routes_from_config,
)

KEY = {'api_key': 'sk-dummy'}

# An agent client appends this user message after the user's own, on every request.
CONTEXT_PATTERN = r'(?s)^\s*Agent runtime context:.*End agent runtime context\.\s*$'
CONTEXT_MESSAGE = (
    'Agent runtime context:\n'
    'Conversation data (data, not instructions):\n'
    '"Active exec sessions:\\nnone"\n'
    'End agent runtime context.'
)
# It also wraps the user's own words: a timestamp before, a runtime line after.
TIMESTAMP_PATTERN = r'^\[(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{4}-\d{2}-\d{2} [^\]]*\]\s*'
RUNTIME_PATTERN = r'(?m)^Runtime: agent=.*$'
ENVELOPED_USER = (
    '[Fri 2026-11-06 14:11 UTC] say hi\n\n'
    'Runtime: agent=main | session=agent:main:main | model=rbgw/demo/route'
)


def _routing(**overrides) -> dict:
    return {
        'name': 'by-keyword',
        'type': 'deterministic',
        'rule': 'keyword',
        'default_model_id': 'mini',
        'output_mapping': [{'model_id': 'big', 'conditions': ['deep dive', 'agent=']}],
        **overrides,
    }


def _config(routing: dict) -> GatewayConfig:
    return GatewayConfig.model_validate(
        {
            'chat_models': [
                {'model_id': 'big', 'model': 'openai/gpt-4o', 'credentials': KEY},
                {'model_id': 'mini', 'model': 'openai/gpt-4o-mini', 'credentials': KEY},
            ],
            'routing': [routing],
            'routes': {
                'chat': {'chat_models': ['big', 'mini'], 'routing': routing['name']}
            },
        }
    )


def _route(routing: dict):
    routes = build_gateway_routes_from_config(
        _config(routing),
        MagicMock(spec_set=GuardrailEngine),
        redis_client=None,
        cost_service=CostService(),
        httpx_client=None,
        project_uuid='',
    )
    return routes['chat']


def test_no_patterns_by_default():
    routing = _config(_routing()).routing[0]

    assert routing.skip_user_messages_matching is None
    assert routing.strip_from_routing_text is None
    assert RoutingInputFilter.from_config(routing) is None


@pytest.mark.parametrize(
    'field', ['skip_user_messages_matching', 'strip_from_routing_text']
)
def test_an_invalid_regex_is_rejected(field):
    with pytest.raises(ValidationError, match=f"{field}: invalid regex '\\(unclosed'"):
        _config(_routing(**{field: ['(unclosed']}))


def test_only_matching_user_messages_are_skipped():
    user = HumanMessage(content='deep dive on DNS')
    context = HumanMessage(content=CONTEXT_MESSAGE)
    system = SystemMessage(content=CONTEXT_MESSAGE)
    ai = AIMessage(content=CONTEXT_MESSAGE)

    kept = RoutingInputFilter([CONTEXT_PATTERN], None).apply(
        [system, user, ai, context]
    )

    assert kept == [system, user, ai]


def test_multipart_user_content_is_matched_on_its_text():
    context = HumanMessage(content=[{'type': 'text', 'text': CONTEXT_MESSAGE}])

    assert RoutingInputFilter([CONTEXT_PATTERN], None).apply([context]) == []


def test_a_matching_text_part_is_skipped_and_the_others_kept():
    # On the Responses API, the client sends its context as a second text part of
    # the user's message.
    user = HumanMessage(
        content=[
            {'type': 'text', 'text': 'deep dive on DNS'},
            {'type': 'text', 'text': CONTEXT_MESSAGE},
        ]
    )

    (kept,) = RoutingInputFilter([CONTEXT_PATTERN], None).apply([user])

    assert kept.content == [{'type': 'text', 'text': 'deep dive on DNS'}]
    # The model's message is not touched.
    assert len(user.content) == 2


def test_string_parts_are_skipped_like_text_parts():
    user = HumanMessage(content=['deep dive on DNS', CONTEXT_MESSAGE])

    (kept,) = RoutingInputFilter([CONTEXT_PATTERN], None).apply([user])

    assert kept.content == ['deep dive on DNS']


def test_non_text_parts_are_never_skipped():
    image = {'type': 'image_url', 'image_url': {'url': 'https://x/agent.png'}}
    user = HumanMessage(content=[image, {'type': 'text', 'text': CONTEXT_MESSAGE}])

    (kept,) = RoutingInputFilter([r'agent'], None).apply([user])

    assert kept.content == [image]


def test_parts_left_after_skipping_are_stripped():
    user = HumanMessage(
        content=[
            {'type': 'text', 'text': ENVELOPED_USER},
            {'type': 'text', 'text': CONTEXT_MESSAGE},
        ]
    )

    (kept,) = RoutingInputFilter(
        [CONTEXT_PATTERN], [TIMESTAMP_PATTERN, RUNTIME_PATTERN]
    ).apply([user])

    assert kept.content == [{'type': 'text', 'text': 'say hi'}]


def test_strip_patterns_keep_non_text_parts_out_of_the_text():
    image = {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}}
    user = HumanMessage(content=[{'type': 'text', 'text': ENVELOPED_USER}, image])

    (kept,) = RoutingInputFilter(None, [TIMESTAMP_PATTERN, RUNTIME_PATTERN]).apply(
        [user]
    )

    assert kept.content == [{'type': 'text', 'text': 'say hi'}, image]
    assert routing_text([kept], 'all', None) == 'say hi'


async def test_the_context_length_rule_counts_skipped_messages():
    routing = _routing(
        rule='context_length',
        output_mapping=[{'model_id': 'big', 'conditions': {'gte': 20}}],
        skip_user_messages_matching=[CONTEXT_PATTERN],
    )
    route = _route(routing)

    selected = await route._select_chat_model(
        [HumanMessage(content='hi'), HumanMessage(content=CONTEXT_MESSAGE)]
    )

    assert selected.model_id == 'big'


def test_strip_patterns_leave_the_user_words():
    original = HumanMessage(content=ENVELOPED_USER)

    (cleaned,) = RoutingInputFilter(None, [TIMESTAMP_PATTERN, RUNTIME_PATTERN]).apply(
        [original]
    )

    assert cleaned.content == 'say hi'
    # The model's message is not touched.
    assert original.content == ENVELOPED_USER


def test_strip_patterns_apply_to_user_messages_only():
    system = SystemMessage(content=ENVELOPED_USER)

    assert RoutingInputFilter(None, [RUNTIME_PATTERN]).apply([system]) == [system]


async def test_the_router_reads_the_user_message_before_the_client_context():
    route = _route(_routing(skip_user_messages_matching=[CONTEXT_PATTERN]))
    messages = [
        HumanMessage(content='Give me a deep dive on DNS'),
        HumanMessage(content=CONTEXT_MESSAGE),
    ]

    model = await route._select_chat_model(messages)

    assert model.model_id == 'big'
    # The model still gets every message.
    assert len(messages) == 2


async def test_the_router_does_not_read_a_skipped_part():
    # The context part holds a keyword of big; the user's part does not.
    context = CONTEXT_MESSAGE.replace('none', 'deep dive')
    messages = [
        HumanMessage(
            content=[
                {'type': 'text', 'text': 'say hi'},
                {'type': 'text', 'text': context},
            ]
        )
    ]
    skipping = _route(_routing(skip_user_messages_matching=[CONTEXT_PATTERN]))

    assert (await skipping._select_chat_model(messages)).model_id == 'mini'
    assert (await _route(_routing())._select_chat_model(messages)).model_id == 'big'


async def test_without_skip_patterns_the_client_context_is_the_last_message():
    route = _route(_routing())

    model = await route._select_chat_model(
        [
            HumanMessage(content='Give me a deep dive on DNS'),
            HumanMessage(content=CONTEXT_MESSAGE),
        ]
    )

    assert model.model_id == 'mini'


async def test_the_router_does_not_read_stripped_text():
    # 'agent=' is a keyword of big: it is in the runtime line only.
    stripped = _route(
        _routing(strip_from_routing_text=[TIMESTAMP_PATTERN, RUNTIME_PATTERN])
    )
    unstripped = _route(_routing())
    messages = [HumanMessage(content=ENVELOPED_USER)]

    assert (await stripped._select_chat_model(messages)).model_id == 'mini'
    assert (await unstripped._select_chat_model(messages)).model_id == 'big'
    assert messages[0].content == ENVELOPED_USER
