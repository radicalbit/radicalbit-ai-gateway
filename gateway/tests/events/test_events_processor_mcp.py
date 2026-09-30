"""MCP identity fields land in their own columns, not in the attributes map."""

from unittest.mock import patch

from radicalbit_ai_gateway.events.events_processor import emit_event
from radicalbit_ai_gateway.models.event_payload import McpInvocationEventPayload
from radicalbit_ai_gateway.models.event_type import EventType

BUFFER = 'radicalbit_ai_gateway.events.events_processor._events_buffer'


def _payload(**overrides) -> McpInvocationEventPayload:
    fields = {
        'request_uuid': '11111111-1111-1111-1111-111111111111',
        'event_type': EventType.MCP_INVOCATION,
        'route_name': 'proj/route',
        'value': 1.0,
        'api_key_uuid': '22222222-2222-2222-2222-222222222222',
        'api_key_name': 'key',
        'group_uuid': '33333333-3333-3333-3333-333333333333',
        'group_name': 'group',
        'mcp_method': 'tools/call',
        'mcp_alias': 'github',
        'mcp_target': 'get_issue',
    }
    return McpInvocationEventPayload(**{**fields, **overrides})


def _emit_and_capture(payload: McpInvocationEventPayload) -> dict:
    with patch(BUFFER) as buffer:
        emit_event(payload)
    return buffer.add.call_args.args[0]


def test_method_alias_and_target_have_their_own_columns():
    row = _emit_and_capture(_payload())

    assert row['MCP_METHOD'] == 'tools/call'
    assert row['MCP_ALIAS'] == 'github'
    assert row['MCP_TARGET'] == 'get_issue'


def test_mcp_fields_do_not_leak_into_the_attributes_map():
    row = _emit_and_capture(_payload())

    assert not {'mcp_method', 'mcp_alias', 'mcp_target'} & set(row['ATTRIBUTES'])


def test_a_missing_target_is_an_empty_string():
    row = _emit_and_capture(_payload(mcp_alias='', mcp_target=''))

    assert row['MCP_ALIAS'] == ''
    assert row['MCP_TARGET'] == ''
