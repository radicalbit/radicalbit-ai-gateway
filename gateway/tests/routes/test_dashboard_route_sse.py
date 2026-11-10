from datetime import datetime, timedelta, timezone
from itertools import cycle
import json
from types import SimpleNamespace
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
BASE_URL = 'http://localhost:9000'
SLEEP = 'radicalbit_ai_gateway.routes.dashboard_route.sleep'
ASYNC_SLEEP = 'radicalbit_ai_gateway.routes.dashboard_route.asyncio.sleep'

STREAMED_EVENTS = 3

KEY_UUID = '550e8400-e29b-41d4-a716-446655440001'
GROUP_UUID = '550e8400-e29b-41d4-a716-446655440002'
MCP_GROUP_UUID = '550e8400-e29b-41d4-a716-446655440003'
MCP_KEY_UUID = '660e8400-e29b-41d4-a716-446655440003'
TS = [1700000000, 1700003600]
COST_TS = [1736330400, 1736334000]
FROM_TS, TO_TS = 1704067200, 1704153600
FROM_DT = datetime.fromtimestamp(FROM_TS, tz=timezone.utc)
TO_DT = datetime.fromtimestamp(TO_TS, tz=timezone.utc)
ROUTES = ['route-A', 'route-B']
TAGS = ['env=prod', 'cost_center=retail']

SERVICE_SPECS = {
    'event': EventService,
    'request': RequestEventService,
    'project': ProjectService,
    'mcp': McpUsageService,
}


class _EndOfStream(Exception):
    """Ends a dashboard stream: its loop never ends on its own."""


def _end_stream_after(events: int):
    """Side effect for a stream's patched sleep: the stream sends *events*
    events, then ends. A test reads them from a transport that keeps the
    events sent before the app's error (``raise_app_exceptions=False``).
    """
    calls = 0

    def sleep(*_):
        nonlocal calls
        calls += 1
        if calls >= events:
            raise _EndOfStream

    return sleep


class _Delegate:
    """Stands in for a service in the module-wide router and forwards every
    call to the current test's fresh mock.
    """

    def __init__(self):
        self.mock = None

    def __getattr__(self, name):
        return getattr(self.mock, name)


DELEGATES = {name: _Delegate() for name in SERVICE_SPECS}


@pytest.fixture(scope='module')
def app():
    """Build the dashboard router once; services are swapped per test."""
    router = DashboardRoute.get_dashboard_router(
        event_service=DELEGATES['event'],
        request_event_service=DELEGATES['request'],
        project_service=DELEGATES['project'],
        mcp_usage_service=DELEGATES['mcp'],
    )
    app = FastAPI(title='AI Gateway', debug=True)
    app.add_exception_handler(GatewayError, gateway_exception_handler)
    app.add_exception_handler(GatewayBadRequest, gateway_exception_handler)
    app.add_exception_handler(AuthRegistryError, auth_registry_exception_handler)
    app.include_router(router, prefix='/public/api/v1')
    project_entry = MagicMock()
    project_entry.config.routes = {}
    app.state.project_configs = {PROJECT_NAME: project_entry}
    app.state.routes = {}
    return app


@pytest.fixture
def services():
    """Fresh service mocks behind the module-wide router."""
    mocks = SimpleNamespace(
        **{name: MagicMock(spec_set=spec) for name, spec in SERVICE_SPECS.items()}
    )
    project = MagicMock()
    project.name = PROJECT_NAME
    mocks.project.get_by_uuid.return_value = project
    for name, delegate in DELEGATES.items():
        delegate.mock = getattr(mocks, name)
    yield mocks
    for delegate in DELEGATES.values():
        delegate.mock = None


async def _stream(app, path, params=None, wanted=1) -> list:
    """Open a stream and return the JSON payloads of its first *wanted* events."""
    end_stream = (
        patch(
            ASYNC_SLEEP,
            new_callable=AsyncMock,
            side_effect=_end_stream_after(STREAMED_EVENTS),
        )
        if path.endswith('/limits/stream')
        else patch(SLEEP, side_effect=_end_stream_after(STREAMED_EVENTS))
    )
    payloads = []
    with end_stream:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            with anyio.fail_after(5):
                async with client.stream(
                    'GET', f'{PROJECT_BASE}{path}', params=params
                ) as response:
                    assert response.status_code == 200
                    assert 'text/event-stream' in response.headers['content-type']
                    async for line in response.aiter_lines():
                        if line.startswith('data:'):
                            payloads.append(json.loads(line[len('data:') :]))
                            if len(payloads) == wanted:
                                break
    assert len(payloads) == wanted
    return payloads


