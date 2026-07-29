"""Guards that every MCP handler carries a Traceloop span.

This is the regression that already happened once: ``prompts/*`` and
``resources/*`` shipped after the first telemetry pass and went uninstrumented,
so half the dispatch table was invisible in traces. These tests fail when a new
handler is added without a decorator.
"""

import pytest

from radicalbit_ai_gateway.mcp_proxy.upstream_client import McpUpstreamClient
from radicalbit_ai_gateway.services.mcp_service import McpService

# Every dispatch branch in McpService._dispatch that has its own handler
# method. 'ping' is intentionally absent: it returns {} inline, and the
# mcp_request workflow span plus rb.gateway.mcp_method covers it.
SERVICE_SPANS = {
    '_initialize': 'mcp_initialize',
    '_tools_list': 'mcp_tools_list',
    '_tools_call': 'mcp_tools_call',
    '_prompts_list': 'mcp_prompts_list',
    '_prompts_get': 'mcp_prompts_get',
    '_resources_list': 'mcp_resources_list',
    '_resources_read': 'mcp_resources_read',
}

UPSTREAM_SPANS = {
    'list_tools': 'mcp_upstream_list_tools',
    'call_tool': 'mcp_upstream_call_tool',
    'list_prompts': 'mcp_upstream_list_prompts',
    'get_prompt': 'mcp_upstream_get_prompt',
    'list_resources': 'mcp_upstream_list_resources',
    'read_resource': 'mcp_upstream_read_resource',
}


def _span_name(func) -> str | None:
    """Recover a Traceloop entity name from the decorator's closure.

    Traceloop exposes no public accessor for it, so this reads the closed-over
    name. ``traceloop-sdk`` is an open version range, so a future release
    closing over a second string would make this ambiguous; it returns None
    there, and callers must treat None as "can't tell" rather than as a
    mismatch — otherwise an SDK bump reads as a missing decorator, which the
    ``__wrapped__`` assertions check independently anyway.
    """
    names = [
        cell.cell_contents
        for cell in (func.__closure__ or ())
        if isinstance(cell.cell_contents, str)
    ]
    return names[0] if len(names) == 1 else None


def _assert_span_name(func, expected: str) -> None:
    actual = _span_name(func)
    assert actual in (expected, None), (
        f'expected span name {expected!r}, found {actual!r}'
    )


@pytest.mark.parametrize(('method', 'span'), sorted(SERVICE_SPANS.items()))
def test_service_handlers_are_instrumented(method, span):
    func = getattr(McpService, method)
    assert hasattr(func, '__wrapped__'), f'{method} is missing its @task decorator'
    _assert_span_name(func, span)


@pytest.mark.parametrize(('method', 'span'), sorted(UPSTREAM_SPANS.items()))
def test_upstream_calls_are_instrumented(method, span):
    func = getattr(McpUpstreamClient, method)
    assert hasattr(func, '__wrapped__'), f'{method} is missing its @task decorator'
    _assert_span_name(func, span)


def test_handle_post_is_the_root_workflow():
    assert hasattr(McpService.handle_post, '__wrapped__')
    _assert_span_name(McpService.handle_post, 'mcp_request')


def test_every_public_upstream_operation_is_covered():
    """A new upstream operation must be added to UPSTREAM_SPANS above."""
    operations = {
        name
        for name in vars(McpUpstreamClient)
        if not name.startswith('_') and callable(getattr(McpUpstreamClient, name))
    }
    assert operations == set(UPSTREAM_SPANS)
