"""Tests for history and the message index in the guardrail reason.

message_roles filters first. Then history keeps the tail of what is left.
The index in the reason points at the client's own message list.
"""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.common.guardrails import apply_check, apply_redact

from radicalbit_ai_gateway.guardrails.guardrail_check import _select_messages
from radicalbit_ai_gateway.guardrails.guardrails import Guardrails
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


@pytest.mark.parametrize(
    ('overrides', 'history', 'last_n'),
    [
        pytest.param({}, GuardrailHistory.ALL, None, id='default-all'),
        pytest.param(
            {'history': 'last_n', 'last_n': 3},
            GuardrailHistory.LAST_N,
            3,
            id='lower-case-last-n',
        ),
        pytest.param(
            {'where': GuardrailWhereType.IO, 'history': 'last'},
            GuardrailHistory.LAST,
            None,
            id='history-on-io',
        ),
    ],
)
def test_valid_history(overrides, history, last_n):
    g = _guardrail(**overrides)
    assert (g.history, g.last_n) == (history, last_n)


def test_output_without_history_is_accepted_and_round_trips():
    g = _guardrail(where=GuardrailWhereType.OUTPUT)
    assert (g.history, g.last_n) == (GuardrailHistory.ALL, None)
    assert Guardrail.model_validate(g.model_dump()) == g


@pytest.mark.parametrize(
    ('overrides', 'match'),
    [
        pytest.param({'history': 'last_n'}, 'needs last_n', id='last-n-needs-last-n'),
        pytest.param(
            {'history': 'last', 'last_n': 2},
            'only allowed',
            id='last-n-only-with-last-n',
        ),
        pytest.param(
            {'history': 'last_n', 'last_n': 0},
            'greater than or equal to 1',
            id='last-n-positive',
        ),
        pytest.param(
            {'where': GuardrailWhereType.OUTPUT, 'history': 'last'},
            'where: output',
            id='history-rejected-on-output',
        ),
    ],
)
def test_invalid_history(overrides, match):
    with pytest.raises(ValueError, match=match):
        _guardrail(**overrides)


def test_narrow_history_on_anonymizer_warns(caplog):
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

_USER_ONLY = [GuardrailMessageRole.USER]
_INPUT = GuardrailWhereType.INPUT


@pytest.mark.parametrize(
    ('messages', 'where', 'kwargs', 'expected'),
    [
        pytest.param(HISTORY, _INPUT, {}, list(enumerate(HISTORY)), id='all'),
        pytest.param(HISTORY, _INPUT, {'history': 'last'}, [(3, USER_2)], id='last'),
        pytest.param(
            HISTORY,
            _INPUT,
            {'history': 'last_n', 'last_n': 2},
            [(2, AI_1), (3, USER_2)],
            id='last-n-tail',
        ),
        pytest.param(
            HISTORY,
            _INPUT,
            {'history': 'last_n', 'last_n': 99},
            list(enumerate(HISTORY)),
            id='last-n-larger-than-list',
        ),
        # Last + [user] is the last user message, even if more follow.
        pytest.param(
            [USER_1, AI_1],
            _INPUT,
            {'history': 'last', 'message_roles': _USER_ONLY},
            [(0, USER_1)],
            id='roles-filter-before-history',
        ),
        pytest.param(
            HISTORY,
            _INPUT,
            {'history': 'last_n', 'last_n': 2, 'message_roles': _USER_ONLY},
            [(1, USER_1), (3, USER_2)],
            id='roles-keep-original-index',
        ),
        # where: io, output phase: history is for input only.
        pytest.param(
            HISTORY,
            GuardrailWhereType.OUTPUT,
            {'where': GuardrailWhereType.IO, 'history': 'last'},
            list(enumerate(HISTORY)),
            id='output-ignores-history',
        ),
        pytest.param(
            HISTORY,
            _INPUT,
            {'history': 'last', 'windowed': False},
            list(enumerate(HISTORY)),
            id='no-window-without-conversation',
        ),
        pytest.param(
            [SYSTEM, *HISTORY],
            _INPUT,
            {'skip': 1},
            [(i + 1, m) for i, m in enumerate(HISTORY)],
            id='skip-drops-gateway-prompt',
        ),
        pytest.param([], _INPUT, {'history': 'last'}, [], id='empty'),
    ],
)
def test_select_messages(messages, where, kwargs, expected):
    window_kwargs = {k: kwargs.pop(k) for k in ('windowed', 'skip') if k in kwargs}
    got = _select_messages(messages, _guardrail(**kwargs), where, **window_kwargs)
    assert got == expected