async def _get(app, path, params=None):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=BASE_URL
    ) as client:
        return await client.get(f'{PROJECT_BASE}{path}', params=params)


def _subset(actual: dict, expected: dict) -> dict:
    return {k: actual[k] for k in expected}


def _ranked(cls, name, pct, chart_cls=RequestChartDataDTO, total=100):
    return cls(
        name=name,
        increment_percentage=pct,
        chart=chart_cls(total=total, granularity='hours', timestamp=TS, data=[40, 60]),
    )


def _cost_chart(total, *series, granularity='hours', timestamp=COST_TS):
    return CostChartDataDTO(
        granularity=granularity,
        timestamp=timestamp,
        data=[CostChartDataSeriesDTO(name=n, data=d) for n, d in series],
        total=total,
    )


def _mcp_chart(total, *series, granularity='hours', timestamp=COST_TS):
    return McpServerChartDataDTO(
        granularity=granularity, timestamp=timestamp, data=list(series), total=total
    )


def _mcp_entity_chart(group_by: str, entity_value: str, data: list[int]):
    return _mcp_chart(
        sum(data),
        McpServerChartDataSeriesDTO(
            name='files' if group_by == 'services' else 'retail',
            uuid=None if group_by == 'services' else UUID(entity_value),
            data=data,
        ),
        timestamp=[1736330400 + 3600 * i for i in range(len(data))],
    )


def _series(name, data, uuid=None):
    return {'name': name, 'uuid': uuid, 'data': data}


# (id, path, grouping the route stands for, entity value)
MCP_ENTITIES = [
    ('service', '/routes/mcp/servers/service/files/stream', 'services', 'files'),
    (
        'group',
        f'/routes/mcp/servers/group/{MCP_GROUP_UUID}/stream',
        'groups',
        MCP_GROUP_UUID,
    ),
    ('key', f'/routes/mcp/servers/key/{MCP_KEY_UUID}/stream', 'keys', MCP_KEY_UUID),
]


def _mcp_entity_cases():
    for name, path, group_by, value in MCP_ENTITIES:
        uuid = None if group_by == 'services' else value
        series_name = 'files' if group_by == 'services' else 'retail'
        yield pytest.param(
            path,
            {},
            'mcp',
            'get_mcp_server_chart_data_by_entity',
            [
                _mcp_entity_chart(group_by, value, [2, 3]),
                _mcp_entity_chart(group_by, value, [2, 6]),
            ],
            [
                {
                    'granularity': 'hours',
                    'timestamp': COST_TS,
                    'total': 5,
                    'data': [_series(series_name, [2, 3], uuid)],
                },
                {'total': 8},
            ],
            {
                'project_uuid': PROJECT_UUID,
                'group_by': group_by,
                'entity_value': value,
                'route_names': None,
                'tags': None,
            },
            id=f'mcp-{name}',
        )
        yield pytest.param(
            path,
            {'routes': ROUTES, 'tags': TAGS},
            'mcp',
            'get_mcp_server_chart_data_by_entity',
            [_mcp_entity_chart(group_by, value, [7])],
            [{'total': 7, 'data': [_series(series_name, [7], uuid)]}],
            {'route_names': ROUTES, 'tags': TAGS},
            id=f'mcp-{name}-filtered',
        )


