"""Guards that every MCP handler carries a task span.

This is the regression that already happened once: ``prompts/*`` and
``resources/*`` shipped after the first telemetry pass and went uninstrumented,
so half the dispatch table was invisible in traces. These tests fail when a new
handler is added without a decorator.
"""

from unittest.mock import MagicMock

import pytest

from radicalbit_ai_gateway.endpoints.common.admission import Admission
from radicalbit_ai_gateway.endpoints.mcp.route import McpRoute
from radicalbit_ai_gateway.mcp_proxy.upstream_client import McpUpstreamClient
from radicalbit_ai_gateway.services.mcp_service import McpService
from radicalbit_ai_gateway.telemetry.tracing import entity_name

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


@pytest.mark.parametrize(('method', 'span'), sorted(SERVICE_SPANS.items()))
def test_service_handlers_are_instrumented(method, span):
    func = getattr(McpService, method)
    assert hasattr(func, '__wrapped__'), f'{method} is missing its @task decorator'
    assert entity_name(func) == span


@pytest.mark.parametrize(('method', 'span'), sorted(UPSTREAM_SPANS.items()))
def test_upstream_calls_are_instrumented(method, span):
    func = getattr(McpUpstreamClient, method)
    assert hasattr(func, '__wrapped__'), f'{method} is missing its @task decorator'
    assert entity_name(func) == span


def test_the_endpoint_is_the_root_workflow():
    """The span must cover the endpoint, not just the service's dispatch.

    Rate limiting runs in the endpoint, in admission before the dispatch, so a
    429 belongs inside ``mcp_request`` — as it would not if the decorator sat
    on a service method the endpoint calls.
    """
    router = McpRoute.get_mcp_router(
        McpService(upstream_client=MagicMock(spec_set=McpUpstreamClient)),
        MagicMock(spec_set=Admission),
    )
    (route,) = router.routes
    assert hasattr(route.endpoint, '__wrapped__')
    assert entity_name(route.endpoint) == 'mcp_request'


def test_every_public_upstream_operation_is_covered():
    """A new upstream operation must be added to UPSTREAM_SPANS above."""
    operations = {
        name
        for name in vars(McpUpstreamClient)
        if not name.startswith('_') and callable(getattr(McpUpstreamClient, name))
    }
    assert operations == set(UPSTREAM_SPANS)