# ---------------------------------------------------------------------------
# apply_check: deterministic checks
# ---------------------------------------------------------------------------


def _route(name='g'):
    cfg = MagicMock()
    cfg.guardrails = [name]
    cfg.route_name = 'r'
    return cfg


def _check(guardrail: Guardrail, **engines) -> Guardrails:
    return Guardrails(
        presidio_engine=engines.get('presidio_engine', MagicMock()),
        judge_engine=engines.get('judge_engine', MagicMock()),
        cost_service=MagicMock(),
        guardrails=[guardrail],
    )


async def _run(check: Guardrails, messages, **extra) -> GuardrailBadRequest | None:
    with patch(
        'radicalbit_ai_gateway.guardrails.guardrail_check.emit_event', autospec=True
    ):
        try:
            await apply_check(
                check,
                route_config=_route(),
                messages=messages,
                where=GuardrailWhereType.INPUT,
                **COMMON_KWARGS,
                **extra,
            )
        except GuardrailBadRequest as e:
            return e
    return None


def _reason(err: GuardrailBadRequest | None, expected: dict | None) -> dict | None:
    """Return the reason keys ``expected`` names, or None when nothing was blocked."""
    if err is None or expected is None:
        return None if err is None else err.reason
    return {k: err.reason[k] for k in expected}


_ASSISTANT_ONLY = [GuardrailMessageRole.ASSISTANT]


@pytest.mark.parametrize(
    ('overrides', 'messages', 'extra', 'expected'),
    [
        # Default: a system message the client sent is message 0 and counts.
        pytest.param(
            {},
            HISTORY,
            {},
            {'message_indices': [0], 'role': 'system'},
            id='all-points-at-client-system-message',
        ),
        # The prompt from the route config is skipped, even with all.
        pytest.param(
            {},
            [SystemMessage(content=f'Never say {BAD}.'), USER_1],
            {'skip': 1},
            None,
            id='gateway-prompt-not-checked',
        ),
        pytest.param(
            {'message_roles': _ASSISTANT_ONLY},
            [SystemMessage(content='Be kind.'), *HISTORY],
            {'skip': 1},
            {'message_indices': [2], 'role': 'assistant'},
            id='gateway-prompt-does-not-shift-index',
        ),
        # Embeddings and decision models: history is ignored.
        pytest.param(
            {'history': 'last'},
            HISTORY,
            {'windowed': False},
            {'message_indices': [0], 'role': 'system'},
            id='no-window-sees-old-messages',
        ),
        # Lab 05 fix: the reason comes from the filtered list, not the prompt.
        pytest.param(
            {'message_roles': _ASSISTANT_ONLY},
            HISTORY,
            {},
            {
                'kind': 'contains',
                'value': BAD,
                'message_indices': [2],
                'role': 'assistant',
                'context': f'I know about <<{BAD}>> but I will …',
            },
            id='roles-point-at-matched-message',
        ),
        pytest.param({'history': 'last'}, HISTORY, {}, None, id='last-skips-old'),
        pytest.param(
            {'history': 'last'},
            [*HISTORY, HumanMessage(content=f'Tell {BAD}')],
            {},
            {'message_indices': [4], 'role': 'user'},
            id='last-triggers-on-last',
        ),
        pytest.param(
            {'history': 'last_n', 'last_n': 2},
            HISTORY,
            {},
            {'message_indices': [2], 'role': 'assistant'},
            id='last-n-2-sees-tail',
        ),
        pytest.param(
            {'history': 'last_n', 'last_n': 1}, HISTORY, {}, None, id='last-n-1-misses'
        ),
        pytest.param(
            {},
            [HumanMessage(content=''), HumanMessage(content=f'say {BAD}')],
            {},
            {'message_indices': [1], 'role': 'user'},
            id='empty-text-does-not-shift-index',
        ),
        pytest.param(
            {
                'type': GuardrailType.REGEX,
                'parameters': CheckParameter(values=[r'\d \+ \d']),
                'history': 'last',
            },
            HISTORY,
            {},
            {
                'kind': 'regex',
                'pattern': r'\d \+ \d',
                'message_indices': [3],
                'role': 'user',
                'context': 'What is <<2>> <<+>> <<2?>>',
            },
            id='regex-reports-pattern-and-index',
        ),
        pytest.param(
            {
                'type': GuardrailType.STARTS_WITH,
                'parameters': CheckParameter(values=['What']),
            },
            HISTORY,
            {},
            {'message_indices': [3], 'role': 'user'},
            id='starts-with',
        ),
        pytest.param(
            {
                'type': GuardrailType.ENDS_WITH,
                'parameters': CheckParameter(values=['there']),
            },
            HISTORY,
            {},
            {'message_indices': [1], 'role': 'user'},
            id='ends-with',
        ),
    ],
)
@pytest.mark.asyncio
async def test_deterministic_check(overrides, messages, extra, expected):
    err = await _run(_check(_guardrail(**overrides)), messages, **extra)
    assert _reason(err, expected) == expected


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
        assert err.reason['message_indices'] == [1]
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


