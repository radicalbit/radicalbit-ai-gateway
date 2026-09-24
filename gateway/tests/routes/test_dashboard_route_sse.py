from datetime import datetime, timedelta, timezone
from itertools import cycle
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import anyio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from radicalbit_ai_gateway.models.event_dto import (
    ChartDataSeriesDTO,
    CostChartDataDTO,
    CostChartDataSeriesDTO,
    CostDataDTO,
    InvocationChartDataDTO,
    MostExpensiveRouteChartDataDTO,
    MostExpensiveRouteDTO,
    MostRequestedErrorRouteDTO,
    MostRequestedRouteDTO,
    RequestChartDataDTO,
    RouteProgressBarDTO,
    RouteProgressBarsDTO,
    TokenChartDataDTO,
    TokenChartDataSeriesDTO,
    WindowProgressBarDTO,
    WindowStatus,
)
from radicalbit_ai_gateway.models.mcp_usage_dto import (
    McpServerChartDataDTO,
    McpServerChartDataSeriesDTO,
)
from radicalbit_ai_gateway.routes.dashboard_route import DashboardRoute
from radicalbit_ai_gateway.services.event_service import EventService
from radicalbit_ai_gateway.services.mcp_usage_service import McpUsageService
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.services.request_event_service import RequestEventService
from radicalbit_ai_gateway.utils.exceptions import (
    AuthRegistryError,
    GatewayBadRequest,
    GatewayError,
    ProjectNotFoundError,
    auth_registry_exception_handler,
    gateway_exception_handler,
)
from radicalbit_ai_gateway.utils.sse_params import compute_sse_time_range

PROJECT_UUID = UUID('44444444-4444-4444-4444-444444444444')
PROJECT_NAME = 'sse-project'
PROJECT_BASE = f'/public/api/v1/projects/{PROJECT_UUID}'


def _r(route: str) -> str:
    return f'{PROJECT_NAME}/{route}'


@pytest.fixture
def sse_test_app():
    """Create a FastAPI app with the dashboard router for SSE testing."""
    request_event_service = MagicMock(spec_set=RequestEventService)
    event_service = MagicMock(spec_set=EventService)
    project_service = MagicMock(spec_set=ProjectService)
    mcp_usage_service = MagicMock(spec_set=McpUsageService)

    project_mock = MagicMock()
    project_mock.name = PROJECT_NAME
    project_service.get_by_uuid = MagicMock(return_value=project_mock)

    project_entry_mock = MagicMock()
    project_entry_mock.config.routes = {}

    router = DashboardRoute.get_dashboard_router(
        event_service=event_service,
        request_event_service=request_event_service,
        project_service=project_service,
        mcp_usage_service=mcp_usage_service,
    )
    app = FastAPI(title='AI Gateway', debug=True)
    app.add_exception_handler(GatewayError, gateway_exception_handler)
    app.add_exception_handler(GatewayBadRequest, gateway_exception_handler)
    app.add_exception_handler(AuthRegistryError, auth_registry_exception_handler)
    app.include_router(router, prefix='/public/api/v1')
    app.state.project_configs = {PROJECT_NAME: project_entry_mock}
    app.state.routes = {}

    return app, request_event_service, event_service, mcp_usage_service, project_service


