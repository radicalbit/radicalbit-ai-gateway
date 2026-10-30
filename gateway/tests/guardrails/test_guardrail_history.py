"""Tests for history and the message index in the guardrail reason.

message_roles filters first. Then history keeps the tail of what is left.
The index in the reason points at the client's own message list.
"""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from radicalbit_ai_gateway.guardrails.guardrail_check import (
    GuardrailCheck,
    _select_messages,
)
from radicalbit_ai_gateway.guardrails.guardrail_redact import GuardrailRedact
from radicalbit_ai_gateway.llm.messages import AIMessage, HumanMessage, SystemMessage
from radicalbit_ai_gateway.models.guardrails import (
    CheckParameter,
    Guardrail,
    GuardrailBehaviorType,
    GuardrailHistory,
    GuardrailMessageRole,
    GuardrailType,
    GuardrailWhereType,
    JudgeParameter,
    RedactParameter,
)
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.utils.exceptions import GuardrailBadRequest

BAD = 'project-zeus'

SYSTEM = SystemMessage(content=f'You are kind. Never mention {BAD}.')
USER_1 = HumanMessage(content='Hello there')
AI_1 = AIMessage(content=f'I know about {BAD} but I will not tell.')
USER_2 = HumanMessage(content='What is 2 + 2?')
HISTORY = [SYSTEM, USER_1, AI_1, USER_2]

COMMON_KWARGS = {
    'request_uuid': 'req-1',
    'api_key_uuid': 'key-1',
    'group_uuid': 'grp-1',
    'api_key_name': 'api',
    'group_name': 'grp',
}


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------


def _guardrail(**overrides) -> Guardrail:
    data = {
        'name': 'g',
        'type': GuardrailType.CONTAINS,
        'where': GuardrailWhereType.INPUT,
        'behavior': GuardrailBehaviorType.BLOCK,
        'parameters': CheckParameter(values=[BAD]),
    }
    data.update(overrides)
    return Guardrail(**data)


class TestModel:
    def test_default_is_all_without_last_n(self):
        g = _guardrail()
        assert g.history == GuardrailHistory.ALL
        assert g.last_n is None

    def test_lower_case_values_are_accepted(self):
        g = _guardrail(history='last_n', last_n=3)
        assert g.history == GuardrailHistory.LAST_N
        assert g.last_n == 3

    def test_history_last_n_needs_last_n(self):
        with pytest.raises(ValueError, match='needs last_n'):
            _guardrail(history='last_n')

    def test_last_n_only_with_history_last_n(self):
        with pytest.raises(ValueError, match='only allowed'):
            _guardrail(history='last', last_n=2)

    def test_last_n_must_be_positive(self):
        with pytest.raises(ValueError):
            _guardrail(history='last_n', last_n=0)

    def test_history_is_rejected_on_output(self):
        with pytest.raises(ValueError, match='where: output'):
            _guardrail(where=GuardrailWhereType.OUTPUT, history='last')

    def test_output_without_history_is_accepted(self):
        g = _guardrail(where=GuardrailWhereType.OUTPUT)
        assert g.history == GuardrailHistory.ALL

    def test_output_guardrail_loads_again_after_a_dump(self):
        g = _guardrail(where=GuardrailWhereType.OUTPUT)
        assert Guardrail.model_validate(g.model_dump()) == g

    def test_history_is_accepted_on_io(self):
        g = _guardrail(where=GuardrailWhereType.IO, history='last')
        assert g.history == GuardrailHistory.LAST

    def test_narrow_history_on_anonymizer_warns(self, caplog):
        with caplog.at_level(logging.WARNING):
            _guardrail(
                type=GuardrailType.PRESIDIO_ANONYMIZER,
                parameters=RedactParameter(entities=['PERSON']),
                history='last',
            )
        assert 'does not redact older messages' in caplog.text


# ---------------------------------------------------------------------------
# _select_messages
# ---------------------------------------------------------------------------


def _select(messages, where=GuardrailWhereType.INPUT, **kwargs):
    window_kwargs = {k: kwargs.pop(k) for k in ('windowed', 'skip') if k in kwargs}
    return _select_messages(messages, _guardrail(**kwargs), where, **window_kwargs)