def _judge_check(g: Guardrail) -> Guardrails:
    chk = _check(g, judge_engine=_TriggeringJudge())
    chk._check._chat_models_by_id = {
        'm1': Model(model_id='m1', model='mock/gateway', credentials=None, params={})
    }
    return chk


@pytest.mark.parametrize(
    ('overrides', 'messages', 'expected'),
    [
        # No roles: the judge reads every user turn as one text.
        pytest.param(
            {},
            HISTORY,
            {'message_indices': [1, 3], 'role': None, 'context': USER_2.content},
            id='all-reports-every-message-read',
        ),
        pytest.param(
            {'history': 'last_n', 'last_n': 2},
            HISTORY,
            {'message_indices': [1, 3], 'role': None},
            id='last-n-counts-user-messages',
        ),
        # The judge drops blank text, so the index must not count it.
        pytest.param(
            {},
            [HumanMessage(content='   '), HumanMessage(content='real')],
            {'message_indices': [1], 'role': 'user'},
            id='blank-messages-not-counted',
        ),
        pytest.param(
            {'history': 'last'},
            [*HISTORY, AIMessage(content='4')],
            {'message_indices': [3], 'role': 'user', 'context': USER_2.content},
            id='last-reads-last-user-message',
        ),
        pytest.param(
            {
                'message_roles': [
                    GuardrailMessageRole.ASSISTANT,
                    GuardrailMessageRole.USER,
                ],
                'history': 'last_n',
                'last_n': 2,
            },
            HISTORY,
            {'message_indices': [2, 3], 'role': None},
            id='roles-list-what-judge-read',
        ),
    ],
)
@pytest.mark.asyncio
async def test_judge_reports_messages_read(overrides, messages, expected):
    err = await _run(_judge_check(_judge_guardrail(**overrides)), messages)
    assert _reason(err, expected) == expected


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
        redact = Guardrails(
            presidio_engine=MagicMock(),
            judge_engine=MagicMock(),
            cost_service=MagicMock(),
            guardrails=[g],
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
            out = await apply_redact(
                redact,
                route_config=_route('red'),
                messages=list(HISTORY),
                where=GuardrailWhereType.INPUT,
                **COMMON_KWARGS,
            )

        assert [m.content for m in out[:3]] == [m.content for m in HISTORY[:3]]
        assert out[3].content == '<X>'
