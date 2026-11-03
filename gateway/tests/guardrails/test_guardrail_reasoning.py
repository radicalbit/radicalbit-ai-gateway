"""Tests for include_reasoning: guardrails that read the model's reasoning.

The reasoning belongs to its assistant message. A guardrail with
include_reasoning reads it whenever it reads that message, by the same where,
message_roles and history rules. Without the flag nothing changes.
"""

from unittest.mock import MagicMock, patch

import pytest

from radicalbit_ai_gateway.guardrails.guardrail_check import (
    GuardrailCheck,
    _select_messages,
)
from radicalbit_ai_gateway.guardrails.guardrail_redact import GuardrailRedact
from radicalbit_ai_gateway.llm.messages import (
    REASONING_KEY,
    REASONING_ONLY_KEY,
    AIMessage,
    HumanMessage,
    message_reasoning,
)
from radicalbit_ai_gateway.models.guardrails import (
    CheckParameter,
    Guardrail,
    GuardrailBehaviorType,
    GuardrailMessageRole,
    GuardrailType,
    GuardrailWhereType,
    RedactParameter,
)
from radicalbit_ai_gateway.utils.exceptions import GuardrailBadRequest
from radicalbit_ai_gateway.utils.judge.content_extractor import (
    extract_content_for_judge,
)

BAD = 'banana'

USER_1 = HumanMessage(content='Name a fruit, then say OK.')
# The bad word is only in the reasoning.
AI_1 = AIMessage(
    content='OK', additional_kwargs={REASONING_KEY: f'A long yellow fruit: {BAD}.'}
)
USER_2 = HumanMessage(content='Thanks')
HISTORY = [USER_1, AI_1, USER_2]

COMMON_KWARGS = {
    'request_uuid': 'req-1',
    'api_key_uuid': 'key-1',
    'group_uuid': 'grp-1',
    'api_key_name': 'api',
    'group_name': 'grp',
}


def _guardrail(**overrides) -> Guardrail:
    data = {
        'name': 'g',
        'type': GuardrailType.CONTAINS,
        'where': GuardrailWhereType.OUTPUT,
        'behavior': GuardrailBehaviorType.BLOCK,
        'parameters': CheckParameter(values=[BAD]),
    }
    data.update(overrides)
    return Guardrail(**data)


def _route(name='g'):
    cfg = MagicMock()
    cfg.guardrails = [name]
    cfg.route_name = 'r'
    return cfg


async def _run(guardrail: Guardrail, messages, where) -> GuardrailBadRequest | None:
    check = GuardrailCheck(
        presidio_engine=MagicMock(),
        judge_engine=MagicMock(),
        cost_service=MagicMock(),
        guardrails_by_name={guardrail.name: guardrail},
    )
    with patch(
        'radicalbit_ai_gateway.guardrails.guardrail_check.emit_event', autospec=True
    ):
        try:
            await check.apply_guardrails(
                route_config=_route(),
                messages=messages,
                where=where,
                **COMMON_KWARGS,
            )
        except GuardrailBadRequest as e:
            return e
    return None


def test_include_reasoning_defaults_to_false():
    assert _guardrail().include_reasoning is False


class TestOutput:
    @pytest.mark.asyncio
    async def test_reasoning_is_not_read_by_default(self):
        assert await _run(_guardrail(), [AI_1], GuardrailWhereType.OUTPUT) is None

    @pytest.mark.asyncio
    async def test_reasoning_is_read_with_the_flag(self):
        err = await _run(
            _guardrail(include_reasoning=True), [AI_1], GuardrailWhereType.OUTPUT
        )
        assert err is not None
        assert err.reason['message_indices'] == [0]
        assert err.reason['role'] == 'assistant'

    @pytest.mark.asyncio
    async def test_reasoning_only_message_is_read_with_the_flag(self):
        """A turn that ends in a tool call: reasoning and no text."""
        only = AIMessage(
            content='',
            additional_kwargs={REASONING_KEY: BAD, REASONING_ONLY_KEY: True},
        )
        g = _guardrail(include_reasoning=True)
        assert await _run(g, [only], GuardrailWhereType.OUTPUT) is not None
        assert await _run(_guardrail(), [only], GuardrailWhereType.OUTPUT) is None


