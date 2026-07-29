from unittest.mock import patch

from radicalbit_ai_gateway.utils.trace_attributes import (
    set_mcp_attributes,
    set_trace_attributes,
)


@patch(
    'radicalbit_ai_gateway.utils.trace_attributes.Traceloop.set_association_properties'
)
def test_set_trace_attributes(mock_set_props):
    with patch(
        'radicalbit_ai_gateway.utils.trace_attributes.get_value',
        return_value=None,
    ):
        set_trace_attributes(
            request_uuid='req-123',
            route_name='my-route',
            api_key_uuid='key-456',
            api_key_name='my-key',
            group_uuid='grp-789',
            group_name='my-group',
        )

    mock_set_props.assert_called_once_with(
        {
            'request_uuid': 'req-123',
            'route_name': 'my-route',
            'api_key_uuid': 'key-456',
            'api_key_name': 'my-key',
            'group_uuid': 'grp-789',
            'group_name': 'my-group',
        }
    )


@patch(
    'radicalbit_ai_gateway.utils.trace_attributes.Traceloop.set_association_properties'
)
def test_set_trace_attributes_partial(mock_set_props):
    with patch(
        'radicalbit_ai_gateway.utils.trace_attributes.get_value',
        return_value=None,
    ):
        set_trace_attributes(
            request_uuid='req-123',
            route_name='my-route',
        )

    mock_set_props.assert_called_once_with(
        {
            'request_uuid': 'req-123',
            'route_name': 'my-route',
        }
    )


@patch(
    'radicalbit_ai_gateway.utils.trace_attributes.Traceloop.set_association_properties'
)
def test_set_mcp_attributes(mock_set_props):
    with patch(
        'radicalbit_ai_gateway.utils.trace_attributes.get_value',
        return_value=None,
    ):
        set_mcp_attributes(
            method='tools/call',
            alias='github',
            target='get_issue',
            error_code=-32000,
        )

    mock_set_props.assert_called_once_with(
        {
            'rb.gateway.mcp_method': 'tools/call',
            'rb.gateway.mcp_alias': 'github',
            'rb.gateway.mcp_target': 'get_issue',
            # span attributes are strings; the JSON-RPC code is an int
            'rb.gateway.mcp_error_code': '-32000',
        }
    )


@patch(
    'radicalbit_ai_gateway.utils.trace_attributes.Traceloop.set_association_properties'
)
def test_set_mcp_attributes_omits_unset_fields(mock_set_props):
    with patch(
        'radicalbit_ai_gateway.utils.trace_attributes.get_value',
        return_value=None,
    ):
        set_mcp_attributes(method='ping')

    mock_set_props.assert_called_once_with({'rb.gateway.mcp_method': 'ping'})


@patch(
    'radicalbit_ai_gateway.utils.trace_attributes.Traceloop.set_association_properties'
)
def test_set_mcp_attributes_with_nothing_set_is_a_noop(mock_set_props):
    with patch(
        'radicalbit_ai_gateway.utils.trace_attributes.get_value',
        return_value=None,
    ):
        set_mcp_attributes()

    mock_set_props.assert_not_called()


@patch(
    'radicalbit_ai_gateway.utils.trace_attributes.Traceloop.set_association_properties'
)
def test_set_mcp_attributes_preserves_existing_properties(mock_set_props):
    """Traceloop replaces the whole dict, so the helper must read-merge-write."""
    with patch(
        'radicalbit_ai_gateway.utils.trace_attributes.get_value',
        return_value={'api_key_uuid': 'key-456', 'route_name': 'my-route'},
    ):
        set_mcp_attributes(method='tools/list')

    mock_set_props.assert_called_once_with(
        {
            'api_key_uuid': 'key-456',
            'route_name': 'my-route',
            'rb.gateway.mcp_method': 'tools/list',
        }
    )


@patch(
    'radicalbit_ai_gateway.utils.trace_attributes.Traceloop.set_association_properties'
)
def test_set_mcp_attributes_records_a_zero_error_code(mock_set_props):
    """0 is falsy but a legitimate code — only None means 'unset'."""
    with patch(
        'radicalbit_ai_gateway.utils.trace_attributes.get_value',
        return_value=None,
    ):
        set_mcp_attributes(error_code=0)

    mock_set_props.assert_called_once_with({'rb.gateway.mcp_error_code': '0'})