# (path, query, service, method, results cycled per tick,
#  expected payload subset per tick, expected subset of the last call's kwargs)
STREAM_CASES = [
    pytest.param(
        '/routes/most-requested/stream',
        {},
        'request',
        'get_most_requested_route',
        [
            _ranked(MostRequestedRouteDTO, 'route-A', 50.0),
            _ranked(MostRequestedRouteDTO, 'route-B', 25.0),
        ],
        [
            {'name': 'route-A', 'incrementPercentage': 50.0},
            {'name': 'route-B', 'incrementPercentage': 25.0},
        ],
        {'_from': None, '_to': None},
        id='most-requested',
    ),
    pytest.param(
        '/routes/most-requested-error/stream',
        {},
        'request',
        'get_most_requested_error_route',
        [
            _ranked(MostRequestedErrorRouteDTO, 'error-route-A', 75.0),
            _ranked(MostRequestedErrorRouteDTO, 'error-route-B', 10.0),
        ],
        [
            {'name': 'error-route-A', 'incrementPercentage': 75.0},
            {'name': 'error-route-B', 'incrementPercentage': 10.0},
        ],
        {},
        id='most-requested-error',
    ),
    pytest.param(
        '/routes/most-expensive/stream',
        {},
        'event',
        'get_most_expensive_route',
        [
            _ranked(
                MostExpensiveRouteDTO, 'route-A', 30.0, MostExpensiveRouteChartDataDTO
            ),
            _ranked(
                MostExpensiveRouteDTO, 'route-B', -10.0, MostExpensiveRouteChartDataDTO
            ),
        ],
        [
            {'name': 'route-A', 'incrementPercentage': 30.0},
            {'name': 'route-B', 'incrementPercentage': -10.0},
        ],
        {},
        id='most-expensive',
    ),
    pytest.param(
        '/routes/costs/stream',
        {'group_by': 'keys', 'routes': ROUTES, 'tags': TAGS},
        'event',
        'get_costs_chart_data',
        [
            _cost_chart(30.0, ('group-1 (route-a)', [10.0, 20.0])),
            _cost_chart(40.0, ('group-1 (route-a)', [15.0, 25.0])),
        ],
        [
            {
                'granularity': 'hours',
                'timestamp': COST_TS,
                'total': 30.0,
                'data': [_series('group-1 (route-a)', [10.0, 20.0])],
            },
            {'total': 40.0},
        ],
        {'route_names': ROUTES, 'group_by': 'keys', 'tags': TAGS},
        id='costs',
    ),
    pytest.param(
        '/routes/costs/summary/stream',
        {'routes': ROUTES},
        'event',
        'get_summary_costs',
        [
            CostDataDTO(input_cost=10.0, output_cost=20.0, total_cost=30.0),
            CostDataDTO(input_cost=15.0, output_cost=25.0, total_cost=40.0),
        ],
        [
            {'inputCost': 10.0, 'outputCost': 20.0, 'totalCost': 30.0},
            {'inputCost': 15.0, 'totalCost': 40.0},
        ],
        {'route_names': ROUTES},
        id='costs-summary',
    ),
    pytest.param(
        '/routes/invocations/stream',
        {'include_models': 'false'},
        'event',
        'get_invocation_chart_data',
        [
            InvocationChartDataDTO(
                granularity='hours', timestamp=TS, data=[3.0, 7.0], total=10
            )
        ],
        [{'granularity': 'hours', 'timestamp': TS, 'data': [3.0, 7.0], 'total': 10}],
        {'include_models': False, 'route_names': None},
        id='invocations',
    ),
    pytest.param(
        '/routes/invocations/stream',
        {
            'routes': ['route-a', 'route-c'],
            '_from': FROM_TS,
            '_to': TO_TS,
            'include_models': 'true',
        },
        'event',
        'get_invocation_chart_data',
        [
            InvocationChartDataDTO(
                granularity='hours',
                timestamp=TS,
                data=[
                    ChartDataSeriesDTO(name='gpt-4', data=[2.0, 1.0]),
                    ChartDataSeriesDTO(name='gpt-3.5', data=[3.0, 2.0]),
                ],
                total=8,
            )
        ],
        [
            {
                'data': [
                    {'name': 'gpt-4', 'data': [2.0, 1.0]},
                    {'name': 'gpt-3.5', 'data': [3.0, 2.0]},
                ]
            }
        ],
        {
            'include_models': True,
            'route_names': ['route-a', 'route-c'],
            '_from': FROM_DT,
            '_to': TO_DT,
        },
        id='invocations-per-model-filtered',
    ),
    pytest.param(
        '/routes/tokens/stream',
        {},
        'event',
        'get_token_chart_data',
        [
            TokenChartDataDTO(
                granularity='hours',
                timestamp=TS,
                data=[
                    TokenChartDataSeriesDTO(name='INPUT', data=[100, 150]),
                    TokenChartDataSeriesDTO(name='OUTPUT', data=[50, 75]),
                ],
                total=375,
            )
        ],
        [
            {
                'granularity': 'hours',
                'timestamp': TS,
                'total': 375,
                'data': [
                    {'name': 'INPUT', 'data': [100, 150]},
                    {'name': 'OUTPUT', 'data': [50, 75]},
                ],
            }
        ],
        {'route_names': None},
        id='tokens',
    ),
    pytest.param(
        '/routes/tokens/stream',
        {'routes': ['route-a', 'route-c'], '_from': FROM_TS, '_to': TO_TS},
        'event',
        'get_token_chart_data',
        [TokenChartDataDTO(granularity='hours', timestamp=[], data=[], total=0)],
        [{'total': 0}],
        {'route_names': ['route-a', 'route-c'], '_from': FROM_DT, '_to': TO_DT},
        id='tokens-filtered',
    ),
    pytest.param(
        f'/routes/costs/key/{KEY_UUID}/stream',
        {'routes': ROUTES},
        'event',
        'get_costs_chart_data_by_route',
        [_cost_chart(50.0, ('route-A', [10.0, 20.0]), ('route-B', [5.0, 15.0]))],
        [
            {
                'granularity': 'hours',
                'total': 50.0,
                'data': [
                    _series('route-A', [10.0, 20.0]),
                    _series('route-B', [5.0, 15.0]),
                ],
            }
        ],
        {
            'entity_column': 'API_KEY_UUID',
            'entity_value': KEY_UUID,
            'route_names': ROUTES,
        },
        id='costs-by-key',
    ),
    pytest.param(
        f'/routes/costs/group/{GROUP_UUID}/stream',
        {'routes': ['route-A']},
        'event',
        'get_costs_chart_data_by_route',
        [
            _cost_chart(
                100.0, ('route-A', [100.0]), granularity='days', timestamp=[1736208000]
            )
        ],
        [{'granularity': 'days', 'total': 100.0}],
        {
            'entity_column': 'GROUP_UUID',
            'entity_value': GROUP_UUID,
            'route_names': ['route-A'],
        },
        id='costs-by-group',
    ),
    pytest.param(
        '/routes/costs/model/gpt-4o/stream',
        {'routes': ROUTES},
        'event',
        'get_costs_chart_data_by_route',
        [_cost_chart(42.0, ('route-A', [42.0]), timestamp=[1736330400])],
        [{'total': 42.0}],
        {'entity_column': 'MODEL_ID', 'entity_value': 'gpt-4o', 'route_names': ROUTES},
        id='costs-by-model',
    ),
    pytest.param(
        '/routes/mcp/servers/stream',
        {},
        'mcp',
        'get_mcp_server_chart_data',
        [
            _mcp_chart(5, McpServerChartDataSeriesDTO(name='files', data=[2, 3])),
            _mcp_chart(8, McpServerChartDataSeriesDTO(name='files', data=[2, 6])),
        ],
        [
            {
                'granularity': 'hours',
                'timestamp': COST_TS,
                'total': 5,
                'data': [_series('files', [2, 3])],
            },
            {'total': 8},
        ],
        {'group_by': 'services'},
        id='mcp-servers-default-services',
    ),
    *(
        pytest.param(
            '/routes/mcp/servers/stream',
            {'group_by': group_by},
            'mcp',
            'get_mcp_server_chart_data',
            [
                _mcp_chart(
                    4,
                    McpServerChartDataSeriesDTO(
                        name='retail', uuid=UUID(MCP_GROUP_UUID), data=[4]
                    ),
                )
            ],
            [{'data': [_series('retail', [4], MCP_GROUP_UUID)]}],
            {'group_by': group_by},
            id=f'mcp-servers-{group_by}',
        )
        for group_by in ('groups', 'keys')
    ),
    pytest.param(
        '/routes/mcp/servers/stream',
        {'routes': ROUTES, 'tags': TAGS},
        'mcp',
        'get_mcp_server_chart_data',
        [_mcp_chart(7, McpServerChartDataSeriesDTO(name='files', data=[7]))],
        [{'total': 7, 'data': [_series('files', [7])]}],
        {'route_names': ROUTES, 'tags': TAGS},
        id='mcp-servers-filtered',
    ),
    *_mcp_entity_cases(),
    pytest.param(
        MCP_ENTITIES[0][1],
        {},
        'mcp',
        'get_mcp_server_chart_data_by_entity',
        [_mcp_chart(0, granularity='days', timestamp=[])],
        # every field of the chart: an empty entity is an empty chart, not a 404
        [{'granularity': 'days', 'timestamp': [], 'data': [], 'total': 0}],
        {},
        id='mcp-entity-empty',
    ),
]