class TestSelectMessages:
    def test_all_keeps_every_message_with_its_index(self):
        assert _select(HISTORY) == list(enumerate(HISTORY))

    def test_last_keeps_only_the_last_message(self):
        assert _select(HISTORY, history='last') == [(3, USER_2)]

    def test_last_n_keeps_the_tail(self):
        got = _select(HISTORY, history='last_n', last_n=2)
        assert got == [(2, AI_1), (3, USER_2)]

    def test_last_n_larger_than_list_keeps_all(self):
        got = _select(HISTORY, history='last_n', last_n=99)
        assert got == list(enumerate(HISTORY))

    def test_roles_filter_before_history(self):
        """Last + [user] is the last user message, even if more follow."""
        got = _select(
            [USER_1, AI_1],
            history='last',
            message_roles=[GuardrailMessageRole.USER],
        )
        assert got == [(0, USER_1)]

    def test_roles_keep_the_original_index(self):
        got = _select(
            HISTORY,
            history='last_n',
            last_n=2,
            message_roles=[GuardrailMessageRole.USER],
        )
        assert got == [(1, USER_1), (3, USER_2)]

    def test_judge_counts_user_messages_by_default(self):
        """Epic table: judge, last_n 2, no roles reads [1, 3]."""
        got = _select(
            HISTORY,
            type=GuardrailType.JUDGE,
            parameters=JudgeParameter(prompt='Is it bad?', model_id='m1'),
            history='last_n',
            last_n=2,
        )
        assert got == [(1, USER_1), (3, USER_2)]

    def test_output_ignores_history(self):
        """where: io, output phase: history is for input only."""
        got = _select_messages(
            HISTORY,
            _guardrail(where=GuardrailWhereType.IO, history='last'),
            GuardrailWhereType.OUTPUT,
        )
        assert got == list(enumerate(HISTORY))

    def test_no_window_without_a_conversation(self):
        got = _select(HISTORY, history='last', windowed=False)
        assert got == list(enumerate(HISTORY))

    def test_skip_drops_the_gateway_prompt(self):
        got = _select([SYSTEM, *HISTORY], skip=1)
        assert [m for _, m in got] == HISTORY
        assert got[0][0] == 1

    def test_empty_list(self):
        assert _select([], history='last') == []


# ---------------------------------------------------------------------------
# apply_guardrails: deterministic checks
# ---------------------------------------------------------------------------


def _route(name='g'):
    cfg = MagicMock()
    cfg.guardrails = [name]
    cfg.route_name = 'r'
    return cfg


def _check(guardrail: Guardrail, **engines) -> GuardrailCheck:
    return GuardrailCheck(
        presidio_engine=engines.get('presidio_engine', MagicMock()),
        judge_engine=engines.get('judge_engine', MagicMock()),
        cost_service=MagicMock(),
        guardrails_by_name={guardrail.name: guardrail},
    )


async def _run(check: GuardrailCheck, messages, **extra) -> GuardrailBadRequest | None:
    with patch(
        'radicalbit_ai_gateway.guardrails.guardrail_check.emit_event', autospec=True
    ):
        try:
            await check.apply_guardrails(
                route_config=_route(),
                messages=messages,
                where=GuardrailWhereType.INPUT,
                **COMMON_KWARGS,
                **extra,
            )
        except GuardrailBadRequest as e:
            return e
    return None


