"""The guardrails module: a route's guardrails, picked once, and a request's."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from radicalbit_ai_gateway.guardrails.guardrail_check import CheckResult
from radicalbit_ai_gateway.guardrails.guardrails import (
    Conversation,
    GuardrailFlags,
    Guardrails,
    Reply,
    RouteGuardrails,
    Texts,
)
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.llm.messages import HumanMessage, SystemMessage
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.guardrails import Guardrail
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.exceptions import (
    GatewayInternalError,
    GuardrailBadRequest,
)

EMAIL = 'ada.lovelace@analytical-engine.example.com'
IDENTITY = RequestIdentity(
    request_uuid='req',
    route_name='chat',
    api_key_uuid='key',
    api_key_name='key-name',
    group_uuid='group',
    group_name='group-name',
)


def _contains(name, where, behavior, value, **extra) -> Guardrail:
    return Guardrail.model_validate(
        {
            'name': name,
            'type': 'contains',
            'where': where,
            'behavior': behavior,
            'parameters': {'values': [value]},
            **extra,
        }
    )


def _redact(name, where) -> Guardrail:
    return Guardrail.model_validate(
        {
            'name': name,
            'type': 'presidio_anonymizer',
            'where': where,
            'parameters': {'language': 'en', 'entities': ['EMAIL_ADDRESS']},
        }
    )


REDACT_IN = _redact('redact_in', 'input')
REDACT_OUT = _redact('redact_out', 'output')
WARN_IN = _contains('warn_in', 'input', 'warn', 'warnme')
SOFT_IN = _contains('soft_in', 'input', 'soft_block', 'softme')
BLOCK_IN = _contains('block_in', 'input', 'block', 'blockme')
SOFT_IO = _contains('soft_io', 'io', 'soft_block', 'softout')
DISABLED = _contains('off', 'io', 'block', 'x', enabled=False)


def _guardrails(*defined: Guardrail) -> Guardrails:
    return Guardrails(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=MagicMock(spec_set=PromptManager)),
        cost_service=MagicMock(spec_set=CostService),
        guardrails=list(defined),
    )


def _route(
    *names: str,
    defined=(REDACT_IN, REDACT_OUT, WARN_IN, SOFT_IN, BLOCK_IN, SOFT_IO, DISABLED),
):
    config = GatewayRouteConfig(
        route_name='chat', chat_models=['m'], guardrails=list(names)
    )
    return _guardrails(*defined).for_route(config)


def _request(route: RouteGuardrails, charge=None):
    return route.for_request(IDENTITY, charge or AsyncMock())


@pytest.fixture(autouse=True)
def _quiet_events():
    with (
        patch('radicalbit_ai_gateway.guardrails.guardrail_check.emit_event'),
        patch('radicalbit_ai_gateway.guardrails.guardrail_redact.emit_event'),
    ):
        yield


class TestRouteGuardrails:
    def test_a_route_picks_its_enabled_guardrails_by_phase_and_class(self):
        route = _route('soft_io', 'redact_in', 'warn_in', 'redact_out', 'off')

        assert route.input_redact == (REDACT_IN,)
        assert route.input_check == (SOFT_IO, WARN_IN)
        assert route.output_redact == (REDACT_OUT,)
        assert route.output_check == (SOFT_IO,)
        assert route.has_output

    def test_names_the_project_does_not_define_are_kept_to_be_logged(self):
        route = _route('ghost', 'warn_in')

        assert route.unknown == ('ghost',)
        assert route.input_check == (WARN_IN,)
        assert not route.has_output

    def test_a_route_without_guardrails_has_none(self):
        route = RouteGuardrails()

        assert not route.has_output
        assert route.input_redact == route.input_check == ()


class TestGuardrailFlags:
    def test_no_flags_no_headers(self):
        assert GuardrailFlags().headers() == {}

    def test_every_flag_has_its_header(self):
        flags = GuardrailFlags(input_warned=True) | GuardrailFlags(
            output_blocked=True, output_warned=True
        )

        assert flags.headers() == {
            'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true',
            'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-TRIGGERED': 'true',
            'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true',
            'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true',
            'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN': 'true',
        }


class TestRequestGuardrails:
    async def test_without_redact_guardrails_the_payload_is_the_same(self):
        messages = [HumanMessage(content=f'Mail {EMAIL}')]
        payload = Conversation(messages)

        screened = await _request(_route('warn_in')).redact_input(payload)

        assert screened.payload is payload
        assert screened.flags == GuardrailFlags()

    async def test_redaction_flags_the_input_and_returns_a_new_list(self):
        messages = [HumanMessage(content=f'Mail {EMAIL}')]

        screened = await _request(_route('redact_in')).redact_input(
            Conversation(messages)
        )

        assert screened.payload.messages() is not messages
        assert screened.payload.messages()[0].content == 'Mail <EMAIL_ADDRESS>'
        assert screened.flags == GuardrailFlags(input_warned=True)

    async def test_a_soft_block_keeps_the_redaction_flag_and_names_its_guardrail(self):
        guardrails = _request(_route('redact_in', 'warn_in', 'soft_in'))

        screened = await guardrails.screen_input(
            Conversation([HumanMessage(content=f'{EMAIL} warnme softme')])
        )

        assert screened.soft_block.guardrail is SOFT_IN
        assert screened.flags == GuardrailFlags(input_warned=True, input_blocked=True)

    async def test_a_warn_before_a_soft_block_is_flagged(self):
        guardrails = _request(_route('warn_in', 'soft_in'))

        screened = await guardrails.check_input(
            Conversation([HumanMessage(content='warnme softme')])
        )

        assert screened.flags == GuardrailFlags(input_warned=True, input_blocked=True)

    async def test_check_skips_the_gateways_system_prompt(self):
        guardrails = _request(_route('soft_in'))
        messages = [SystemMessage(content='softme'), HumanMessage(content='hi')]

        screened = await guardrails.check_input(Conversation(messages, skip=1))

        assert screened.soft_block is None

    async def test_a_block_raises(self):
        with pytest.raises(GuardrailBadRequest):
            await _request(_route('block_in')).check_input(Texts(['blockme']))

    async def test_texts_come_back_as_strings(self):
        screened = await _request(_route('redact_in')).screen_input(
            Texts([f'Mail {EMAIL}', 'hi'])
        )

        assert screened.payload == Texts(['Mail <EMAIL_ADDRESS>', 'hi'])

    async def test_an_empty_reply_is_checked_not_redacted(self):
        route = _route('redact_out', 'soft_io')
        route.redact.apply = AsyncMock()

        screened = await _request(route).screen_output(Reply(''))

        route.redact.apply.assert_not_called()
        assert screened.soft_block is None

    async def test_an_output_soft_block_flags_the_output_warned_and_blocked(self):
        screened = await _request(_route('soft_io')).screen_output(
            Reply('a softout reply')
        )

        assert screened.soft_block.guardrail is SOFT_IO
        assert screened.flags == GuardrailFlags(output_warned=True, output_blocked=True)

    async def test_an_output_redaction_flags_the_output(self):
        screened = await _request(_route('redact_out')).screen_output(
            Reply(f'Write to {EMAIL}')
        )

        assert screened.payload.text == 'Write to <EMAIL_ADDRESS>'
        assert screened.flags == GuardrailFlags(output_warned=True)

    async def test_judge_calls_are_charged_to_the_request(self):
        route = _route('warn_in')
        route.check.apply = AsyncMock(return_value=CheckResult())
        charge = AsyncMock()

        await _request(route, charge).check_input(Texts(['hi']))

        kwargs = route.check.apply.call_args.kwargs
        assert kwargs['count_judge_usage'] is charge
        assert kwargs['identity'] is IDENTITY
        assert kwargs['windowed'] is False

    async def test_an_unexpected_error_becomes_an_internal_error(self):
        route = _route('warn_in')
        route.check.apply = AsyncMock(side_effect=RuntimeError('boom'))

        with pytest.raises(GatewayInternalError, match='Error during guardrail'):
            await _request(route).check_input(Texts(['hi']))