class TestStreamMostRequestedRoute:
    """Tests for the SSE /projects/{project_uuid}/routes/most-requested/stream endpoint."""

    @pytest.mark.asyncio
    async def test_stream_most_requested_route(self, sse_test_app):
        """Test SSE endpoint returns correct content type and streams data in SSE format."""
        (
            app,
            request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_dto_1 = MostRequestedRouteDTO(
            name='route-A',
            increment_percentage=50.0,
            chart=RequestChartDataDTO(
                total=100,
                granularity='hours',
                timestamp=[1700000000, 1700003600],
                data=[40, 60],
            ),
        )
        mock_dto_2 = MostRequestedRouteDTO(
            name='route-B',
            increment_percentage=25.0,
            chart=RequestChartDataDTO(
                total=200,
                granularity='hours',
                timestamp=[1700000000, 1700003600],
                data=[80, 120],
            ),
        )
        request_event_service.get_most_requested_route = MagicMock(
            side_effect=cycle([mock_dto_1, mock_dto_2])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET', f'{PROJECT_BASE}/routes/most-requested/stream'
                    ) as response:
                        assert response.status_code == 200
                        assert 'text/event-stream' in response.headers['content-type']

                        events = []
                        current_event_lines = []
                        async for line in response.aiter_lines():
                            if line == '':
                                if current_event_lines:
                                    events.append('\n'.join(current_event_lines))
                                    current_event_lines = []
                                    if len(events) == 2:
                                        break
                            else:
                                current_event_lines.append(line)

                        assert len(events) == 2

                        event1 = events[0]
                        assert 'data:' in event1
                        json_start = event1.find('{')
                        json_end = event1.rfind('}') + 1
                        payload1 = json.loads(event1[json_start:json_end])
                        assert payload1['name'] == 'route-A'
                        assert payload1['incrementPercentage'] == 50.0

                        event2 = events[1]
                        assert 'data:' in event2
                        json_start = event2.find('{')
                        json_end = event2.rfind('}') + 1
                        payload2 = json.loads(event2[json_start:json_end])
                        assert payload2['name'] == 'route-B'
                        assert payload2['incrementPercentage'] == 25.0


class TestStreamMostRequestedErrorRoute:
    """Tests for the SSE /projects/{project_uuid}/routes/most-requested-error/stream endpoint."""

    @pytest.mark.asyncio
    async def test_stream_most_requested_error_route(self, sse_test_app):
        """Test SSE endpoint returns correct content type and streams error route data."""
        (
            app,
            request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_dto_1 = MostRequestedErrorRouteDTO(
            name='error-route-A',
            increment_percentage=75.0,
            chart=RequestChartDataDTO(
                total=0.5,
                granularity='hours',
                timestamp=[1700000000, 1700003600],
                data=[20, 30],
            ),
        )
        mock_dto_2 = MostRequestedErrorRouteDTO(
            name='error-route-B',
            increment_percentage=10.0,
            chart=RequestChartDataDTO(
                total=0.8,
                granularity='hours',
                timestamp=[1700000000, 1700003600],
                data=[30, 50],
            ),
        )
        request_event_service.get_most_requested_error_route = MagicMock(
            side_effect=cycle([mock_dto_1, mock_dto_2])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/most-requested-error/stream',
                    ) as response:
                        assert response.status_code == 200
                        assert 'text/event-stream' in response.headers['content-type']

                        events = []
                        current_event_lines = []
                        async for line in response.aiter_lines():
                            if line == '':
                                if current_event_lines:
                                    events.append('\n'.join(current_event_lines))
                                    current_event_lines = []
                                    if len(events) == 2:
                                        break
                            else:
                                current_event_lines.append(line)

                        assert len(events) == 2

                        event1 = events[0]
                        assert 'data:' in event1
                        json_start = event1.find('{')
                        json_end = event1.rfind('}') + 1
                        payload1 = json.loads(event1[json_start:json_end])
                        assert payload1['name'] == 'error-route-A'
                        assert payload1['incrementPercentage'] == 75.0

                        event2 = events[1]
                        assert 'data:' in event2
                        json_start = event2.find('{')
                        json_end = event2.rfind('}') + 1
                        payload2 = json.loads(event2[json_start:json_end])
                        assert payload2['name'] == 'error-route-B'
                        assert payload2['incrementPercentage'] == 10.0

    @pytest.mark.asyncio
    async def test_stream_yields_empty_json_on_none(self, sse_test_app):
        """Test SSE endpoint yields empty JSON when service returns None."""
        (
            app,
            request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_dto = MostRequestedErrorRouteDTO(
            name='error-route-A',
            increment_percentage=50.0,
            chart=RequestChartDataDTO(
                total=1.0,
                granularity='hours',
                timestamp=[1700000000, 1700003600],
                data=[40, 60],
            ),
        )
        request_event_service.get_most_requested_error_route = MagicMock(
            side_effect=cycle([None, mock_dto])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/most-requested-error/stream',
                    ) as response:
                        assert response.status_code == 200

                        events = []
                        current_event_lines = []
                        async for line in response.aiter_lines():
                            if line == '':
                                if current_event_lines:
                                    events.append('\n'.join(current_event_lines))
                                    current_event_lines = []
                                    if len(events) == 2:
                                        break
                            else:
                                current_event_lines.append(line)

                        assert len(events) == 2
                        payload1 = json.loads(
                            events[0][events[0].find('{') : events[0].rfind('}') + 1]
                        )
                        assert payload1 == {}
                        payload2 = json.loads(
                            events[1][events[1].find('{') : events[1].rfind('}') + 1]
                        )
                        assert payload2['name'] == 'error-route-A'


class TestStreamMostExpensiveRoute:
    """Tests for the SSE /projects/{project_uuid}/routes/most-expensive/stream endpoint."""

    @pytest.mark.asyncio
    async def test_stream_most_expensive_route(self, sse_test_app):
        """Test SSE endpoint returns correct content type and streams data in SSE format."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_dto_1 = MostExpensiveRouteDTO(
            name='route-A',
            increment_percentage=30.0,
            chart=MostExpensiveRouteChartDataDTO(
                total=500.0,
                granularity='hours',
                timestamp=[1700000000, 1700003600],
                data=[200.0, 300.0],
            ),
        )
        mock_dto_2 = MostExpensiveRouteDTO(
            name='route-B',
            increment_percentage=-10.0,
            chart=MostExpensiveRouteChartDataDTO(
                total=150.0,
                granularity='hours',
                timestamp=[1700000000, 1700003600],
                data=[90.0, 60.0],
            ),
        )
        event_service.get_most_expensive_route = MagicMock(
            side_effect=cycle([mock_dto_1, mock_dto_2])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/most-expensive/stream',
                    ) as response:
                        assert response.status_code == 200
                        assert 'text/event-stream' in response.headers['content-type']

                        events = []
                        current_event_lines = []
                        async for line in response.aiter_lines():
                            if line == '':
                                if current_event_lines:
                                    events.append('\n'.join(current_event_lines))
                                    current_event_lines = []
                                    if len(events) == 2:
                                        break
                            else:
                                current_event_lines.append(line)

                        assert len(events) == 2

                        event1 = events[0]
                        assert 'data:' in event1
                        json_start = event1.find('{')
                        json_end = event1.rfind('}') + 1
                        payload1 = json.loads(event1[json_start:json_end])
                        assert payload1['name'] == 'route-A'
                        assert payload1['incrementPercentage'] == 30.0
                        assert payload1['chart']['total'] == 500.0

                        event2 = events[1]
                        assert 'data:' in event2
                        json_start = event2.find('{')
                        json_end = event2.rfind('}') + 1
                        payload2 = json.loads(event2[json_start:json_end])
                        assert payload2['name'] == 'route-B'
                        assert payload2['incrementPercentage'] == -10.0
                        assert payload2['chart']['total'] == 150.0

    @pytest.mark.asyncio
    async def test_stream_yields_empty_json_on_none(self, sse_test_app):
        """Test SSE endpoint yields empty JSON when service returns None."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_dto = MostExpensiveRouteDTO(
            name='route-A',
            increment_percentage=20.0,
            chart=MostExpensiveRouteChartDataDTO(
                total=300.0,
                granularity='days',
                timestamp=[1700000000, 1700086400],
                data=[100.0, 200.0],
            ),
        )
        event_service.get_most_expensive_route = MagicMock(
            side_effect=cycle([None, mock_dto])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/most-expensive/stream',
                    ) as response:
                        assert response.status_code == 200

                        events = []
                        current_event_lines = []
                        async for line in response.aiter_lines():
                            if line == '':
                                if current_event_lines:
                                    events.append('\n'.join(current_event_lines))
                                    current_event_lines = []
                                    if len(events) == 2:
                                        break
                            else:
                                current_event_lines.append(line)

                        assert len(events) == 2
                        payload1 = json.loads(
                            events[0][events[0].find('{') : events[0].rfind('}') + 1]
                        )
                        assert payload1 == {}
                        payload2 = json.loads(
                            events[1][events[1].find('{') : events[1].rfind('}') + 1]
                        )
                        assert payload2['name'] == 'route-A'


class TestStreamCostsChart:
    """Tests for the SSE /projects/{project_uuid}/routes/costs/stream endpoint."""

    @pytest.mark.asyncio
    async def test_stream_costs_chart_all_routes(self, sse_test_app):
        """Test SSE endpoint streams cost chart for all routes when no routes given."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_dto_1 = CostChartDataDTO(
            granularity='hours',
            timestamp=[1736330400, 1736334000],
            data=[CostChartDataSeriesDTO(name='group-1 (route-a)', data=[10.0, 20.0])],
            total=30.0,
        )
        mock_dto_2 = CostChartDataDTO(
            granularity='hours',
            timestamp=[1736330400, 1736334000],
            data=[CostChartDataSeriesDTO(name='group-1 (route-a)', data=[15.0, 25.0])],
            total=40.0,
        )
        event_service.get_costs_chart_data = MagicMock(
            side_effect=cycle([mock_dto_1, mock_dto_2])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/costs/stream',
                        params={'group_by': 'groups'},
                    ) as response:
                        assert response.status_code == 200
                        assert 'text/event-stream' in response.headers['content-type']

                        events = []
                        current_event_lines = []
                        async for line in response.aiter_lines():
                            if line == '':
                                if current_event_lines:
                                    events.append('\n'.join(current_event_lines))
                                    current_event_lines = []
                                    if len(events) == 2:
                                        break
                            else:
                                current_event_lines.append(line)

                        assert len(events) == 2

                        json_start = events[0].find('{')
                        json_end = events[0].rfind('}') + 1
                        payload1 = json.loads(events[0][json_start:json_end])
                        assert payload1['granularity'] == 'hours'
                        assert payload1['timestamp'] == [1736330400, 1736334000]
                        assert payload1['total'] == 30.0
                        assert payload1['data'][0]['name'] == 'group-1 (route-a)'

                        json_start = events[1].find('{')
                        json_end = events[1].rfind('}') + 1
                        payload2 = json.loads(events[1][json_start:json_end])
                        assert payload2['total'] == 40.0

    @pytest.mark.asyncio
    async def test_stream_costs_chart_filtered_routes(self, sse_test_app):
        """Test SSE endpoint passes routes filter to service (prefixed with project name)."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_dto = CostChartDataDTO(
            granularity='days',
            timestamp=[1736208000],
            data=[CostChartDataSeriesDTO(name='api-key-1', data=[50.0])],
            total=50.0,
        )
        event_service.get_costs_chart_data = MagicMock(side_effect=cycle([mock_dto]))

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/costs/stream',
                        params={
                            'routes': ['route-A', 'route-B'],
                            'group_by': 'keys',
                        },
                    ) as response:
                        assert response.status_code == 200

                        events = []
                        current_event_lines = []
                        async for line in response.aiter_lines():
                            if line == '':
                                if current_event_lines:
                                    events.append('\n'.join(current_event_lines))
                                    current_event_lines = []
                                    if len(events) == 1:
                                        break
                            else:
                                current_event_lines.append(line)

                        assert len(events) == 1
                        call_kwargs = (
                            event_service.get_costs_chart_data.call_args.kwargs
                        )
                        assert call_kwargs['route_names'] == [
                            'route-A',
                            'route-B',
                        ]
                        assert call_kwargs['group_by'] == 'keys'

    @pytest.mark.asyncio
    async def test_stream_costs_chart_filtered_tags(self, sse_test_app):
        """Test SSE endpoint passes the tags filter to the service on every tick."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_dto = CostChartDataDTO(
            granularity='days',
            timestamp=[1736208000],
            data=[CostChartDataSeriesDTO(name='api-key-1', data=[50.0])],
            total=50.0,
        )
        event_service.get_costs_chart_data = MagicMock(side_effect=cycle([mock_dto]))

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/costs/stream',
                        params={
                            'group_by': 'keys',
                            'tags': ['env=prod', 'cost_center=retail'],
                        },
                    ) as response:
                        assert response.status_code == 200

                        events = []
                        current_event_lines = []
                        async for line in response.aiter_lines():
                            if line == '':
                                if current_event_lines:
                                    events.append('\n'.join(current_event_lines))
                                    current_event_lines = []
                                    if len(events) == 1:
                                        break
                            else:
                                current_event_lines.append(line)

                        assert len(events) == 1
                        call_kwargs = (
                            event_service.get_costs_chart_data.call_args.kwargs
                        )
                        assert call_kwargs['tags'] == ['env=prod', 'cost_center=retail']

    @pytest.mark.asyncio
    async def test_stream_costs_chart_bad_request_gte_and_from(self, sse_test_app):
        """Test that combining _gte with _from returns 400."""
        (
            app,
            _request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url='http://localhost:9000'
        ) as async_client:
            response = await async_client.get(
                f'{PROJECT_BASE}/routes/costs/stream',
                params={'_gte': 3600, '_from': 1700000000, 'group_by': 'groups'},
            )
            assert response.status_code == 400
            error_data = response.json()
            assert 'error' in error_data
            assert '_gte' in error_data['error']['message'].lower()


class TestStreamCostsSummary:
    """Tests for the SSE /projects/{project_uuid}/routes/costs/summary/stream endpoint."""

    @pytest.mark.asyncio
    async def test_stream_costs_summary_all_routes(self, sse_test_app):
        """Test SSE endpoint streams cost summary for all routes when no routes given."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_dto_1 = CostDataDTO(input_cost=10.0, output_cost=20.0, total_cost=30.0)
        mock_dto_2 = CostDataDTO(input_cost=15.0, output_cost=25.0, total_cost=40.0)
        event_service.get_summary_costs = MagicMock(
            side_effect=cycle([mock_dto_1, mock_dto_2])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET', f'{PROJECT_BASE}/routes/costs/summary/stream'
                    ) as response:
                        assert response.status_code == 200
                        assert 'text/event-stream' in response.headers['content-type']

                        events = []
                        current_event_lines = []
                        async for line in response.aiter_lines():
                            if line == '':
                                if current_event_lines:
                                    events.append('\n'.join(current_event_lines))
                                    current_event_lines = []
                                    if len(events) == 2:
                                        break
                            else:
                                current_event_lines.append(line)

                        assert len(events) == 2

                        json_start = events[0].find('{')
                        json_end = events[0].rfind('}') + 1
                        payload1 = json.loads(events[0][json_start:json_end])
                        assert payload1['inputCost'] == 10.0
                        assert payload1['outputCost'] == 20.0
                        assert payload1['totalCost'] == 30.0

                        json_start = events[1].find('{')
                        json_end = events[1].rfind('}') + 1
                        payload2 = json.loads(events[1][json_start:json_end])
                        assert payload2['inputCost'] == 15.0
                        assert payload2['totalCost'] == 40.0

    @pytest.mark.asyncio
    async def test_stream_costs_summary_filtered_routes(self, sse_test_app):
        """Test SSE endpoint passes routes filter to service."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_dto = CostDataDTO(input_cost=5.0, output_cost=10.0, total_cost=15.0)
        event_service.get_summary_costs = MagicMock(side_effect=cycle([mock_dto]))

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/costs/summary/stream',
                        params={'routes': ['route-A', 'route-B']},
                    ) as response:
                        assert response.status_code == 200

                        events = []
                        current_event_lines = []
                        async for line in response.aiter_lines():
                            if line == '':
                                if current_event_lines:
                                    events.append('\n'.join(current_event_lines))
                                    current_event_lines = []
                                    if len(events) == 1:
                                        break
                            else:
                                current_event_lines.append(line)

                        assert len(events) == 1
                        call_kwargs = event_service.get_summary_costs.call_args.kwargs
                        assert call_kwargs['route_names'] == [
                            'route-A',
                            'route-B',
                        ]

    @pytest.mark.asyncio
    async def test_stream_costs_summary_bad_request_gte_and_from(self, sse_test_app):
        """Test that combining _gte with _from returns 400."""
        (
            app,
            _request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url='http://localhost:9000'
        ) as async_client:
            response = await async_client.get(
                f'{PROJECT_BASE}/routes/costs/summary/stream',
                params={'_gte': 3600, '_from': 1700000000},
            )
            assert response.status_code == 400
            error_data = response.json()
            assert 'error' in error_data
            assert '_gte' in error_data['error']['message'].lower()


class TestSseParamsValidation:
    """Tests for SSE parameter validation (_gte, _from, _to mutual exclusivity)."""

    @pytest.mark.asyncio
    async def test_gte_with_from_returns_400(self, sse_test_app):
        """Test that _gte + _from returns 400 error."""
        (
            app,
            _request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url='http://localhost:9000'
        ) as async_client:
            response = await async_client.get(
                f'{PROJECT_BASE}/routes/most-requested/stream',
                params={'_gte': 3600, '_from': 1700000000},
            )
            assert response.status_code == 400
            error_data = response.json()
            assert 'error' in error_data
            assert '_gte' in error_data['error']['message'].lower()

    @pytest.mark.asyncio
    async def test_gte_with_from_and_to_returns_400(self, sse_test_app):
        """Test that _gte + _from + _to returns 400 error."""
        (
            app,
            _request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url='http://localhost:9000'
        ) as async_client:
            response = await async_client.get(
                f'{PROJECT_BASE}/routes/most-requested/stream',
                params={'_gte': 3600, '_from': 1700000000, '_to': 1700003600},
            )
            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_gte_zero_or_negative_returns_400(self, sse_test_app):
        """Test that _gte <= 0 returns 400 error."""
        (
            app,
            _request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url='http://localhost:9000'
        ) as async_client:
            response = await async_client.get(
                f'{PROJECT_BASE}/routes/most-requested/stream',
                params={'_gte': 0},
            )
            assert response.status_code == 400
            error_data = response.json()
            assert 'positive' in error_data['error']['message'].lower()

            response = await async_client.get(
                f'{PROJECT_BASE}/routes/most-requested/stream',
                params={'_gte': -100},
            )
            assert response.status_code == 400


class TestComputeSseTimeRange:
    """Unit tests for compute_sse_time_range helper function."""

    def test_gte_returns_rolling_window(self):
        """Test that _gte returns (now - _gte, None)."""
        gte_seconds = 3600
        before = datetime.now(timezone.utc) - timedelta(seconds=gte_seconds)
        from_dt, to_dt = compute_sse_time_range(gte_seconds, None, None)
        after = datetime.now(timezone.utc) - timedelta(seconds=gte_seconds)

        assert to_dt is None
        assert before <= from_dt <= after

    def test_from_to_returns_fixed_timestamps(self):
        """Test that _from/_to returns fixed timestamps."""
        from_dt, to_dt = compute_sse_time_range(None, 1700000000, 1700003600)

        assert from_dt is not None
        assert to_dt is not None
        assert from_dt.timestamp() == 1700000000
        assert to_dt.timestamp() == 1700003600

    def test_no_params_returns_none_none(self):
        """Test that no params returns (None, None)."""
        from_dt, to_dt = compute_sse_time_range(None, None, None)

        assert from_dt is None
        assert to_dt is None


class TestSseGteFunctionality:
    """Tests for _gte rolling window functionality."""

    @pytest.mark.asyncio
    async def test_gte_streams_data(self, sse_test_app):
        """Test that _gte parameter works and streams data."""
        (
            app,
            request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_dto = MostRequestedRouteDTO(
            name='route-A',
            increment_percentage=50.0,
            chart=RequestChartDataDTO(
                total=100,
                granularity='hours',
                timestamp=[1700000000, 1700003600],
                data=[40, 60],
            ),
        )
        request_event_service.get_most_requested_route = MagicMock(
            side_effect=cycle([mock_dto])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/most-requested/stream',
                        params={'_gte': 3600},
                    ) as response:
                        assert response.status_code == 200
                        assert 'text/event-stream' in response.headers['content-type']

    @pytest.mark.asyncio
    async def test_gte_rolling_window_updates_datetime(self, sse_test_app):
        """Test that from_datetime changes between iterations when using _gte."""
        (
            app,
            request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        captured_times: list = []

        def capture_from_datetime(*args, **kwargs):
            captured_times.append(kwargs.get('_from'))
            return MostRequestedRouteDTO(
                name='route-A',
                increment_percentage=50.0,
                chart=RequestChartDataDTO(
                    total=100,
                    granularity='hours',
                    timestamp=[1700000000, 1700003600],
                    data=[40, 60],
                ),
            )

        request_event_service.get_most_requested_route = MagicMock(
            side_effect=capture_from_datetime
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/most-requested/stream',
                        params={'_gte': 3600},
                    ) as response:
                        assert response.status_code == 200

                        events = []
                        current_event_lines = []
                        async for line in response.aiter_lines():
                            if line == '':
                                if current_event_lines:
                                    events.append('\n'.join(current_event_lines))
                                    current_event_lines = []
                                    if len(events) == 2:
                                        break
                            else:
                                current_event_lines.append(line)

        assert len(captured_times) >= 2
        assert captured_times[0] != captured_times[1]


class TestSseBackwardCompatibility:
    """Tests to ensure backward compatibility with _from/_to parameters."""

    @pytest.mark.asyncio
    async def test_from_to_still_works(self, sse_test_app):
        """Test that _from/_to parameters still work as before."""
        (
            app,
            request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_dto = MostRequestedRouteDTO(
            name='route-A',
            increment_percentage=50.0,
            chart=RequestChartDataDTO(
                total=100,
                granularity='hours',
                timestamp=[1700000000, 1700003600],
                data=[40, 60],
            ),
        )
        request_event_service.get_most_requested_route = MagicMock(
            side_effect=cycle([mock_dto])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/most-requested/stream',
                        params={'_from': 1700000000, '_to': 1700003600},
                    ) as response:
                        assert response.status_code == 200
                        assert 'text/event-stream' in response.headers['content-type']

    @pytest.mark.asyncio
    async def test_no_params_still_works(self, sse_test_app):
        """Test that no parameters still works (default behavior)."""
        (
            app,
            request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_dto = MostRequestedRouteDTO(
            name='route-A',
            increment_percentage=50.0,
            chart=RequestChartDataDTO(
                total=100,
                granularity='hours',
                timestamp=[1700000000, 1700003600],
                data=[40, 60],
            ),
        )
        request_event_service.get_most_requested_route = MagicMock(
            side_effect=cycle([mock_dto])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET', f'{PROJECT_BASE}/routes/most-requested/stream'
                    ) as response:
                        assert response.status_code == 200
                        assert 'text/event-stream' in response.headers['content-type']


class TestStreamLimitsProgress:
    """Tests for the SSE /projects/{project_uuid}/routes/limits/stream endpoint."""

    @pytest.mark.asyncio
    async def test_returns_correct_sse_payload(self, sse_test_app):
        """Endpoint streams the payload returned by event_service.get_route_limits_progress."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_result = [
            RouteProgressBarDTO(
                route_name='my-route',
                progress_bar=RouteProgressBarsDTO(
                    budget=WindowProgressBarDTO(
                        window_length=3600,
                        window_start_time=1_700_000_000,
                        window_end_time=1_700_003_600,
                        window_size=10.0,
                        window_filled_size=7.0,
                        window_filled_percentage=70.0,
                    ),
                    rate=WindowProgressBarDTO(
                        window_length=60,
                        window_start_time=1_700_003_540,
                        window_end_time=1_700_003_600,
                        window_size=100.0,
                        window_filled_size=60.0,
                        window_filled_percentage=60.0,
                    ),
                ),
            )
        ]
        event_service.get_route_limits_progress = AsyncMock(return_value=mock_result)

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.asyncio.sleep',
            new_callable=AsyncMock,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as client:
                with anyio.move_on_after(2):
                    async with client.stream(
                        'GET', f'{PROJECT_BASE}/routes/limits/stream'
                    ) as response:
                        assert response.status_code == 200
                        assert 'text/event-stream' in response.headers['content-type']

                        events = []
                        current_lines = []
                        async for line in response.aiter_lines():
                            if line == '':
                                if current_lines:
                                    events.append('\n'.join(current_lines))
                                    current_lines = []
                                    if len(events) == 1:
                                        break
                            else:
                                current_lines.append(line)

                        assert len(events) == 1
                        raw = events[0]
                        assert 'data:' in raw
                        payload = json.loads(raw[raw.find('[') : raw.rfind(']') + 1])
                        assert len(payload) == 1
                        entry = payload[0]
                        assert entry['routeName'] == 'my-route'
                        pb = entry['progressBar']
                        assert pb['budget']['windowLength'] == 3600
                        assert pb['budget']['windowSize'] == pytest.approx(10.0)
                        assert pb['budget']['windowFilledSize'] == pytest.approx(7.0)
                        assert pb['budget']['windowFilledPercentage'] == pytest.approx(
                            70.0
                        )
                        assert pb['budget']['windowStatus'] == WindowStatus.OK
                        assert pb['rate']['windowSize'] == pytest.approx(100.0)
                        assert pb['rate']['windowStatus'] == WindowStatus.OK
                        assert 'tokenInput' not in pb
                        assert 'tokenOutput' not in pb

    @pytest.mark.asyncio
    async def test_filters_by_routes(self, sse_test_app):
        """Endpoint passes routes query param to the service (prefixed with project name)."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        event_service.get_route_limits_progress = AsyncMock(return_value=[])

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.asyncio.sleep',
            new_callable=AsyncMock,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as client:
                with anyio.move_on_after(2):
                    async with client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/limits/stream',
                        params=[('routes', 'route-a'), ('routes', 'route-c')],
                    ) as response:
                        async for _ in response.aiter_lines():
                            break

                        call_args = event_service.get_route_limits_progress.call_args
                        assert call_args[0][1] == [_r('route-a'), _r('route-c')]

    @pytest.mark.asyncio
    async def test_progress_bar_absent_when_none(self, sse_test_app):
        """ProgressBar key is absent in SSE payload when progress_bar is None."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        event_service.get_route_limits_progress = AsyncMock(
            return_value=[RouteProgressBarDTO(route_name='my-route', progress_bar=None)]
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.asyncio.sleep',
            new_callable=AsyncMock,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as client:
                with anyio.move_on_after(2):
                    async with client.stream(
                        'GET', f'{PROJECT_BASE}/routes/limits/stream'
                    ) as response:
                        events = []
                        current_lines = []
                        async for line in response.aiter_lines():
                            if line == '':
                                if current_lines:
                                    events.append('\n'.join(current_lines))
                                    current_lines = []
                                    if len(events) == 1:
                                        break
                            else:
                                current_lines.append(line)

                        raw = events[0]
                        payload = json.loads(raw[raw.find('[') : raw.rfind(']') + 1])
                        assert payload[0]['routeName'] == 'my-route'
                        assert 'progressBar' not in payload[0]

    @pytest.mark.asyncio
    async def test_forwards_window_statuses_to_service(self, sse_test_app):
        """window_statuses query params are forwarded to get_route_limits_progress."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        event_service.get_route_limits_progress = AsyncMock(return_value=[])

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.asyncio.sleep',
            new_callable=AsyncMock,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as client:
                with anyio.move_on_after(2):
                    async with client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/limits/stream',
                        params=[
                            ('window_statuses', 'ok'),
                            ('window_statuses', 'warning'),
                        ],
                    ) as response:
                        async for _ in response.aiter_lines():
                            break

                        call_args = event_service.get_route_limits_progress.call_args
                        assert call_args[0][2] == [
                            WindowStatus.OK,
                            WindowStatus.WARNING,
                        ]


class TestStreamInvocations:
    """Tests for the SSE /projects/{project_uuid}/routes/invocations/stream endpoint."""

    @pytest.mark.asyncio
    async def test_returns_correct_sse_payload(self, sse_test_app):
        """Endpoint streams InvocationChartDataDTO returned by event_service."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_result = InvocationChartDataDTO(
            granularity='hours',
            timestamp=[1700000000, 1700003600],
            data=[3.0, 7.0],
            total=10,
        )
        event_service.get_invocation_chart_data = MagicMock(return_value=mock_result)

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as client:
                with anyio.move_on_after(2):
                    async with client.stream(
                        'GET', f'{PROJECT_BASE}/routes/invocations/stream'
                    ) as response:
                        assert response.status_code == 200
                        assert 'text/event-stream' in response.headers['content-type']

                        events = []
                        current_lines = []
                        async for line in response.aiter_lines():
                            if line == '':
                                if current_lines:
                                    events.append('\n'.join(current_lines))
                                    current_lines = []
                                    if len(events) == 1:
                                        break
                            else:
                                current_lines.append(line)

                        assert len(events) == 1
                        raw = events[0]
                        assert 'data:' in raw
                        json_start = raw.find('{')
                        json_end = raw.rfind('}') + 1
                        payload = json.loads(raw[json_start:json_end])
                        assert payload['granularity'] == 'hours'
                        assert payload['timestamp'] == [1700000000, 1700003600]
                        assert payload['data'] == [3.0, 7.0]
                        assert payload['total'] == 10

                        call_kwargs = (
                            event_service.get_invocation_chart_data.call_args.kwargs
                        )
                        assert call_kwargs['include_models'] is False

    @pytest.mark.asyncio
    async def test_filters_by_routes(self, sse_test_app):
        """Endpoint passes routes query param to the service (prefixed with project name)."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_result = InvocationChartDataDTO(
            granularity='weeks', timestamp=[], data=[], total=0
        )
        event_service.get_invocation_chart_data = MagicMock(return_value=mock_result)

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as client:
                with anyio.move_on_after(2):
                    async with client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/invocations/stream',
                        params=[('routes', 'route-a'), ('routes', 'route-c')],
                    ) as response:
                        async for _ in response.aiter_lines():
                            break

                        call_kwargs = (
                            event_service.get_invocation_chart_data.call_args.kwargs
                        )
                        assert call_kwargs['route_names'] == [
                            'route-a',
                            'route-c',
                        ]

    @pytest.mark.asyncio
    async def test_all_routes_when_no_filter(self, sse_test_app):
        """Service is called with routes=None when no routes param is provided."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_result = InvocationChartDataDTO(
            granularity='weeks', timestamp=[], data=[], total=0
        )
        event_service.get_invocation_chart_data = MagicMock(return_value=mock_result)

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as client:
                with anyio.move_on_after(2):
                    async with client.stream(
                        'GET', f'{PROJECT_BASE}/routes/invocations/stream'
                    ) as response:
                        async for _ in response.aiter_lines():
                            break

                        call_kwargs = (
                            event_service.get_invocation_chart_data.call_args.kwargs
                        )
                        assert call_kwargs['route_names'] is None

    @pytest.mark.asyncio
    async def test_respects_from_to_params(self, sse_test_app):
        """Endpoint forwards _from and _to unix timestamps to the service as datetimes."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_result = InvocationChartDataDTO(
            granularity='hours', timestamp=[], data=[], total=0
        )
        event_service.get_invocation_chart_data = MagicMock(return_value=mock_result)

        _from_ts = 1704067200  # 2024-01-01T00:00:00Z
        _to_ts = 1704153600  # 2024-01-02T00:00:00Z
        expected_from = datetime.fromtimestamp(_from_ts, tz=timezone.utc)
        expected_to = datetime.fromtimestamp(_to_ts, tz=timezone.utc)

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as client:
                with anyio.move_on_after(2):
                    async with client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/invocations/stream',
                        params={'_from': _from_ts, '_to': _to_ts},
                    ) as response:
                        async for _ in response.aiter_lines():
                            break

                        call_kwargs = (
                            event_service.get_invocation_chart_data.call_args.kwargs
                        )
                        assert call_kwargs['_from'] == expected_from
                        assert call_kwargs['_to'] == expected_to

    @pytest.mark.asyncio
    async def test_gte_streams_data(self, sse_test_app):
        """Endpoint accepts _gte as a rolling window and passes datetimes to the service."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_result = InvocationChartDataDTO(
            granularity='hours', timestamp=[], data=[], total=0
        )
        event_service.get_invocation_chart_data = MagicMock(return_value=mock_result)

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as client:
                with anyio.move_on_after(2):
                    async with client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/invocations/stream',
                        params={'_gte': 3600},
                    ) as response:
                        async for _ in response.aiter_lines():
                            break

                        call_kwargs = (
                            event_service.get_invocation_chart_data.call_args.kwargs
                        )
                        assert call_kwargs['_from'] is not None
                        assert call_kwargs['_to'] is None

    @pytest.mark.asyncio
    async def test_gte_and_from_returns_400(self, sse_test_app):
        """Passing both _gte and _from returns 400 (mutually exclusive)."""
        (
            app,
            _request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url='http://localhost:9000'
        ) as client:
            response = await client.get(
                f'{PROJECT_BASE}/routes/invocations/stream',
                params={'_gte': 3600, '_from': 1704067200},
            )
            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_include_models_false_returns_flat_data(self, sse_test_app):
        """With include_models=False, payload data is a flat list of numbers."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_result = InvocationChartDataDTO(
            granularity='hours',
            timestamp=[1700000000, 1700003600],
            data=[5.0, 3.0],
            total=8,
        )
        event_service.get_invocation_chart_data = MagicMock(return_value=mock_result)

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as client:
                with anyio.move_on_after(2):
                    async with client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/invocations/stream',
                        params={'include_models': 'false'},
                    ) as response:
                        async for _ in response.aiter_lines():
                            break

                        call_kwargs = (
                            event_service.get_invocation_chart_data.call_args.kwargs
                        )
                        assert call_kwargs['include_models'] is False

    @pytest.mark.asyncio
    async def test_include_models_true_returns_series_data(self, sse_test_app):
        """With include_models=True, payload data contains per-model series."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_result = InvocationChartDataDTO(
            granularity='hours',
            timestamp=[1700000000, 1700003600],
            data=[
                ChartDataSeriesDTO(name='gpt-4', data=[2.0, 1.0]),
                ChartDataSeriesDTO(name='gpt-3.5', data=[3.0, 2.0]),
            ],
            total=8,
        )
        event_service.get_invocation_chart_data = MagicMock(return_value=mock_result)

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as client:
                with anyio.move_on_after(2):
                    async with client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/invocations/stream',
                        params={'include_models': 'true'},
                    ) as response:
                        events = []
                        current_lines = []
                        async for line in response.aiter_lines():
                            if line == '':
                                if current_lines:
                                    events.append('\n'.join(current_lines))
                                    current_lines = []
                                    if len(events) == 1:
                                        break
                            else:
                                current_lines.append(line)

                        call_kwargs = (
                            event_service.get_invocation_chart_data.call_args.kwargs
                        )
                        assert call_kwargs['include_models'] is True

                        assert len(events) == 1
                        raw = events[0]
                        json_start = raw.find('{')
                        json_end = raw.rfind('}') + 1
                        payload = json.loads(raw[json_start:json_end])
                        assert isinstance(payload['data'], list)
                        assert payload['data'][0]['name'] == 'gpt-4'
                        assert payload['data'][0]['data'] == [2.0, 1.0]
                        assert payload['data'][1]['name'] == 'gpt-3.5'


