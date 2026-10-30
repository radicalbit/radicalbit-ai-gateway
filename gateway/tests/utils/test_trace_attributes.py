from unittest.mock import patch

from opentelemetry import context as context_api, trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from radicalbit_ai_gateway.utils.trace_attributes import (
    in_request_trace,
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
def test_set_trace_attributes_comma_joins_tags(mock_set_props):
    with patch(
        'radicalbit_ai_gateway.utils.trace_attributes.get_value',
        return_value=None,
    ):
        set_trace_attributes(
            request_uuid='req-123',
            tags=['env=prod', 'cost_center=retail'],
        )

    mock_set_props.assert_called_once_with(
        {
            'request_uuid': 'req-123',
            'tags': 'env=prod,cost_center=retail',
        }
    )


@patch(
    'radicalbit_ai_gateway.utils.trace_attributes.Traceloop.set_association_properties'
)
def test_set_trace_attributes_omits_empty_tags(mock_set_props):
    with patch(
        'radicalbit_ai_gateway.utils.trace_attributes.get_value',
        return_value=None,
    ):
        set_trace_attributes(request_uuid='req-123', tags=[])

    mock_set_props.assert_called_once_with({'request_uuid': 'req-123'})


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
def test_set_mcp_attributes_records_the_failed_upstreams(mock_set_props):
    with patch(
        'radicalbit_ai_gateway.utils.trace_attributes.get_value',
        return_value=None,
    ):
        set_mcp_attributes(upstream_failed='github,jira')

    mock_set_props.assert_called_once_with(
        {'rb.gateway.mcp_upstream_failed': 'github,jira'}
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


async def test_in_request_trace_keeps_a_stream_in_the_endpoint_trace():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer('test')
    before = context_api.get_current()

    async def model_call():
        with tracer.start_as_current_span('model'):
            yield 'chunk'

    # The endpoint: its span ends and its context is gone before the
    # response body is iterated.
    endpoint = tracer.start_span('endpoint')
    token = context_api.attach(trace.set_span_in_context(endpoint))
    stream = in_request_trace(model_call())
    unrelated = model_call()
    context_api.detach(token)
    endpoint.end()

    assert [item async for item in stream] == ['chunk']
    assert [item async for item in unrelated] == ['chunk']

    _, model, orphan = exporter.get_finished_spans()
    assert model.context.trace_id == endpoint.context.trace_id
    assert model.parent.span_id == endpoint.context.span_id
    # Without it, the stream's spans open a trace of their own.
    assert orphan.parent is None
    assert context_api.get_current() == before