@pytest.mark.parametrize(
    ('path', 'params', 'service', 'method', 'results', 'expected', 'call'),
    STREAM_CASES,
)
async def test_each_tick_streams_the_service_result_and_forwards_the_query(
    app, services, path, params, service, method, results, expected, call
):
    mocked = getattr(getattr(services, service), method)
    mocked.side_effect = cycle(results)

    payloads = await _stream(app, path, params, wanted=len(expected))

    for payload, want in zip(payloads, expected, strict=True):
        assert _subset(payload, want) == want
    assert _subset(mocked.call_args.kwargs, call) == call


@pytest.mark.parametrize(
    ('path', 'service', 'method', 'dto'),
    [
        pytest.param(
            '/routes/most-requested-error/stream',
            'request',
            'get_most_requested_error_route',
            _ranked(MostRequestedErrorRouteDTO, 'error-route-A', 50.0, total=1.0),
            id='most-requested-error',
        ),
        pytest.param(
            '/routes/most-expensive/stream',
            'event',
            'get_most_expensive_route',
            _ranked(
                MostExpensiveRouteDTO, 'route-A', 50.0, MostExpensiveRouteChartDataDTO
            ),
            id='most-expensive',
        ),
    ],
)
async def test_a_tick_without_data_streams_an_empty_object(
    app, services, path, service, method, dto
):
    getattr(getattr(services, service), method).side_effect = cycle([None, dto])

    first, second = await _stream(app, path, wanted=2)

    assert first == {}
    assert second['name'] == dto.name