class TestStreamTokens:
    """Tests for the SSE /projects/{project_uuid}/routes/tokens/stream endpoint."""

    @pytest.mark.asyncio
    async def test_returns_correct_sse_payload(self, sse_test_app):
        """Endpoint streams TokenChartDataDTO returned by event_service."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_result = TokenChartDataDTO(
            granularity='hours',
            timestamp=[1700000000, 1700003600],
            data=[
                TokenChartDataSeriesDTO(name='INPUT', data=[100, 150]),
                TokenChartDataSeriesDTO(name='OUTPUT', data=[50, 75]),
            ],
            total=375,
        )
        event_service.get_token_chart_data = MagicMock(return_value=mock_result)

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as client:
                with anyio.move_on_after(2):
                    async with client.stream(
                        'GET', f'{PROJECT_BASE}/routes/tokens/stream'
                    ) as response:
                        assert response.status_code == 200
                        assert 'text/event-stream' in response.headers['content-type']

                        events = []
                        current_lines = []
                        async for line in response.aiter_lines():
                            if line == '':
                                if current_lines:
                                    events.append('\n'.join(current_lines))
                                    current_lines = []
                                    if len(events) == 1:
                                        break
                            else:
                                current_lines.append(line)

                        assert len(events) == 1
                        raw = events[0]
                        assert 'data:' in raw
                        json_start = raw.find('{')
                        json_end = raw.rfind('}') + 1
                        payload = json.loads(raw[json_start:json_end])
                        assert payload['granularity'] == 'hours'
                        assert payload['timestamp'] == [1700000000, 1700003600]
                        assert payload['total'] == 375
                        assert len(payload['data']) == 2
                        assert payload['data'][0]['name'] == 'INPUT'
                        assert payload['data'][0]['data'] == [100, 150]
                        assert payload['data'][1]['name'] == 'OUTPUT'
                        assert payload['data'][1]['data'] == [50, 75]

    @pytest.mark.asyncio
    async def test_filters_by_routes(self, sse_test_app):
        """Endpoint passes routes query param to the service (prefixed with project name)."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_result = TokenChartDataDTO(
            granularity='weeks', timestamp=[], data=[], total=0
        )
        event_service.get_token_chart_data = MagicMock(return_value=mock_result)

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as client:
                with anyio.move_on_after(2):
                    async with client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/tokens/stream',
                        params=[('routes', 'route-a'), ('routes', 'route-c')],
                    ) as response:
                        async for _ in response.aiter_lines():
                            break

                        call_kwargs = (
                            event_service.get_token_chart_data.call_args.kwargs
                        )
                        assert call_kwargs['route_names'] == [
                            'route-a',
                            'route-c',
                        ]

    @pytest.mark.asyncio
    async def test_all_routes_when_no_filter(self, sse_test_app):
        """Service is called with routes=None when no routes param is provided."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_result = TokenChartDataDTO(
            granularity='weeks', timestamp=[], data=[], total=0
        )
        event_service.get_token_chart_data = MagicMock(return_value=mock_result)

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as client:
                with anyio.move_on_after(2):
                    async with client.stream(
                        'GET', f'{PROJECT_BASE}/routes/tokens/stream'
                    ) as response:
                        async for _ in response.aiter_lines():
                            break

                        call_kwargs = (
                            event_service.get_token_chart_data.call_args.kwargs
                        )
                        assert call_kwargs['route_names'] is None

    @pytest.mark.asyncio
    async def test_respects_from_to_params(self, sse_test_app):
        """Endpoint forwards _from and _to unix timestamps to the service as datetimes."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_result = TokenChartDataDTO(
            granularity='hours', timestamp=[], data=[], total=0
        )
        event_service.get_token_chart_data = MagicMock(return_value=mock_result)

        _from_ts = 1704067200  # 2024-01-01T00:00:00Z
        _to_ts = 1704153600  # 2024-01-02T00:00:00Z
        expected_from = datetime.fromtimestamp(_from_ts, tz=timezone.utc)
        expected_to = datetime.fromtimestamp(_to_ts, tz=timezone.utc)

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as client:
                with anyio.move_on_after(2):
                    async with client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/tokens/stream',
                        params={'_from': _from_ts, '_to': _to_ts},
                    ) as response:
                        async for _ in response.aiter_lines():
                            break

                        call_kwargs = (
                            event_service.get_token_chart_data.call_args.kwargs
                        )
                        assert call_kwargs['_from'] == expected_from
                        assert call_kwargs['_to'] == expected_to

    @pytest.mark.asyncio
    async def test_gte_streams_data(self, sse_test_app):
        """Endpoint accepts _gte as a rolling window and passes datetimes to the service."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_result = TokenChartDataDTO(
            granularity='hours', timestamp=[], data=[], total=0
        )
        event_service.get_token_chart_data = MagicMock(return_value=mock_result)

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as client:
                with anyio.move_on_after(2):
                    async with client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/tokens/stream',
                        params={'_gte': 3600},
                    ) as response:
                        async for _ in response.aiter_lines():
                            break

                        call_kwargs = (
                            event_service.get_token_chart_data.call_args.kwargs
                        )
                        assert call_kwargs['_from'] is not None
                        assert call_kwargs['_to'] is None

    @pytest.mark.asyncio
    async def test_gte_and_from_returns_400(self, sse_test_app):
        """Passing both _gte and _from returns 400 (mutually exclusive)."""
        (
            app,
            _request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url='http://localhost:9000'
        ) as client:
            response = await client.get(
                f'{PROJECT_BASE}/routes/tokens/stream',
                params={'_gte': 3600, '_from': 1704067200},
            )
            assert response.status_code == 400


class TestStreamCostsChartByEntity:
    """Tests for the entity drill-down SSE endpoints (key/group/model)."""

    @pytest.mark.asyncio
    async def test_stream_costs_chart_by_key(self, sse_test_app):
        """Test /projects/{uuid}/routes/costs/key/{key_uuid}/stream streams cost chart."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app
        key_uuid = '550e8400-e29b-41d4-a716-446655440001'

        mock_dto = CostChartDataDTO(
            granularity='hours',
            timestamp=[1736330400, 1736334000],
            data=[
                CostChartDataSeriesDTO(name='route-A', data=[10.0, 20.0]),
                CostChartDataSeriesDTO(name='route-B', data=[5.0, 15.0]),
            ],
            total=50.0,
        )
        event_service.get_costs_chart_data_by_route = MagicMock(
            side_effect=cycle([mock_dto])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/costs/key/{key_uuid}/stream',
                    ) as response:
                        assert response.status_code == 200
                        assert 'text/event-stream' in response.headers['content-type']

                        events = []
                        current_event_lines = []
                        async for line in response.aiter_lines():
                            if line == '':
                                if current_event_lines:
                                    events.append('\n'.join(current_event_lines))
                                    current_event_lines = []
                                    if len(events) == 1:
                                        break
                            else:
                                current_event_lines.append(line)

                        assert len(events) == 1
                        json_start = events[0].find('{')
                        json_end = events[0].rfind('}') + 1
                        payload = json.loads(events[0][json_start:json_end])
                        assert payload['granularity'] == 'hours'
                        assert payload['total'] == 50.0
                        assert payload['data'][0]['name'] == 'route-A'

                        call_kwargs = (
                            event_service.get_costs_chart_data_by_route.call_args.kwargs
                        )
                        assert call_kwargs['entity_column'] == 'API_KEY_UUID'
                        assert call_kwargs['entity_value'] == key_uuid
                        assert call_kwargs['route_names'] is None

    @pytest.mark.asyncio
    async def test_stream_costs_chart_by_key_with_routes_filter(self, sse_test_app):
        """Test /projects/{uuid}/routes/costs/key/{key_uuid}/stream filters by routes."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app
        key_uuid = '550e8400-e29b-41d4-a716-446655440001'

        mock_dto = CostChartDataDTO(
            granularity='hours',
            timestamp=[1736330400],
            data=[CostChartDataSeriesDTO(name='route-A', data=[10.0])],
            total=10.0,
        )
        event_service.get_costs_chart_data_by_route = MagicMock(
            side_effect=cycle([mock_dto])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/costs/key/{key_uuid}/stream',
                        params={'routes': ['route-A', 'route-B']},
                    ) as response:
                        assert response.status_code == 200

                        async for _ in response.aiter_lines():
                            break

                        call_kwargs = (
                            event_service.get_costs_chart_data_by_route.call_args.kwargs
                        )
                        assert call_kwargs['route_names'] == [
                            'route-A',
                            'route-B',
                        ]

    @pytest.mark.asyncio
    async def test_stream_costs_chart_by_group(self, sse_test_app):
        """Test /projects/{uuid}/routes/costs/group/{group_uuid}/stream streams cost chart."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app
        group_uuid = '550e8400-e29b-41d4-a716-446655440002'

        mock_dto = CostChartDataDTO(
            granularity='days',
            timestamp=[1736208000],
            data=[CostChartDataSeriesDTO(name='route-A', data=[100.0])],
            total=100.0,
        )
        event_service.get_costs_chart_data_by_route = MagicMock(
            side_effect=cycle([mock_dto])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/costs/group/{group_uuid}/stream',
                    ) as response:
                        assert response.status_code == 200

                        async for _ in response.aiter_lines():
                            break

                        call_kwargs = (
                            event_service.get_costs_chart_data_by_route.call_args.kwargs
                        )
                        assert call_kwargs['entity_column'] == 'GROUP_UUID'
                        assert call_kwargs['entity_value'] == group_uuid
                        assert call_kwargs['route_names'] is None

    @pytest.mark.asyncio
    async def test_stream_costs_chart_by_group_with_routes_filter(self, sse_test_app):
        """Test /projects/{uuid}/routes/costs/group/{group_uuid}/stream filters by routes."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app
        group_uuid = '550e8400-e29b-41d4-a716-446655440002'

        mock_dto = CostChartDataDTO(
            granularity='days',
            timestamp=[1736208000],
            data=[CostChartDataSeriesDTO(name='route-A', data=[100.0])],
            total=100.0,
        )
        event_service.get_costs_chart_data_by_route = MagicMock(
            side_effect=cycle([mock_dto])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/costs/group/{group_uuid}/stream',
                        params={'routes': ['route-A']},
                    ) as response:
                        assert response.status_code == 200

                        async for _ in response.aiter_lines():
                            break

                        call_kwargs = (
                            event_service.get_costs_chart_data_by_route.call_args.kwargs
                        )
                        assert call_kwargs['route_names'] == ['route-A']

    @pytest.mark.asyncio
    async def test_stream_costs_chart_by_model(self, sse_test_app):
        """Test /projects/{uuid}/routes/costs/model/{model_id}/stream streams cost chart."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_dto = CostChartDataDTO(
            granularity='hours',
            timestamp=[1736330400],
            data=[CostChartDataSeriesDTO(name='route-A', data=[42.0])],
            total=42.0,
        )
        event_service.get_costs_chart_data_by_route = MagicMock(
            side_effect=cycle([mock_dto])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/costs/model/gpt-4o/stream',
                    ) as response:
                        assert response.status_code == 200

                        async for _ in response.aiter_lines():
                            break

                        call_kwargs = (
                            event_service.get_costs_chart_data_by_route.call_args.kwargs
                        )
                        assert call_kwargs['entity_column'] == 'MODEL_ID'
                        assert call_kwargs['entity_value'] == 'gpt-4o'
                        assert call_kwargs['route_names'] is None

    @pytest.mark.asyncio
    async def test_stream_costs_chart_by_model_with_routes_filter(self, sse_test_app):
        """Test /projects/{uuid}/routes/costs/model/{model_id}/stream filters by routes."""
        (
            app,
            _request_event_service,
            event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_dto = CostChartDataDTO(
            granularity='hours',
            timestamp=[1736330400],
            data=[CostChartDataSeriesDTO(name='route-A', data=[42.0])],
            total=42.0,
        )
        event_service.get_costs_chart_data_by_route = MagicMock(
            side_effect=cycle([mock_dto])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    async with async_client.stream(
                        'GET',
                        f'{PROJECT_BASE}/routes/costs/model/gpt-4o/stream',
                        params={'routes': ['route-A', 'route-B']},
                    ) as response:
                        assert response.status_code == 200

                        async for _ in response.aiter_lines():
                            break

                        call_kwargs = (
                            event_service.get_costs_chart_data_by_route.call_args.kwargs
                        )
                        assert call_kwargs['route_names'] == [
                            'route-A',
                            'route-B',
                        ]

    @pytest.mark.asyncio
    async def test_stream_costs_chart_by_key_gte_and_from_returns_400(
        self, sse_test_app
    ):
        """Passing both _gte and _from returns 400 (mutually exclusive)."""
        (
            app,
            _request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app
        key_uuid = '550e8400-e29b-41d4-a716-446655440001'

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url='http://localhost:9000'
        ) as client:
            response = await client.get(
                f'{PROJECT_BASE}/routes/costs/key/{key_uuid}/stream',
                params={'_gte': 3600, '_from': 1704067200},
            )
            assert response.status_code == 400
            assert 'error' in response.json()


class TestStreamMcpServersChart:
    """Tests for the SSE /projects/{project_uuid}/routes/mcp/servers/stream endpoint."""

    @staticmethod
    async def _read_events(async_client, params, wanted: int = 1):
        events = []
        async with async_client.stream(
            'GET',
            f'{PROJECT_BASE}/routes/mcp/servers/stream',
            params=params,
        ) as response:
            assert response.status_code == 200
            assert 'text/event-stream' in response.headers['content-type']
            current_event_lines = []
            async for line in response.aiter_lines():
                if line == '':
                    if current_event_lines:
                        events.append('\n'.join(current_event_lines))
                        current_event_lines = []
                        if len(events) == wanted:
                            break
                else:
                    current_event_lines.append(line)
        return events

    @staticmethod
    def _payload(event: str) -> dict:
        return json.loads(event[event.find('{') : event.rfind('}') + 1])

    @pytest.mark.asyncio
    async def test_stream_mcp_servers_all_routes(self, sse_test_app):
        """Every tick carries a fresh chart for the whole project."""
        (
            app,
            _request_event_service,
            _event_service,
            mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mock_dto_1 = McpServerChartDataDTO(
            granularity='hours',
            timestamp=[1736330400, 1736334000],
            data=[McpServerChartDataSeriesDTO(name='files', data=[2, 3])],
            total=5,
        )
        mock_dto_2 = McpServerChartDataDTO(
            granularity='hours',
            timestamp=[1736330400, 1736334000],
            data=[McpServerChartDataSeriesDTO(name='files', data=[2, 6])],
            total=8,
        )
        mcp_usage_service.get_mcp_server_chart_data = MagicMock(
            side_effect=cycle([mock_dto_1, mock_dto_2])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    events = await self._read_events(async_client, {}, wanted=2)

                    assert len(events) == 2
                    payload1 = self._payload(events[0])
                    assert payload1['granularity'] == 'hours'
                    assert payload1['timestamp'] == [1736330400, 1736334000]
                    assert payload1['total'] == 5
                    assert payload1['data'][0]['name'] == 'files'
                    assert payload1['data'][0]['data'] == [2, 3]
                    assert self._payload(events[1])['total'] == 8

    @pytest.mark.asyncio
    async def test_stream_mcp_servers_defaults_to_services(self, sse_test_app):
        """No group_by means one series per MCP service."""
        (
            app,
            _request_event_service,
            _event_service,
            mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mcp_usage_service.get_mcp_server_chart_data = MagicMock(
            side_effect=cycle(
                [
                    McpServerChartDataDTO(
                        granularity='days', timestamp=[1736208000], data=[], total=0
                    )
                ]
            )
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    events = await self._read_events(async_client, {})

                    assert len(events) == 1
                    call_kwargs = (
                        mcp_usage_service.get_mcp_server_chart_data.call_args.kwargs
                    )
                    assert call_kwargs['group_by'] == 'services'

    @pytest.mark.parametrize('group_by', ['services', 'groups', 'keys'])
    @pytest.mark.asyncio
    async def test_stream_mcp_servers_each_grouping(self, sse_test_app, group_by):
        """Each grouping reaches the service as asked."""
        (
            app,
            _request_event_service,
            _event_service,
            mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mcp_usage_service.get_mcp_server_chart_data = MagicMock(
            side_effect=cycle(
                [
                    McpServerChartDataDTO(
                        granularity='days',
                        timestamp=[1736208000],
                        data=[
                            McpServerChartDataSeriesDTO(
                                name='retail',
                                uuid=UUID('550e8400-e29b-41d4-a716-446655440003'),
                                data=[4],
                            )
                        ],
                        total=4,
                    )
                ]
            )
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    events = await self._read_events(
                        async_client, {'group_by': group_by}
                    )

                    assert len(events) == 1
                    payload = self._payload(events[0])
                    assert payload['data'][0]['uuid'] == (
                        '550e8400-e29b-41d4-a716-446655440003'
                    )
                    call_kwargs = (
                        mcp_usage_service.get_mcp_server_chart_data.call_args.kwargs
                    )
                    assert call_kwargs['group_by'] == group_by

    @pytest.mark.asyncio
    async def test_stream_mcp_servers_filtered_routes(self, sse_test_app):
        """The routes filter reaches the service on every tick."""
        (
            app,
            _request_event_service,
            _event_service,
            mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mcp_usage_service.get_mcp_server_chart_data = MagicMock(
            side_effect=cycle(
                [
                    McpServerChartDataDTO(
                        granularity='days',
                        timestamp=[1736208000],
                        data=[McpServerChartDataSeriesDTO(name='files', data=[7])],
                        total=7,
                    )
                ]
            )
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    events = await self._read_events(
                        async_client, {'routes': ['route-A', 'route-B']}
                    )

                    assert len(events) == 1
                    payload = self._payload(events[0])
                    assert payload['total'] == 7
                    assert payload['data'][0]['data'] == [7]
                    call_kwargs = (
                        mcp_usage_service.get_mcp_server_chart_data.call_args.kwargs
                    )
                    assert call_kwargs['route_names'] == ['route-A', 'route-B']

    @pytest.mark.asyncio
    async def test_stream_mcp_servers_filtered_tags(self, sse_test_app):
        """The tags filter reaches the service on every tick."""
        (
            app,
            _request_event_service,
            _event_service,
            mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mcp_usage_service.get_mcp_server_chart_data = MagicMock(
            side_effect=cycle(
                [
                    McpServerChartDataDTO(
                        granularity='days',
                        timestamp=[1736208000],
                        data=[McpServerChartDataSeriesDTO(name='files', data=[3])],
                        total=3,
                    )
                ]
            )
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    events = await self._read_events(
                        async_client,
                        {'tags': ['env=prod', 'cost_center=retail']},
                    )

                    assert len(events) == 1
                    payload = self._payload(events[0])
                    assert payload['total'] == 3
                    assert payload['data'][0]['data'] == [3]
                    call_kwargs = (
                        mcp_usage_service.get_mcp_server_chart_data.call_args.kwargs
                    )
                    assert call_kwargs['tags'] == ['env=prod', 'cost_center=retail']

    @pytest.mark.asyncio
    async def test_stream_mcp_servers_rolling_window_moves(self, sse_test_app):
        """A look-back window is recomputed on every tick, not frozen."""
        (
            app,
            _request_event_service,
            _event_service,
            mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mcp_usage_service.get_mcp_server_chart_data = MagicMock(
            side_effect=cycle(
                [
                    McpServerChartDataDTO(
                        granularity='hours', timestamp=[1736208000], data=[], total=0
                    )
                ]
            )
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    events = await self._read_events(
                        async_client, {'_gte': 3600}, wanted=3
                    )

                    assert len(events) == 3
                    froms = [
                        call.kwargs['_from']
                        for call in (
                            mcp_usage_service.get_mcp_server_chart_data.call_args_list
                        )
                    ]
                    assert all(f is not None for f in froms)
                    assert froms == sorted(froms)
                    assert len(set(froms)) > 1

    @pytest.mark.asyncio
    async def test_stream_mcp_servers_bad_request_gte_and_from(self, sse_test_app):
        """Combining a look-back with explicit bounds is rejected."""
        (
            app,
            _request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url='http://localhost:9000'
        ) as async_client:
            response = await async_client.get(
                f'{PROJECT_BASE}/routes/mcp/servers/stream',
                params={'_gte': 3600, '_from': 1700000000},
            )
            assert response.status_code == 400
            assert '_gte' in response.json()['error']['message'].lower()

    @pytest.mark.asyncio
    async def test_stream_mcp_servers_bad_request_non_positive_gte(self, sse_test_app):
        """A non-positive look-back is rejected."""
        (
            app,
            _request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url='http://localhost:9000'
        ) as async_client:
            response = await async_client.get(
                f'{PROJECT_BASE}/routes/mcp/servers/stream',
                params={'_gte': 0},
            )
            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_stream_mcp_servers_unknown_project(self, sse_test_app):
        """An unknown project fails loudly."""
        (
            app,
            _request_event_service,
            _event_service,
            _mcp_usage_service,
            project_service,
        ) = sse_test_app
        project_service.validate_exists = MagicMock(
            side_effect=ProjectNotFoundError('Project with UUID ... not found')
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url='http://localhost:9000'
        ) as async_client:
            response = await async_client.get(
                f'{PROJECT_BASE}/routes/mcp/servers/stream',
            )
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_stream_mcp_servers_invalid_group_by(self, sse_test_app):
        """A grouping the chart does not offer is rejected."""
        (
            app,
            _request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url='http://localhost:9000'
        ) as async_client:
            response = await async_client.get(
                f'{PROJECT_BASE}/routes/mcp/servers/stream',
                params={'group_by': 'models'},
            )
            assert response.status_code == 422


GROUP_UUID = '550e8400-e29b-41d4-a716-446655440003'
KEY_UUID = '660e8400-e29b-41d4-a716-446655440003'

# (path under the project, the grouping the route stands for, the entity value)
MCP_ENTITY_ENDPOINTS = [
    pytest.param(
        '/routes/mcp/servers/service/files/stream', 'services', 'files', id='service'
    ),
    pytest.param(
        f'/routes/mcp/servers/group/{GROUP_UUID}/stream',
        'groups',
        GROUP_UUID,
        id='group',
    ),
    pytest.param(
        f'/routes/mcp/servers/key/{KEY_UUID}/stream', 'keys', KEY_UUID, id='key'
    ),
]


class TestStreamMcpServersChartByEntity:
    """The per-entity drill-down streams: service alias, group uuid, key uuid."""

    @staticmethod
    async def _read_events(async_client, path, params, wanted: int = 1):
        events = []
        async with async_client.stream(
            'GET', f'{PROJECT_BASE}{path}', params=params
        ) as response:
            assert response.status_code == 200
            assert 'text/event-stream' in response.headers['content-type']
            current_event_lines = []
            async for line in response.aiter_lines():
                if line == '':
                    if current_event_lines:
                        events.append('\n'.join(current_event_lines))
                        current_event_lines = []
                        if len(events) == wanted:
                            break
                else:
                    current_event_lines.append(line)
        return events

    @staticmethod
    def _payload(event: str) -> dict:
        return json.loads(event[event.find('{') : event.rfind('}') + 1])

    @staticmethod
    def _single_series(group_by: str, entity_value: str, data: list[int]):
        return McpServerChartDataDTO(
            granularity='hours',
            timestamp=[1736330400 + 3600 * i for i in range(len(data))],
            data=[
                McpServerChartDataSeriesDTO(
                    name='files' if group_by == 'services' else 'retail',
                    uuid=None if group_by == 'services' else UUID(entity_value),
                    data=data,
                )
            ],
            total=sum(data),
        )

    @pytest.mark.parametrize(('path', 'group_by', 'entity_value'), MCP_ENTITY_ENDPOINTS)
    @pytest.mark.asyncio
    async def test_stream_all_routes(self, sse_test_app, path, group_by, entity_value):
        """Every tick carries the one entity's series for the whole project."""
        (
            app,
            _request_event_service,
            _event_service,
            mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mcp_usage_service.get_mcp_server_chart_data_by_entity = MagicMock(
            side_effect=cycle(
                [
                    self._single_series(group_by, entity_value, [2, 3]),
                    self._single_series(group_by, entity_value, [2, 6]),
                ]
            )
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    events = await self._read_events(async_client, path, {}, wanted=2)

                    assert len(events) == 2
                    payload = self._payload(events[0])
                    assert payload['granularity'] == 'hours'
                    assert payload['timestamp'] == [1736330400, 1736334000]
                    assert payload['total'] == 5
                    assert len(payload['data']) == 1
                    assert payload['data'][0]['data'] == [2, 3]
                    assert payload['data'][0]['uuid'] == (
                        None if group_by == 'services' else entity_value
                    )
                    assert self._payload(events[1])['total'] == 8

                    call_kwargs = mcp_usage_service.get_mcp_server_chart_data_by_entity.call_args.kwargs
                    assert call_kwargs['project_uuid'] == PROJECT_UUID
                    assert call_kwargs['group_by'] == group_by
                    assert call_kwargs['entity_value'] == entity_value
                    assert call_kwargs['route_names'] is None
                    assert call_kwargs['tags'] is None

    @pytest.mark.parametrize(('path', 'group_by', 'entity_value'), MCP_ENTITY_ENDPOINTS)
    @pytest.mark.asyncio
    async def test_stream_filtered_routes(
        self, sse_test_app, path, group_by, entity_value
    ):
        """The routes filter reaches the service on every tick."""
        (
            app,
            _request_event_service,
            _event_service,
            mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mcp_usage_service.get_mcp_server_chart_data_by_entity = MagicMock(
            side_effect=cycle([self._single_series(group_by, entity_value, [7])])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    events = await self._read_events(
                        async_client, path, {'routes': ['route-A', 'route-B']}
                    )

                    assert len(events) == 1
                    payload = self._payload(events[0])
                    assert payload['total'] == 7
                    assert payload['data'][0]['data'] == [7]
                    call_kwargs = mcp_usage_service.get_mcp_server_chart_data_by_entity.call_args.kwargs
                    assert call_kwargs['route_names'] == ['route-A', 'route-B']

    @pytest.mark.parametrize(('path', 'group_by', 'entity_value'), MCP_ENTITY_ENDPOINTS)
    @pytest.mark.asyncio
    async def test_stream_filtered_tags(
        self, sse_test_app, path, group_by, entity_value
    ):
        """The tags filter reaches the service on every tick."""
        (
            app,
            _request_event_service,
            _event_service,
            mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mcp_usage_service.get_mcp_server_chart_data_by_entity = MagicMock(
            side_effect=cycle([self._single_series(group_by, entity_value, [3])])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    events = await self._read_events(
                        async_client,
                        path,
                        {'tags': ['env=prod', 'cost_center=retail']},
                    )

                    assert len(events) == 1
                    payload = self._payload(events[0])
                    assert payload['total'] == 3
                    call_kwargs = mcp_usage_service.get_mcp_server_chart_data_by_entity.call_args.kwargs
                    assert call_kwargs['tags'] == ['env=prod', 'cost_center=retail']

    @pytest.mark.parametrize(('path', 'group_by', 'entity_value'), MCP_ENTITY_ENDPOINTS)
    @pytest.mark.asyncio
    async def test_stream_empty_entity_is_an_empty_chart(
        self, sse_test_app, path, group_by, entity_value
    ):
        """An unknown or quiet entity streams an empty chart, not a 404."""
        (
            app,
            _request_event_service,
            _event_service,
            mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mcp_usage_service.get_mcp_server_chart_data_by_entity = MagicMock(
            side_effect=cycle(
                [
                    McpServerChartDataDTO(
                        granularity='days', timestamp=[], data=[], total=0
                    )
                ]
            )
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    events = await self._read_events(async_client, path, {})

                    assert len(events) == 1
                    assert self._payload(events[0]) == {
                        'granularity': 'days',
                        'timestamp': [],
                        'data': [],
                        'total': 0,
                    }

    @pytest.mark.parametrize(('path', 'group_by', 'entity_value'), MCP_ENTITY_ENDPOINTS)
    @pytest.mark.asyncio
    async def test_stream_rolling_window_moves(
        self, sse_test_app, path, group_by, entity_value
    ):
        """A look-back window is recomputed on every tick, not frozen."""
        (
            app,
            _request_event_service,
            _event_service,
            mcp_usage_service,
            _project_service,
        ) = sse_test_app

        mcp_usage_service.get_mcp_server_chart_data_by_entity = MagicMock(
            side_effect=cycle([self._single_series(group_by, entity_value, [1])])
        )

        with patch(
            'radicalbit_ai_gateway.routes.dashboard_route.sleep', return_value=None
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url='http://localhost:9000'
            ) as async_client:
                with anyio.move_on_after(2):
                    events = await self._read_events(
                        async_client, path, {'_gte': 3600}, wanted=3
                    )

                    assert len(events) == 3
                    calls = mcp_usage_service.get_mcp_server_chart_data_by_entity.call_args_list
                    froms = [call.kwargs['_from'] for call in calls]
                    assert all(f is not None for f in froms)
                    assert all(call.kwargs['_to'] is None for call in calls)
                    assert froms == sorted(froms)
                    assert len(set(froms)) > 1

    @pytest.mark.parametrize(('path', 'group_by', 'entity_value'), MCP_ENTITY_ENDPOINTS)
    @pytest.mark.asyncio
    async def test_stream_bad_request_gte_and_from(
        self, sse_test_app, path, group_by, entity_value
    ):
        """Combining a look-back with explicit bounds is rejected."""
        (
            app,
            _request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url='http://localhost:9000'
        ) as async_client:
            response = await async_client.get(
                f'{PROJECT_BASE}{path}', params={'_gte': 3600, '_from': 1700000000}
            )
            assert response.status_code == 400
            assert '_gte' in response.json()['error']['message'].lower()

    @pytest.mark.parametrize(('path', 'group_by', 'entity_value'), MCP_ENTITY_ENDPOINTS)
    @pytest.mark.asyncio
    async def test_stream_bad_request_non_positive_gte(
        self, sse_test_app, path, group_by, entity_value
    ):
        """A non-positive look-back is rejected."""
        (
            app,
            _request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url='http://localhost:9000'
        ) as async_client:
            response = await async_client.get(
                f'{PROJECT_BASE}{path}', params={'_gte': 0}
            )
            assert response.status_code == 400

    @pytest.mark.parametrize(('path', 'group_by', 'entity_value'), MCP_ENTITY_ENDPOINTS)
    @pytest.mark.asyncio
    async def test_stream_unknown_project(
        self, sse_test_app, path, group_by, entity_value
    ):
        """An unknown project fails loudly before the stream opens."""
        (
            app,
            _request_event_service,
            _event_service,
            _mcp_usage_service,
            project_service,
        ) = sse_test_app
        project_service.validate_exists = MagicMock(
            side_effect=ProjectNotFoundError('Project with UUID ... not found')
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url='http://localhost:9000'
        ) as async_client:
            response = await async_client.get(f'{PROJECT_BASE}{path}')
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_a_malformed_group_or_key_uuid_is_rejected(self, sse_test_app):
        """The group and key routes take a uuid, and say so."""
        (
            app,
            _request_event_service,
            _event_service,
            _mcp_usage_service,
            _project_service,
        ) = sse_test_app

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url='http://localhost:9000'
        ) as async_client:
            for kind in ('group', 'key'):
                response = await async_client.get(
                    f'{PROJECT_BASE}/routes/mcp/servers/{kind}/not-a-uuid/stream'
                )
                assert response.status_code == 422, kind