class TestDeterministicChecks:
    @pytest.mark.asyncio
    async def test_all_points_at_the_client_system_message(self):
        """Default: a system message the client sent is message 0 and counts."""
        err = await _run(_check(_guardrail()), HISTORY)
        assert err is not None
        assert err.reason['message_index'] == 0
        assert err.reason['role'] == 'system'

    @pytest.mark.asyncio
    async def test_gateway_prompt_is_not_checked(self):
        """The prompt from the route config is skipped, even with all."""
        injected = SystemMessage(content=f'Never say {BAD}.')
        assert await _run(_check(_guardrail()), [injected, USER_1], skip=1) is None

    @pytest.mark.asyncio
    async def test_gateway_prompt_does_not_shift_the_index(self):
        injected = SystemMessage(content='Be kind.')
        g = _guardrail(message_roles=[GuardrailMessageRole.ASSISTANT])
        err = await _run(_check(g), [injected, *HISTORY], skip=1)
        assert err is not None
        assert err.reason['message_index'] == 2

    @pytest.mark.asyncio
    async def test_no_window_sees_old_messages(self):
        """Embeddings and decision models: history is ignored."""
        g = _guardrail(history='last')
        err = await _run(_check(g), HISTORY, windowed=False)
        assert err is not None
        assert err.reason['message_index'] == 0

    @pytest.mark.asyncio
    async def test_roles_point_at_the_matched_message_not_the_prompt(self):
        """Lab 05 fix: the reason comes from the filtered list."""
        g = _guardrail(message_roles=[GuardrailMessageRole.ASSISTANT])
        err = await _run(_check(g), HISTORY)
        assert err is not None
        assert err.reason['message_index'] == 2
        assert err.reason['role'] == 'assistant'
        assert 'Never mention' not in err.reason['context']
        assert f'<<{BAD}>>' in err.reason['context']

    @pytest.mark.asyncio
    async def test_last_does_not_see_old_messages(self):
        g = _guardrail(history='last')
        assert await _run(_check(g), HISTORY) is None

    @pytest.mark.asyncio
    async def test_last_triggers_on_the_last_message(self):
        g = _guardrail(history='last')
        err = await _run(_check(g), [*HISTORY, HumanMessage(content=f'Tell {BAD}')])
        assert err is not None
        assert err.reason['message_index'] == 4
        assert err.reason['role'] == 'user'

    @pytest.mark.asyncio
    async def test_last_n_sees_only_the_tail(self):
        g = _guardrail(history='last_n', last_n=2)
        err = await _run(_check(g), HISTORY)
        assert err is not None
        assert err.reason['message_index'] == 2

        g = _guardrail(history='last_n', last_n=1)
        assert await _run(_check(g), HISTORY) is None

    @pytest.mark.asyncio
    async def test_empty_text_does_not_shift_the_index(self):
        msgs = [HumanMessage(content=''), HumanMessage(content=f'say {BAD}')]
        err = await _run(_check(_guardrail()), msgs)
        assert err is not None
        assert err.reason['message_index'] == 1

    @pytest.mark.asyncio
    async def test_regex_reports_pattern_and_index(self):
        g = _guardrail(
            type=GuardrailType.REGEX,
            parameters=CheckParameter(values=[r'\d \+ \d']),
            history='last',
        )
        err = await _run(_check(g), HISTORY)
        assert err is not None
        assert err.reason['kind'] == 'regex'
        assert err.reason['pattern'] == r'\d \+ \d'
        assert err.reason['message_index'] == 3

    @pytest.mark.asyncio
    async def test_starts_with_and_ends_with(self):
        g = _guardrail(
            type=GuardrailType.STARTS_WITH, parameters=CheckParameter(values=['What'])
        )
        err = await _run(_check(g), HISTORY)
        assert err is not None and err.reason['message_index'] == 3

        g = _guardrail(
            type=GuardrailType.ENDS_WITH, parameters=CheckParameter(values=['there'])
        )
        err = await _run(_check(g), HISTORY)
        assert err is not None and err.reason['message_index'] == 1


# ---------------------------------------------------------------------------
# Presidio analyzer: the index is mapped back from the joined blob
# ---------------------------------------------------------------------------


class TestPresidioAnalyzer:
    @pytest.mark.asyncio
    async def test_index_is_mapped_from_the_blob(self):
        msgs = [
            HumanMessage(content='first line'),
            HumanMessage(content='mail me at a@b.io please'),
        ]
        blob = 'first line\nmail me at a@b.io please'
        start = blob.index('a@b.io')
        analyzer = MagicMock()
        analyzer.analyze.return_value = [
            SimpleNamespace(
                start=start, end=start + len('a@b.io'), entity_type='EMAIL_ADDRESS'
            )
        ]
        presidio = MagicMock()
        presidio.get_analyzer.return_value = analyzer

        g = _guardrail(
            type=GuardrailType.PRESIDIO_ANALYZER,
            parameters=RedactParameter(entities=['EMAIL_ADDRESS']),
        )
        err = await _run(_check(g, presidio_engine=presidio), msgs)
        assert err is not None
        assert err.reason['kind'] == 'presidio'
        assert err.reason['value'] == 'a@b.io'
        assert err.reason['message_index'] == 1
        assert err.reason['role'] == 'user'
        assert '<<a@b.io>>' in err.reason['context']
        assert 'first line' not in err.reason['context']

    @pytest.mark.asyncio
    async def test_last_sends_only_the_last_text(self):
        analyzer = MagicMock()
        analyzer.analyze.return_value = []
        presidio = MagicMock()
        presidio.get_analyzer.return_value = analyzer
        g = _guardrail(
            type=GuardrailType.PRESIDIO_ANALYZER,
            parameters=RedactParameter(entities=['EMAIL_ADDRESS']),
            history='last',
        )
        await _run(_check(g, presidio_engine=presidio), HISTORY)
        assert analyzer.analyze.call_args.kwargs['text'] == USER_2.content