async def test_limits_stream_sends_progress_bars_and_forwards_filters(app, services):
    services.event.get_route_limits_progress.return_value = [
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
        ),
        RouteProgressBarDTO(route_name='bare-route', progress_bar=None),
    ]

    [payload] = await _stream(
        app,
        '/routes/limits/stream',
        [
            ('routes', 'route-a'),
            ('routes', 'route-c'),
            ('window_statuses', 'ok'),
            ('window_statuses', 'warning'),
        ],
    )

    assert len(payload) == 2
    assert payload[0]['routeName'] == 'my-route'
    pb = payload[0]['progressBar']
    assert pb['budget']['windowLength'] == 3600
    assert pb['budget']['windowSize'] == pytest.approx(10.0)
    assert pb['budget']['windowFilledSize'] == pytest.approx(7.0)
    assert pb['budget']['windowFilledPercentage'] == pytest.approx(70.0)
    assert pb['budget']['windowStatus'] == WindowStatus.OK
    assert pb['rate']['windowSize'] == pytest.approx(100.0)
    assert pb['rate']['windowStatus'] == WindowStatus.OK
    assert 'tokenInput' not in pb
    assert 'tokenOutput' not in pb
    assert payload[1] == {'routeName': 'bare-route'}
    assert services.event.get_route_limits_progress.call_args.args[1:4] == (
        PROJECT_NAME,
        ['route-a', 'route-c'],
        [WindowStatus.OK, WindowStatus.WARNING],
    )


