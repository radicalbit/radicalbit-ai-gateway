"""Tests for the guardrail message role scope feature.

Verifies that _filter_messages_by_roles correctly filters messages by LangChain
type, and that apply_check respects the
message_roles configuration field.
"""

from unittest.mock import MagicMock

import pytest

from tests.common.guardrails import apply_check

from radicalbit_ai_gateway.guardrails.guardrail_check import _filter_messages_by_roles
from radicalbit_ai_gateway.guardrails.guardrails import Guardrails
from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from radicalbit_ai_gateway.models.guardrails import (
    CheckParameter,
    Guardrail,
    GuardrailBehaviorType,
    GuardrailMessageRole,
    GuardrailType,
    GuardrailWhereType,
)
from radicalbit_ai_gateway.utils.exceptions import GuardrailBadRequest

# ---------------------------------------------------------------------------
# _filter_messages_by_roles unit tests
# ---------------------------------------------------------------------------

BLOCKED_KEYWORD = 'forbidden-keyword'
SAFE_CONTENT = 'safe and innocuous message'

HUMAN = HumanMessage(content=f'user says {BLOCKED_KEYWORD}')
SYSTEM = SystemMessage(content=f'system says {BLOCKED_KEYWORD}')
TOOL = ToolMessage(content=f'tool says {BLOCKED_KEYWORD}', tool_call_id='c1')
AI = AIMessage(content=f'assistant says {BLOCKED_KEYWORD}')

ALL_MESSAGES = [HUMAN, SYSTEM, TOOL, AI]


USER = GuardrailMessageRole.USER
SYSTEM_ROLE = GuardrailMessageRole.SYSTEM
TOOL_ROLE = GuardrailMessageRole.TOOL
ASSISTANT = GuardrailMessageRole.ASSISTANT


@pytest.mark.parametrize(
    ('messages', 'roles', 'expected'),
    [
        # None (not configured) means no filtering.
        pytest.param(ALL_MESSAGES, None, ALL_MESSAGES, id='default-none-returns-all'),
        # An explicit empty list lets nothing through.
        pytest.param(ALL_MESSAGES, [], [], id='empty-list-returns-nothing'),
        pytest.param(ALL_MESSAGES, [USER], [HUMAN], id='user-only'),
        pytest.param(ALL_MESSAGES, [SYSTEM_ROLE], [SYSTEM], id='system-only'),
        pytest.param(ALL_MESSAGES, [TOOL_ROLE], [TOOL], id='tool-only'),
        pytest.param(ALL_MESSAGES, [ASSISTANT], [AI], id='assistant-only'),
        pytest.param(
            ALL_MESSAGES, [USER, TOOL_ROLE], [HUMAN, TOOL], id='user-and-tool'
        ),
        pytest.param(
            ALL_MESSAGES,
            [USER, SYSTEM_ROLE, TOOL_ROLE, ASSISTANT],
            ALL_MESSAGES,
            id='all-roles',
        ),
        pytest.param([], [USER], [], id='empty-messages'),
        pytest.param([SYSTEM, AI], [USER], [], id='no-matching-messages'),
    ],
)
def test_filter_messages_by_roles(messages, roles, expected):
    assert _filter_messages_by_roles(messages, roles) == expected


# ---------------------------------------------------------------------------
# apply_check integration tests (using _check_contains internally)
# ---------------------------------------------------------------------------


def _make_guardrail(
    message_roles: list[GuardrailMessageRole] | None,
    values: list[str],
    behavior: GuardrailBehaviorType = GuardrailBehaviorType.BLOCK,
) -> Guardrail:
    return Guardrail(
        name='test_guardrail',
        type=GuardrailType.CONTAINS,
        where=GuardrailWhereType.INPUT,
        behavior=behavior,
        message_roles=message_roles,
        parameters=CheckParameter(type='CHECK', values=values),
    )


def _make_route_config(guardrail_name: str = 'test_guardrail'):
    config = MagicMock()
    config.guardrails = [guardrail_name]
    config.route_name = 'test_route'
    return config


def _make_check_engine(guardrail: Guardrail) -> Guardrails:
    return Guardrails(
        presidio_engine=MagicMock(),
        judge_engine=MagicMock(),
        cost_service=MagicMock(),
        guardrails=[guardrail],
    )


COMMON_KWARGS = {
    'request_uuid': 'req-1',
    'api_key_uuid': 'key-1',
    'group_uuid': 'grp-1',
    'api_key_name': 'api',
    'group_name': 'grp',
    'project_uuid': 'proj-1',
    'project_name': 'proj',
}


_SAFE_HUMAN = HumanMessage(content=SAFE_CONTENT)
_BLOCKED_TOOL = ToolMessage(content=f'tool says {BLOCKED_KEYWORD}', tool_call_id='c1')
_BLOCKED_HUMAN = HumanMessage(content=f'user says {BLOCKED_KEYWORD}')


async def _apply(roles, messages):
    guardrail = _make_guardrail(roles, [BLOCKED_KEYWORD])
    return await apply_check(
        _make_check_engine(guardrail),
        route_config=_make_route_config(),
        messages=messages,
        where=GuardrailWhereType.INPUT,
        **COMMON_KWARGS,
    )


class TestApplyGuardrailsRoleFiltering:
    """apply_check must respect message_roles."""

    @pytest.mark.parametrize(
        ('roles', 'messages'),
        [
            pytest.param(
                [USER],
                [HumanMessage(content=f'Test {BLOCKED_KEYWORD} optics')],
                id='user-role-on-human-message',
            ),
            pytest.param(
                [TOOL_ROLE],
                [_SAFE_HUMAN, _BLOCKED_TOOL],
                id='tool-role-on-tool-message',
            ),
            pytest.param(
                [SYSTEM_ROLE],
                [
                    SystemMessage(content=f'System prompt contains {BLOCKED_KEYWORD}'),
                    _SAFE_HUMAN,
                ],
                id='system-role-on-system-message',
            ),
            pytest.param(
                [USER, TOOL_ROLE],
                [_SAFE_HUMAN, _BLOCKED_TOOL],
                id='user-and-tool-on-tool-message',
            ),
            # Default None scans every message type (original gateway behaviour).
            pytest.param(
                None, [_SAFE_HUMAN, _BLOCKED_TOOL], id='default-none-on-tool-message'
            ),
            pytest.param(None, [_BLOCKED_HUMAN], id='default-none-on-user-message'),
        ],
    )
    async def test_guardrail_blocks_keyword_in_a_scoped_role(self, roles, messages):
        with pytest.raises(GuardrailBadRequest):
            await _apply(roles, messages)

    @pytest.mark.parametrize(
        ('roles', 'messages'),
        [
            pytest.param(
                [USER],
                [_SAFE_HUMAN, _BLOCKED_TOOL],
                id='user-role-ignores-tool-message',
            ),
            pytest.param(
                [TOOL_ROLE],
                [_BLOCKED_HUMAN, ToolMessage(content=SAFE_CONTENT, tool_call_id='c1')],
                id='tool-role-ignores-human-message',
            ),
        ],
    )
    async def test_guardrail_ignores_keyword_outside_the_scoped_roles(
        self, roles, messages
    ):
        result = await _apply(roles, messages)
        assert result.soft_block is None