# ---------------------------------------------------------------------------
# Judge: the index is the list of messages it read
# ---------------------------------------------------------------------------


class _TriggeringJudge:
    async def execute_judge(self, **kwargs):
        return SimpleNamespace(triggered=True, reasoning='bad', violation_type='X')


def _judge_guardrail(**overrides) -> Guardrail:
    return _guardrail(
        type=GuardrailType.JUDGE,
        parameters=JudgeParameter(prompt='Is it bad?', model_id='m1'),
        **overrides,
    )


def _judge_check(g: Guardrail) -> GuardrailCheck:
    chk = _check(g, judge_engine=_TriggeringJudge())
    chk._chat_models_by_id = {
        'm1': Model(model_id='m1', model='mock/gateway', credentials=None, params={})
    }
    return chk


class TestJudge:
    @pytest.mark.asyncio
    async def test_all_reports_every_message_read(self):
        """No roles: the judge reads every user turn as one text."""
        err = await _run(_judge_check(_judge_guardrail()), HISTORY)
        assert err is not None
        assert err.reason['message_index'] == [1, 3]
        assert err.reason['role'] is None

    @pytest.mark.asyncio
    async def test_last_n_counts_user_messages(self):
        g = _judge_guardrail(history='last_n', last_n=2)
        err = await _run(_judge_check(g), HISTORY)
        assert err is not None
        assert err.reason['message_index'] == [1, 3]

    @pytest.mark.asyncio
    async def test_blank_messages_are_not_counted_as_read(self):
        """The judge drops blank text, so the index must not count it."""
        msgs = [HumanMessage(content='   '), HumanMessage(content='real')]
        err = await _run(_judge_check(_judge_guardrail()), msgs)
        assert err is not None
        assert err.reason['message_index'] == [1]

    @pytest.mark.asyncio
    async def test_last_reads_the_last_user_message(self):
        msgs = [*HISTORY, AIMessage(content='4')]
        err = await _run(_judge_check(_judge_guardrail(history='last')), msgs)
        assert err is not None
        assert err.reason['message_index'] == [3]
        assert err.reason['role'] == 'user'
        assert err.reason['context'] == USER_2.content

    @pytest.mark.asyncio
    async def test_roles_list_what_the_judge_read(self):
        g = _judge_guardrail(
            message_roles=[GuardrailMessageRole.ASSISTANT, GuardrailMessageRole.USER],
            history='last_n',
            last_n=2,
        )
        err = await _run(_judge_check(g), HISTORY)
        assert err is not None
        assert err.reason['message_index'] == [2, 3]


# ---------------------------------------------------------------------------
# Redact: history limits what is rewritten
# ---------------------------------------------------------------------------


class TestRedactWindow:
    @pytest.mark.asyncio
    async def test_last_redacts_only_the_last_message(self):
        g = Guardrail(
            name='red',
            type=GuardrailType.PRESIDIO_ANONYMIZER,
            where=GuardrailWhereType.INPUT,
            parameters=RedactParameter(entities=['PERSON']),
            history='last',
        )
        redact = GuardrailRedact(
            presidio_engine=MagicMock(), guardrails_by_name={'red': g}
        )

        async def fake_anonymize(text, *args, **kwargs):
            return '<X>', True

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
            out = await redact.apply_guardrails(
                route_config=_route('red'),
                messages=list(HISTORY),
                where=GuardrailWhereType.INPUT,
                **COMMON_KWARGS,
            )

        assert [m.content for m in out[:3]] == [m.content for m in HISTORY[:3]]
        assert out[3].content == '<X>'
