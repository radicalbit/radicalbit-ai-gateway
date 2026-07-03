"""Tests for the guardrail message role scope feature.

Verifies that _filter_messages_by_roles correctly filters messages by LangChain
type, and that apply_guardrails / evaluate_warn_triggered respect the
message_roles configuration field.
"""

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
import pytest

from radicalbit_ai_gateway.guardrails.guardrail_check import (
    GuardrailCheck,
    _filter_messages_by_roles,
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


class TestFilterMessagesByRoles:
    def test_default_none_returns_all_messages(self):
        """None (not configured) → no filtering, all messages returned."""
        result = _filter_messages_by_roles(ALL_MESSAGES, None)
        assert result == ALL_MESSAGES

    def test_empty_list_returns_nothing(self):
        """Explicit empty list → nothing passes through."""
        result = _filter_messages_by_roles(ALL_MESSAGES, [])
        assert result == []

    def test_user_only(self):
        result = _filter_messages_by_roles(ALL_MESSAGES, [GuardrailMessageRole.USER])
        assert result == [HUMAN]

    def test_system_only(self):
        result = _filter_messages_by_roles(ALL_MESSAGES, [GuardrailMessageRole.SYSTEM])
        assert result == [SYSTEM]

    def test_tool_only(self):
        result = _filter_messages_by_roles(ALL_MESSAGES, [GuardrailMessageRole.TOOL])
        assert result == [TOOL]

    def test_assistant_only(self):
        result = _filter_messages_by_roles(
            ALL_MESSAGES, [GuardrailMessageRole.ASSISTANT]
        )
        assert result == [AI]

    def test_user_and_tool(self):
        result = _filter_messages_by_roles(
            ALL_MESSAGES, [GuardrailMessageRole.USER, GuardrailMessageRole.TOOL]
        )
        assert result == [HUMAN, TOOL]

    def test_all_roles(self):
        result = _filter_messages_by_roles(
            ALL_MESSAGES,
            [
                GuardrailMessageRole.USER,
                GuardrailMessageRole.SYSTEM,
                GuardrailMessageRole.TOOL,
                GuardrailMessageRole.ASSISTANT,
            ],
        )
        assert result == ALL_MESSAGES

    def test_empty_messages_returns_empty(self):
        result = _filter_messages_by_roles([], [GuardrailMessageRole.USER])
        assert result == []

    def test_no_matching_messages_returns_empty(self):
        """If none of the messages match the requested roles, return []."""
        result = _filter_messages_by_roles([SYSTEM, AI], [GuardrailMessageRole.USER])
        assert result == []


# ---------------------------------------------------------------------------
# apply_guardrails integration tests (using _check_contains internally)
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


def _make_check_engine(guardrail: Guardrail) -> GuardrailCheck:
    return GuardrailCheck(
        presidio_engine=MagicMock(),
        judge_engine=MagicMock(),
        cost_service=MagicMock(),
        guardrails_by_name={'test_guardrail': guardrail},
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


class TestApplyGuardrailsRoleFiltering:
    """apply_guardrails must respect message_roles."""

    @pytest.mark.asyncio
    async def test_user_role_triggers_on_human_message(self):
        """BLOCK guardrail with role=user raises when keyword is in user message."""
        guardrail = _make_guardrail([GuardrailMessageRole.USER], [BLOCKED_KEYWORD])
        engine = _make_check_engine(guardrail)
        route = _make_route_config()
        messages = [HumanMessage(content=f'Test {BLOCKED_KEYWORD} optics')]
        with pytest.raises(GuardrailBadRequest):
            await engine.apply_guardrails(
                route_config=route,
                messages=messages,
                where=GuardrailWhereType.INPUT,
                **COMMON_KWARGS,
            )

    @pytest.mark.asyncio
    async def test_user_role_does_not_trigger_on_tool_message(self):
        """Keyword only in tool message, guardrail scoped to user → must NOT trigger."""
        guardrail = _make_guardrail([GuardrailMessageRole.USER], [BLOCKED_KEYWORD])
        engine = _make_check_engine(guardrail)
        route = _make_route_config()
        messages = [
            HumanMessage(content=SAFE_CONTENT),
            ToolMessage(content=f'tool says {BLOCKED_KEYWORD}', tool_call_id='c1'),
        ]
        result = await engine.apply_guardrails(
            route_config=route,
            messages=messages,
            where=GuardrailWhereType.INPUT,
            **COMMON_KWARGS,
        )
        assert result is None  # not triggered

    @pytest.mark.asyncio
    async def test_tool_role_triggers_on_tool_message(self):
        """BLOCK guardrail with role=tool raises when keyword is in tool message."""
        guardrail = _make_guardrail([GuardrailMessageRole.TOOL], [BLOCKED_KEYWORD])
        engine = _make_check_engine(guardrail)
        route = _make_route_config()
        messages = [
            HumanMessage(content=SAFE_CONTENT),
            ToolMessage(content=f'tool says {BLOCKED_KEYWORD}', tool_call_id='c1'),
        ]
        with pytest.raises(GuardrailBadRequest):
            await engine.apply_guardrails(
                route_config=route,
                messages=messages,
                where=GuardrailWhereType.INPUT,
                **COMMON_KWARGS,
            )

    @pytest.mark.asyncio
    async def test_tool_role_does_not_trigger_on_human_message(self):
        """Keyword only in user message, guardrail scoped to tool → must NOT trigger."""
        guardrail = _make_guardrail([GuardrailMessageRole.TOOL], [BLOCKED_KEYWORD])
        engine = _make_check_engine(guardrail)
        route = _make_route_config()
        messages = [
            HumanMessage(content=f'user says {BLOCKED_KEYWORD}'),
            ToolMessage(content=SAFE_CONTENT, tool_call_id='c1'),
        ]
        result = await engine.apply_guardrails(
            route_config=route,
            messages=messages,
            where=GuardrailWhereType.INPUT,
            **COMMON_KWARGS,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_system_role_triggers_on_system_message(self):
        """BLOCK guardrail with role=system raises when keyword is in system message."""
        guardrail = _make_guardrail([GuardrailMessageRole.SYSTEM], [BLOCKED_KEYWORD])
        engine = _make_check_engine(guardrail)
        route = _make_route_config()
        messages = [
            SystemMessage(content=f'System prompt contains {BLOCKED_KEYWORD}'),
            HumanMessage(content=SAFE_CONTENT),
        ]
        with pytest.raises(GuardrailBadRequest):
            await engine.apply_guardrails(
                route_config=route,
                messages=messages,
                where=GuardrailWhereType.INPUT,
                **COMMON_KWARGS,
            )

    @pytest.mark.asyncio
    async def test_multi_role_user_and_tool(self):
        """BLOCK guardrail with roles=[user,tool] raises when keyword is in tool message."""
        guardrail = _make_guardrail(
            [GuardrailMessageRole.USER, GuardrailMessageRole.TOOL], [BLOCKED_KEYWORD]
        )
        engine = _make_check_engine(guardrail)
        route = _make_route_config()
        messages = [
            HumanMessage(content=SAFE_CONTENT),
            ToolMessage(content=f'tool says {BLOCKED_KEYWORD}', tool_call_id='c1'),
        ]
        with pytest.raises(GuardrailBadRequest):
            await engine.apply_guardrails(
                route_config=route,
                messages=messages,
                where=GuardrailWhereType.INPUT,
                **COMMON_KWARGS,
            )

    @pytest.mark.asyncio
    async def test_default_none_scans_all_messages(self):
        """Default (None) scans all message types — original gateway behavior."""
        guardrail = _make_guardrail(None, [BLOCKED_KEYWORD])
        engine = _make_check_engine(guardrail)
        route = _make_route_config()
        # keyword in tool message → MUST trigger because None = no filtering
        messages = [
            HumanMessage(content=SAFE_CONTENT),
            ToolMessage(content=f'tool says {BLOCKED_KEYWORD}', tool_call_id='c1'),
        ]
        with pytest.raises(GuardrailBadRequest):
            await engine.apply_guardrails(
                route_config=route,
                messages=messages,
                where=GuardrailWhereType.INPUT,
                **COMMON_KWARGS,
            )

    @pytest.mark.asyncio
    async def test_default_none_triggers_on_user_message(self):
        """Default (None) also triggers when keyword is in user message."""
        guardrail = _make_guardrail(None, [BLOCKED_KEYWORD])
        engine = _make_check_engine(guardrail)
        route = _make_route_config()
        messages = [HumanMessage(content=f'user says {BLOCKED_KEYWORD}')]
        with pytest.raises(GuardrailBadRequest):
            await engine.apply_guardrails(
                route_config=route,
                messages=messages,
                where=GuardrailWhereType.INPUT,
                **COMMON_KWARGS,
            )

    @pytest.mark.asyncio
    async def test_explicit_user_only_does_not_scan_tool(self):
        """Explicit [USER] scope: keyword in tool message → must NOT trigger."""
        guardrail = _make_guardrail([GuardrailMessageRole.USER], [BLOCKED_KEYWORD])
        engine = _make_check_engine(guardrail)
        route = _make_route_config()
        messages = [
            HumanMessage(content=SAFE_CONTENT),
            ToolMessage(content=f'tool says {BLOCKED_KEYWORD}', tool_call_id='c1'),
        ]
        result = await engine.apply_guardrails(
            route_config=route,
            messages=messages,
            where=GuardrailWhereType.INPUT,
            **COMMON_KWARGS,
        )
        assert result is None