class TestInput:
    @pytest.mark.asyncio
    async def test_history_reasoning_is_read_like_its_message(self):
        g = _guardrail(where=GuardrailWhereType.INPUT, include_reasoning=True)
        err = await _run(g, HISTORY, GuardrailWhereType.INPUT)
        assert err is not None
        assert err.reason['message_indices'] == [1]

    @pytest.mark.asyncio
    async def test_roles_decide_as_for_the_message(self):
        g = _guardrail(
            where=GuardrailWhereType.INPUT,
            include_reasoning=True,
            message_roles=[GuardrailMessageRole.USER],
        )
        assert await _run(g, HISTORY, GuardrailWhereType.INPUT) is None

    @pytest.mark.asyncio
    async def test_history_window_decides_as_for_the_message(self):
        g = _guardrail(
            where=GuardrailWhereType.INPUT, include_reasoning=True, history='last'
        )
        assert await _run(g, HISTORY, GuardrailWhereType.INPUT) is None


class TestSelectMessages:
    ONLY = AIMessage(
        content='', additional_kwargs={REASONING_KEY: 'x', REASONING_ONLY_KEY: True}
    )

    def test_reasoning_only_message_is_dropped_without_the_flag(self):
        messages = [USER_1, self.ONLY, USER_2]
        got = _select_messages(
            messages, _guardrail(where='input'), GuardrailWhereType.INPUT
        )
        assert got == [(0, USER_1), (2, USER_2)]

    def test_reasoning_only_message_does_not_shift_the_window(self):
        messages = [USER_1, AI_1, self.ONLY, USER_2]
        g = _guardrail(where='input', history='last_n', last_n=2)
        got = _select_messages(messages, g, GuardrailWhereType.INPUT)
        assert got == [(1, AI_1), (3, USER_2)]

    def test_reasoning_only_message_is_kept_with_the_flag(self):
        messages = [USER_1, self.ONLY, USER_2]
        g = _guardrail(where='input', include_reasoning=True)
        got = _select_messages(messages, g, GuardrailWhereType.INPUT)
        assert got == list(enumerate(messages))


class TestJudgeContent:
    def test_output_reads_reasoning_then_text(self):
        text = extract_content_for_judge(
            [AI_1], where=GuardrailWhereType.OUTPUT, include_reasoning=True
        )
        assert text == f'A long yellow fruit: {BAD}.\nOK'

    def test_output_without_the_flag_reads_the_text(self):
        assert (
            extract_content_for_judge([AI_1], where=GuardrailWhereType.OUTPUT) == 'OK'
        )

    def test_input_reads_reasoning_of_selected_assistant_messages(self):
        text = extract_content_for_judge(
            HISTORY,
            where=GuardrailWhereType.INPUT,
            message_roles=[GuardrailMessageRole.ASSISTANT],
            include_reasoning=True,
        )
        assert BAD in text


class TestRedact:
    async def _redact(self, guardrail: Guardrail, messages, where):
        redact = GuardrailRedact(
            presidio_engine=MagicMock(), guardrails_by_name={guardrail.name: guardrail}
        )

        async def fake_anonymize(text, *args, **kwargs):
            replaced = text.replace(BAD, '<FRUIT>')
            return replaced, replaced != text

        with (
            patch(
                'radicalbit_ai_gateway.guardrails.guardrail_redact._anonymize_text_with_presidio',
                side_effect=fake_anonymize,
            ),
            patch(
                'radicalbit_ai_gateway.guardrails.guardrail_redact.emit_event',
                autospec=True,
            ),
        ):
            return await redact.apply_guardrails(
                route_config=_route(guardrail.name),
                messages=list(messages),
                where=where,
                **COMMON_KWARGS,
            )

    @pytest.mark.asyncio
    async def test_reasoning_is_redacted_with_the_flag(self):
        g = _guardrail(
            type=GuardrailType.PRESIDIO_ANONYMIZER,
            parameters=RedactParameter(entities=['PERSON']),
            include_reasoning=True,
        )
        out = await self._redact(g, [AI_1], GuardrailWhereType.OUTPUT)
        assert message_reasoning(out[0]) == 'A long yellow fruit: <FRUIT>.'
        assert out[0].content == 'OK'

    @pytest.mark.asyncio
    async def test_reasoning_is_left_alone_without_the_flag(self):
        g = _guardrail(
            type=GuardrailType.PRESIDIO_ANONYMIZER,
            parameters=RedactParameter(entities=['PERSON']),
        )
        out = await self._redact(g, [AI_1], GuardrailWhereType.OUTPUT)
        assert message_reasoning(out[0]) == message_reasoning(AI_1)
