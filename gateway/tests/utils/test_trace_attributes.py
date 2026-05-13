from unittest.mock import patch

from radicalbit_ai_gateway.utils.trace_attributes import set_trace_attributes


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