@pytest.mark.parametrize(
    ('path', 'service', 'method', 'result'),
    [
        pytest.param(
            '/routes/most-requested/stream',
            'request',
            'get_most_requested_route',
            _ranked(MostRequestedRouteDTO, 'route-A', 50.0),
            id='most-requested',
        ),
        pytest.param(
            '/routes/invocations/stream',
            'event',
            'get_invocation_chart_data',
            InvocationChartDataDTO(granularity='hours', timestamp=[], data=[], total=0),
            id='invocations',
        ),
        pytest.param(
            '/routes/tokens/stream',
            'event',
            'get_token_chart_data',
            TokenChartDataDTO(granularity='hours', timestamp=[], data=[], total=0),
            id='tokens',
        ),
        pytest.param(
            '/routes/mcp/servers/stream',
            'mcp',
            'get_mcp_server_chart_data',
            _mcp_chart(0, timestamp=[1736208000]),
            id='mcp-servers',
        ),
        *(
            pytest.param(
                path,
                'mcp',
                'get_mcp_server_chart_data_by_entity',
                _mcp_entity_chart(group_by, value, [1]),
                id=f'mcp-{name}',
            )
            for name, path, group_by, value in MCP_ENTITIES
        ),
    ],
)
async def test_a_look_back_window_is_recomputed_on_every_tick(
    app, services, path, service, method, result
):
    mocked = getattr(getattr(services, service), method)
    mocked.return_value = result

    await _stream(app, path, {'_gte': 3600}, wanted=3)

    calls = mocked.call_args_list
    froms = [call.kwargs['_from'] for call in calls]
    assert len(froms) == 3
    assert all(f is not None for f in froms)
    assert all(call.kwargs['_to'] is None for call in calls)
    assert froms == sorted(froms)
    assert len(set(froms)) > 1


@pytest.mark.parametrize(
    ('path', 'params'),
    [
        pytest.param('/routes/costs/stream', {'group_by': 'groups'}, id='costs'),
        pytest.param('/routes/costs/summary/stream', {}, id='costs-summary'),
        pytest.param('/routes/most-requested/stream', {}, id='most-requested'),
        pytest.param('/routes/invocations/stream', {}, id='invocations'),
        pytest.param('/routes/tokens/stream', {}, id='tokens'),
        pytest.param(f'/routes/costs/key/{KEY_UUID}/stream', {}, id='costs-by-key'),
        pytest.param('/routes/mcp/servers/stream', {}, id='mcp-servers'),
        *(
            pytest.param(path, {}, id=f'mcp-{name}')
            for name, path, _, _ in MCP_ENTITIES
        ),
    ],
)
async def test_a_stream_rejects_a_look_back_combined_with_bounds(
    app, services, path, params
):
    response = await _get(app, path, {**params, '_gte': 3600, '_from': 1700000000})

    assert response.status_code == 400
    assert '_gte' in response.json()['error']['message'].lower()


@pytest.mark.parametrize(
    ('params', 'message'),
    [
        pytest.param({'_gte': 0}, 'positive', id='zero-gte'),
        pytest.param({'_gte': -100}, 'positive', id='negative-gte'),
    ],
)
async def test_invalid_time_params_are_rejected(app, services, params, message):
    response = await _get(app, '/routes/most-requested/stream', params)

    assert response.status_code == 400
    assert message in response.json()['error']['message'].lower()


def test_compute_sse_time_range_rolls_a_look_back_and_keeps_fixed_bounds():
    before = datetime.now(timezone.utc) - timedelta(seconds=3600)
    from_dt, to_dt = compute_sse_time_range(3600, None, None)
    after = datetime.now(timezone.utc) - timedelta(seconds=3600)
    assert to_dt is None
    assert before <= from_dt <= after

    from_dt, to_dt = compute_sse_time_range(None, 1700000000, 1700003600)
    assert from_dt.timestamp() == 1700000000
    assert to_dt.timestamp() == 1700003600

    assert compute_sse_time_range(None, None, None) == (None, None)


@pytest.mark.parametrize(
    'path',
    [
        pytest.param('/routes/mcp/servers/stream', id='mcp-servers'),
        *(pytest.param(path, id=f'mcp-{name}') for name, path, _, _ in MCP_ENTITIES),
    ],
)
async def test_an_unknown_project_fails_before_the_stream_opens(app, services, path):
    services.project.validate_exists.side_effect = ProjectNotFoundError(
        'Project with UUID ... not found'
    )

    response = await _get(app, path)

    assert response.status_code == 404


async def test_a_malformed_grouping_or_entity_uuid_is_rejected(app, services):
    for path, params in (
        ('/routes/mcp/servers/stream', {'group_by': 'models'}),
        ('/routes/mcp/servers/group/not-a-uuid/stream', None),
        ('/routes/mcp/servers/key/not-a-uuid/stream', None),
    ):
        response = await _get(app, path, params)
        assert response.status_code == 422, path
