import datetime
import unittest
from unittest.mock import MagicMock
import uuid
from uuid import UUID

from fastapi import FastAPI
from fastapi_pagination import Page, Params
from starlette.testclient import TestClient

from radicalbit_ai_gateway.models.trace_dto import (
    ErrorEvents,
    GroupedSpanLatenciesDTO,
    GroupedSpanLatencyDTO,
    LatenciesDTO,
    SpanDTO,
    SpanLatenciesDTO,
    SpanLatencyDTO,
    TraceDTO,
    TracesChartDataDTO,
    TracesChartDataSeriesDTO,
    TreeNodeDTO,
)
from radicalbit_ai_gateway.routes.tracing_route import TracingRoute
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.services.tracing_service import TracingService
from radicalbit_ai_gateway.utils.exceptions import (
    GatewayError,
    GatewayNotFoundError,
    gateway_exception_handler,
)

PROJECT_UUID = UUID('11111111-1111-1111-1111-111111111111')
PROJECT_NAME = 'test-project'


def _r(name: str) -> str:
    """Return route name (short, without project prefix)."""
    return name


class TestTracingRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prefix = '/public/api/v1'
        cls.tracing_service: TracingService = MagicMock(spec_set=TracingService)
        cls.project_service: ProjectService = MagicMock(spec_set=ProjectService)

        # Project mock
        project_mock = MagicMock()
        project_mock.name = PROJECT_NAME
        cls.project_service.get_by_uuid = MagicMock(return_value=project_mock)

        # Project config with routes route-a, route-b, my-route
        project_entry_mock = MagicMock()
        project_entry_mock.config.routes = {
            'route-a': MagicMock(),
            'route-b': MagicMock(),
            'my-route': MagicMock(),
        }

        router = TracingRoute.get_tracing_router(
            tracing_service=cls.tracing_service,
            project_service=cls.project_service,
        )
        app = FastAPI(title='AI Gateway', debug=True)
        app.add_exception_handler(GatewayError, gateway_exception_handler)
        app.state.project_configs = {PROJECT_NAME: project_entry_mock}
        app.include_router(router, prefix=cls.prefix)
        cls.client = TestClient(app)
        cls.project_path = f'{cls.prefix}/projects/{PROJECT_UUID}'

    def test_get_traces_chart_data(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        mock_chart = TracesChartDataDTO(
            granularity='hours',
            timestamp=[int(base_time.timestamp())],
            data=[
                TracesChartDataSeriesDTO(name='success', data=[7]),
                TracesChartDataSeriesDTO(name='warning', data=[0]),
                TracesChartDataSeriesDTO(name='error', data=[1]),
            ],
            total=8,
        )
        self.tracing_service.get_traces_chart_data = MagicMock(return_value=mock_chart)

        response = self.client.get(
            f'{self.project_path}/traces/chart',
            params={
                '_from': int(base_time.timestamp()),
                '_to': int((base_time + datetime.timedelta(hours=2)).timestamp()),
                'routes': ['route-a', 'route-b'],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body['granularity'] == 'hours'
        assert len(body['timestamp']) == 1
        series = {s['name']: s['data'] for s in body['data']}
        assert series['success'] == [7.0]
        assert series['warning'] == [0.0]
        assert series['error'] == [1.0]

        call_kwargs = self.tracing_service.get_traces_chart_data.call_args.kwargs
        assert set(call_kwargs['route_names']) == {_r('route-a'), _r('route-b')}

    def test_get_traces_chart_data_no_filters(self):
        mock_chart = TracesChartDataDTO(
            granularity='days', timestamp=[], data=[], total=0
        )
        self.tracing_service.get_traces_chart_data = MagicMock(return_value=mock_chart)

        response = self.client.get(f'{self.project_path}/traces/chart')

        assert response.status_code == 200
        body = response.json()
        assert body['granularity'] == 'days'
        assert body['timestamp'] == []
        assert body['data'] == []

        call_kwargs = self.tracing_service.get_traces_chart_data.call_args.kwargs
        assert call_kwargs['route_names'] is None
        assert call_kwargs['project_uuid'] == PROJECT_UUID
        assert call_kwargs['_from'] is None
        assert call_kwargs['_to'] is None

    def test_get_latencies(self):
        mock_latencies = LatenciesDTO(p50=120.0, p90=250.0, p95=310.0, p99=500.0)
        self.tracing_service.get_latencies = MagicMock(return_value=mock_latencies)

        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        response = self.client.get(
            f'{self.project_path}/traces/latencies',
            params={
                '_from': int(base_time.timestamp()),
                '_to': int((base_time + datetime.timedelta(hours=2)).timestamp()),
                'routes': ['route-a', 'route-b'],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body['p50'] == 120.0
        assert body['p90'] == 250.0
        assert body['p95'] == 310.0
        assert body['p99'] == 500.0

        call_kwargs = self.tracing_service.get_latencies.call_args.kwargs
        assert set(call_kwargs['route_names']) == {_r('route-a'), _r('route-b')}

    def test_get_latencies_with_tags_filter(self):
        mock_latencies = LatenciesDTO(p50=120.0, p90=250.0, p95=310.0, p99=500.0)
        self.tracing_service.get_latencies = MagicMock(return_value=mock_latencies)

        response = self.client.get(
            f'{self.project_path}/traces/latencies',
            params={'tags': ['env=prod']},
        )

        assert response.status_code == 200
        call_kwargs = self.tracing_service.get_latencies.call_args.kwargs
        assert call_kwargs['tags'] == ['env=prod']

    def test_get_latencies_no_filters(self):
        mock_latencies = LatenciesDTO(p50=None, p90=None, p95=None, p99=None)
        self.tracing_service.get_latencies = MagicMock(return_value=mock_latencies)

        response = self.client.get(f'{self.project_path}/traces/latencies')

        assert response.status_code == 200
        call_kwargs = self.tracing_service.get_latencies.call_args.kwargs
        assert call_kwargs['route_names'] is None
        assert call_kwargs['project_uuid'] == PROJECT_UUID
        assert call_kwargs['_from'] is None
        assert call_kwargs['_to'] is None

    def test_get_traces_chart_data_single_route(self):
        mock_chart = TracesChartDataDTO(
            granularity='hours',
            timestamp=[1736330400],
            data=[
                TracesChartDataSeriesDTO(name='success', data=[3]),
                TracesChartDataSeriesDTO(name='warning', data=[0]),
                TracesChartDataSeriesDTO(name='error', data=[0]),
            ],
            total=3,
        )
        self.tracing_service.get_traces_chart_data = MagicMock(return_value=mock_chart)

        response = self.client.get(
            f'{self.project_path}/traces/chart',
            params={'routes': 'my-route'},
        )

        assert response.status_code == 200
        call_kwargs = self.tracing_service.get_traces_chart_data.call_args.kwargs
        assert call_kwargs['route_names'] == [_r('my-route')]

    def test_get_traces_chart_data_with_tags_filter(self):
        mock_chart = TracesChartDataDTO(
            granularity='hours', timestamp=[], data=[], total=0
        )
        self.tracing_service.get_traces_chart_data = MagicMock(return_value=mock_chart)

        response = self.client.get(
            f'{self.project_path}/traces/chart',
            params={'tags': ['env=prod']},
        )

        assert response.status_code == 200
        call_kwargs = self.tracing_service.get_traces_chart_data.call_args.kwargs
        assert call_kwargs['tags'] == ['env=prod']

    def test_get_span_latencies(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        mock_span_latencies = SpanLatenciesDTO(
            data=[
                SpanLatencyDTO(
                    span_name='invoke', p50=120.0, p90=250.0, p95=310.0, p99=500.0
                ),
                SpanLatencyDTO(
                    span_name='set_cached_response',
                    p50=10.0,
                    p90=20.0,
                    p95=25.0,
                    p99=40.0,
                ),
            ]
        )
        self.tracing_service.get_span_latencies = MagicMock(
            return_value=mock_span_latencies
        )

        response = self.client.get(
            f'{self.project_path}/traces/spans/latencies',
            params={
                '_from': int(base_time.timestamp()),
                '_to': int((base_time + datetime.timedelta(hours=2)).timestamp()),
                'routes': ['route-a', 'route-b'],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body['data']) == 2
        spans = {s['spanName']: s for s in body['data']}
        assert spans['invoke']['p50'] == 120.0
        assert spans['invoke']['p99'] == 500.0
        assert spans['set_cached_response']['p50'] == 10.0

        call_kwargs = self.tracing_service.get_span_latencies.call_args.kwargs
        assert set(call_kwargs['route_names']) == {_r('route-a'), _r('route-b')}

    def test_get_span_latencies_no_filters(self):
        mock_span_latencies = SpanLatenciesDTO(data=[])
        self.tracing_service.get_span_latencies = MagicMock(
            return_value=mock_span_latencies
        )

        response = self.client.get(f'{self.project_path}/traces/spans/latencies')

        assert response.status_code == 200
        body = response.json()
        assert body['data'] == []

        call_kwargs = self.tracing_service.get_span_latencies.call_args.kwargs
        assert call_kwargs['route_names'] is None
        assert call_kwargs['project_uuid'] == PROJECT_UUID
        assert call_kwargs['_from'] is None
        assert call_kwargs['_to'] is None

    def test_get_span_latencies_with_tags_filter(self):
        mock_span_latencies = SpanLatenciesDTO(data=[])
        self.tracing_service.get_span_latencies = MagicMock(
            return_value=mock_span_latencies
        )

        response = self.client.get(
            f'{self.project_path}/traces/spans/latencies',
            params={'tags': ['env=prod']},
        )

        assert response.status_code == 200
        call_kwargs = self.tracing_service.get_span_latencies.call_args.kwargs
        assert call_kwargs['tags'] == ['env=prod']

    def test_get_span_latencies_single_route(self):
        mock_span_latencies = SpanLatenciesDTO(
            data=[
                SpanLatencyDTO(
                    span_name='invoke', p50=80.0, p90=160.0, p95=200.0, p99=300.0
                )
            ]
        )
        self.tracing_service.get_span_latencies = MagicMock(
            return_value=mock_span_latencies
        )

        response = self.client.get(
            f'{self.project_path}/traces/spans/latencies',
            params={'routes': 'my-route'},
        )

        assert response.status_code == 200
        call_kwargs = self.tracing_service.get_span_latencies.call_args.kwargs
        assert call_kwargs['route_names'] == [_r('my-route')]

    def test_get_span_latencies_passes_time_range(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        mock_span_latencies = SpanLatenciesDTO(data=[])
        self.tracing_service.get_span_latencies = MagicMock(
            return_value=mock_span_latencies
        )

        _from_ts = int(base_time.timestamp())
        _to_ts = int((base_time + datetime.timedelta(hours=2)).timestamp())

        self.client.get(
            f'{self.project_path}/traces/spans/latencies',
            params={'_from': _from_ts, '_to': _to_ts},
        )

        call_kwargs = self.tracing_service.get_span_latencies.call_args.kwargs
        assert call_kwargs['_from'] is not None
        assert call_kwargs['_to'] is not None
        assert int(call_kwargs['_from'].timestamp()) == _from_ts
        assert int(call_kwargs['_to'].timestamp()) == _to_ts

    def test_get_span_latencies_grouped(self):
        mock_grouped = GroupedSpanLatenciesDTO(
            data=[
                GroupedSpanLatencyDTO(
                    category='invocation',
                    p50=100.0,
                    p90=200.0,
                    p95=250.0,
                    p99=400.0,
                    spans=[
                        SpanLatencyDTO(
                            span_name='invoke_openai',
                            p50=90.0,
                            p90=180.0,
                            p95=230.0,
                            p99=380.0,
                        )
                    ],
                ),
                GroupedSpanLatencyDTO(
                    category='cache',
                    p50=10.0,
                    p90=20.0,
                    p95=25.0,
                    p99=40.0,
                    spans=[
                        SpanLatencyDTO(
                            span_name='get_cached_response',
                            p50=5.0,
                            p90=10.0,
                            p95=15.0,
                            p99=20.0,
                        )
                    ],
                ),
            ]
        )
        self.tracing_service.get_grouped_span_latencies = MagicMock(
            return_value=mock_grouped
        )

        response = self.client.get(
            f'{self.project_path}/traces/spans/latencies',
            params={'grouped': True},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body['data']) == 2
        invocation = next(c for c in body['data'] if c['category'] == 'invocation')
        assert invocation['p50'] == 100.0
        assert len(invocation['spans']) == 1
        assert invocation['spans'][0]['spanName'] == 'invoke_openai'

    def test_get_span_latencies_grouped_passes_filters(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        mock_grouped = GroupedSpanLatenciesDTO(data=[])
        self.tracing_service.get_grouped_span_latencies = MagicMock(
            return_value=mock_grouped
        )

        _from_ts = int(base_time.timestamp())
        _to_ts = int((base_time + datetime.timedelta(hours=2)).timestamp())

        self.client.get(
            f'{self.project_path}/traces/spans/latencies',
            params={
                'grouped': True,
                '_from': _from_ts,
                '_to': _to_ts,
                'routes': ['route-a'],
            },
        )

        call_kwargs = self.tracing_service.get_grouped_span_latencies.call_args.kwargs
        assert call_kwargs['route_names'] == [_r('route-a')]
        assert call_kwargs['_from'] is not None
        assert call_kwargs['_to'] is not None

    def test_get_span_latencies_grouped_include_others(self):
        mock_grouped = GroupedSpanLatenciesDTO(data=[])
        self.tracing_service.get_grouped_span_latencies = MagicMock(
            return_value=mock_grouped
        )

        self.client.get(
            f'{self.project_path}/traces/spans/latencies',
            params={'grouped': True, 'include_others': True},
        )

        call_kwargs = self.tracing_service.get_grouped_span_latencies.call_args.kwargs
        assert call_kwargs['include_others'] is True

    def test_get_span_latencies_default_not_grouped(self):
        self.tracing_service.get_span_latencies = MagicMock(
            return_value=SpanLatenciesDTO(data=[])
        )

        self.client.get(f'{self.project_path}/traces/spans/latencies')

        self.tracing_service.get_span_latencies.assert_called_once()
        self.tracing_service.get_grouped_span_latencies.assert_not_called()

    # --- get_trace_by_id tests (no project_uuid in path) ---

    def test_get_trace_by_id_success(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        mock_trace = TraceDTO(
            trace_id='trace-123',
            request_uuid=uuid.UUID('12345678-1234-5678-1234-567812345678'),
            root_span_id='span-root',
            total_spans=3,
            duration_ms=150.5,
            error_count=0,
            created_at=int(base_time.timestamp()),
            latest_span_ts=int(base_time.timestamp()),
            output_tokens=100,
            input_tokens=50,
            total_tokens=150,
            route_name='my-route',
            api_key_uuid=UUID('660e8400-e29b-41d4-a716-446655440003'),
            api_key_name='my-api-key',
            group_uuid=UUID('550e8400-e29b-41d4-a716-446655440003'),
            group_name='my-group',
            tree=TreeNodeDTO(
                span_id='span-root',
                span_name='invoke',
                duration_ms=150.5,
                status_code='OK',
                output_tokens=100,
                input_tokens=50,
                total_tokens=150,
                error_count=0,
                created_at=int(base_time.timestamp()),
                children=[
                    TreeNodeDTO(
                        span_id='span-child-1',
                        span_name='cache_check',
                        duration_ms=5.0,
                        status_code='OK',
                        output_tokens=0,
                        input_tokens=0,
                        total_tokens=0,
                        error_count=0,
                        created_at=int(base_time.timestamp()),
                        children=[],
                    ),
                    TreeNodeDTO(
                        span_id='span-child-2',
                        span_name='llm_call',
                        duration_ms=140.0,
                        status_code='OK',
                        output_tokens=100,
                        input_tokens=50,
                        total_tokens=150,
                        error_count=0,
                        created_at=int(base_time.timestamp()),
                        children=[],
                    ),
                ],
            ),
        )
        self.tracing_service.get_trace_by_id = MagicMock(return_value=mock_trace)

        response = self.client.get(f'{self.project_path}/traces/trace-123')

        assert response.status_code == 200
        body = response.json()
        assert body['traceId'] == 'trace-123'
        assert body['requestUuid'] == '12345678-1234-5678-1234-567812345678'
        assert body['rootSpanId'] == 'span-root'
        assert body['totalSpans'] == 3
        assert body['durationMs'] == 150.5
        assert body['errorCount'] == 0
        assert body['routeName'] == 'my-route'
        assert body['apiKeyUuid'] == '660e8400-e29b-41d4-a716-446655440003'
        assert body['apiKeyName'] == 'my-api-key'
        assert body['groupUuid'] == '550e8400-e29b-41d4-a716-446655440003'
        assert body['groupName'] == 'my-group'

        tree = body['tree']
        assert tree['spanId'] == 'span-root'
        assert tree['spanName'] == 'invoke'
        assert len(tree['children']) == 2

        call_kwargs = self.tracing_service.get_trace_by_id.call_args.kwargs
        assert call_kwargs['trace_id'] == 'trace-123'

    def test_get_trace_by_id_without_request_uuid(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        mock_trace = TraceDTO(
            trace_id='trace-no-uuid',
            request_uuid=None,
            root_span_id='span-root',
            total_spans=3,
            duration_ms=150.5,
            error_count=0,
            created_at=int(base_time.timestamp()),
            latest_span_ts=int(base_time.timestamp()),
            output_tokens=100,
            input_tokens=50,
            total_tokens=150,
            route_name='my-route',
            api_key_uuid=UUID('660e8400-e29b-41d4-a716-446655440003'),
            api_key_name='my-api-key',
            group_uuid=UUID('550e8400-e29b-41d4-a716-446655440003'),
            group_name='my-group',
            tree=TreeNodeDTO(
                span_id='span-root',
                span_name='invoke',
                duration_ms=150.5,
                status_code='OK',
                output_tokens=100,
                input_tokens=50,
                total_tokens=150,
                error_count=0,
                created_at=int(base_time.timestamp()),
                children=[],
            ),
        )
        self.tracing_service.get_trace_by_id = MagicMock(return_value=mock_trace)

        response = self.client.get(f'{self.project_path}/traces/trace-no-uuid')

        assert response.status_code == 200
        body = response.json()
        assert body['traceId'] == 'trace-no-uuid'
        assert body.get('requestUuid') is None
        assert body['rootSpanId'] == 'span-root'

    def test_get_trace_by_id_not_found(self):
        self.tracing_service.get_trace_by_id = MagicMock(
            side_effect=GatewayNotFoundError("Trace 'nonexistent' not found")
        )

        response = self.client.get(f'{self.project_path}/traces/nonexistent')

        assert response.status_code == 404
        body = response.json()
        assert 'not found' in body['error']['message']

    def test_get_trace_by_id_hierarchical_tree(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        mock_trace = TraceDTO(
            trace_id='trace-tree',
            request_uuid=uuid.UUID('12345678-1234-5678-1234-567812345678'),
            root_span_id='span-root',
            total_spans=4,
            duration_ms=200.0,
            error_count=0,
            created_at=int(base_time.timestamp()),
            latest_span_ts=int(base_time.timestamp()),
            output_tokens=0,
            input_tokens=0,
            total_tokens=0,
            route_name='test-route',
            api_key_uuid=UUID('660e8400-e29b-41d4-a716-446655440003'),
            api_key_name='test-key',
            group_uuid=UUID('550e8400-e29b-41d4-a716-446655440003'),
            group_name='test-group',
            tree=TreeNodeDTO(
                span_id='span-root',
                span_name='request',
                duration_ms=200.0,
                status_code='OK',
                output_tokens=0,
                input_tokens=0,
                total_tokens=0,
                error_count=0,
                created_at=int(base_time.timestamp()),
                children=[
                    TreeNodeDTO(
                        span_id='span-child',
                        span_name='process',
                        duration_ms=180.0,
                        status_code='OK',
                        output_tokens=0,
                        input_tokens=0,
                        total_tokens=0,
                        error_count=0,
                        created_at=int(base_time.timestamp()),
                        children=[
                            TreeNodeDTO(
                                span_id='span-grandchild',
                                span_name='sub_process',
                                duration_ms=100.0,
                                status_code='OK',
                                output_tokens=0,
                                input_tokens=0,
                                total_tokens=0,
                                error_count=0,
                                created_at=int(base_time.timestamp()),
                                children=[],
                            ),
                        ],
                    ),
                ],
            ),
        )
        self.tracing_service.get_trace_by_id = MagicMock(return_value=mock_trace)

        response = self.client.get(f'{self.project_path}/traces/trace-tree')

        assert response.status_code == 200
        body = response.json()
        tree = body['tree']

        assert len(tree['children']) == 1
        child = tree['children'][0]
        assert child['spanId'] == 'span-child'
        assert len(child['children']) == 1
        grandchild = child['children'][0]
        assert grandchild['spanId'] == 'span-grandchild'
        assert grandchild['children'] == []

    def test_get_trace_by_id_with_attributes(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        mock_trace = TraceDTO(
            trace_id='trace-attrs',
            request_uuid=uuid.UUID('12345678-1234-5678-1234-567812345678'),
            root_span_id='span-1',
            total_spans=1,
            duration_ms=50.0,
            error_count=0,
            created_at=int(base_time.timestamp()),
            latest_span_ts=int(base_time.timestamp()),
            output_tokens=0,
            input_tokens=0,
            total_tokens=0,
            route_name='production-route',
            api_key_uuid=UUID('660e8400-e29b-41d4-a716-446655440004'),
            api_key_name='production-key',
            group_uuid=UUID('550e8400-e29b-41d4-a716-446655440004'),
            group_name='production-group',
            tree=TreeNodeDTO(
                span_id='span-1',
                span_name='invoke',
                duration_ms=50.0,
                status_code='OK',
                output_tokens=0,
                input_tokens=0,
                total_tokens=0,
                error_count=0,
                created_at=int(base_time.timestamp()),
                children=[],
            ),
        )
        self.tracing_service.get_trace_by_id = MagicMock(return_value=mock_trace)

        response = self.client.get(f'{self.project_path}/traces/trace-attrs')

        assert response.status_code == 200
        body = response.json()
        assert body['routeName'] == 'production-route'
        assert body['apiKeyUuid'] == '660e8400-e29b-41d4-a716-446655440004'
        assert body['apiKeyName'] == 'production-key'
        assert body['groupUuid'] == '550e8400-e29b-41d4-a716-446655440004'
        assert body['groupName'] == 'production-group'

    def test_get_trace_by_id_with_errors(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        mock_trace = TraceDTO(
            trace_id='trace-error',
            request_uuid=uuid.UUID('12345678-1234-5678-1234-567812345678'),
            root_span_id='span-1',
            total_spans=3,
            duration_ms=100.0,
            error_count=2,
            created_at=int(base_time.timestamp()),
            latest_span_ts=int(base_time.timestamp()),
            output_tokens=0,
            input_tokens=0,
            total_tokens=0,
            route_name='error-route',
            api_key_uuid=UUID('660e8400-e29b-41d4-a716-446655440003'),
            api_key_name='test-key',
            group_uuid=UUID('550e8400-e29b-41d4-a716-446655440003'),
            group_name='test-group',
            tree=TreeNodeDTO(
                span_id='span-1',
                span_name='invoke',
                duration_ms=100.0,
                status_code='ERROR',
                output_tokens=0,
                input_tokens=0,
                total_tokens=0,
                error_count=1,
                created_at=int(base_time.timestamp()),
                children=[
                    TreeNodeDTO(
                        span_id='span-2',
                        span_name='failed_call',
                        duration_ms=50.0,
                        status_code='ERROR',
                        output_tokens=0,
                        input_tokens=0,
                        total_tokens=0,
                        error_count=1,
                        created_at=int(base_time.timestamp()),
                        children=[],
                    ),
                ],
            ),
        )
        self.tracing_service.get_trace_by_id = MagicMock(return_value=mock_trace)

        response = self.client.get(f'{self.project_path}/traces/trace-error')

        assert response.status_code == 200
        body = response.json()
        assert body['errorCount'] == 2
        assert body['tree']['statusCode'] == 'ERROR'

    # --- get_traces (list) tests ---

    def test_get_traces(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        req_uuid = str(uuid.uuid4())
        group_uuid = uuid.uuid4()
        key_uuid = uuid.uuid4()
        mock_result = Page.create(
            items=[
                TraceDTO(
                    trace_id=req_uuid,
                    request_uuid=uuid.UUID(req_uuid),
                    route_name='my-route',
                    group_name='my-group',
                    group_uuid=group_uuid,
                    api_key_name='my-key',
                    api_key_uuid=key_uuid,
                    duration_ms=1500.0,
                    total_spans=3,
                    error_count=1,
                    input_tokens=200,
                    output_tokens=300,
                    total_tokens=500,
                    created_at=int(base_time.timestamp()),
                    latest_span_ts=int(
                        (base_time + datetime.timedelta(seconds=1)).timestamp()
                    ),
                )
            ],
            params=Params(page=1, size=50),
            total=1,
        )
        self.tracing_service.get_traces = MagicMock(return_value=mock_result)

        response = self.client.get(
            f'{self.project_path}/traces',
            params={
                '_from': int(base_time.timestamp()),
                '_to': int((base_time + datetime.timedelta(hours=1)).timestamp()),
                'routes': ['my-route'],
                'page': 1,
                'size': 50,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body['total'] == 1
        assert len(body['items']) == 1

        item = body['items'][0]
        assert item['traceId'] == req_uuid
        assert item['routeName'] == 'my-route'
        assert item['durationMs'] == 1500.0
        assert item['totalSpans'] == 3
        assert item['errorCount'] == 1
        assert item['inputTokens'] == 200
        assert item['outputTokens'] == 300
        assert item['totalTokens'] == 500

        call_kwargs = self.tracing_service.get_traces.call_args.kwargs
        assert call_kwargs['route_names'] == [_r('my-route')]
        assert call_kwargs['group_uuids'] is None
        assert call_kwargs['key_uuids'] is None

    def test_get_traces_no_filters(self):
        mock_result = Page.create(items=[], params=Params(page=1, size=50), total=0)
        self.tracing_service.get_traces = MagicMock(return_value=mock_result)

        response = self.client.get(f'{self.project_path}/traces')

        assert response.status_code == 200
        body = response.json()
        assert body['total'] == 0
        assert body['items'] == []

        call_kwargs = self.tracing_service.get_traces.call_args.kwargs
        assert call_kwargs['route_names'] is None
        assert call_kwargs['project_uuid'] == PROJECT_UUID
        assert call_kwargs['group_uuids'] is None
        assert call_kwargs['key_uuids'] is None
        assert call_kwargs['_from'] is None
        assert call_kwargs['_to'] is None

    def test_get_traces_passes_time_range_and_pagination(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        mock_result = Page.create(items=[], params=Params(page=3, size=10), total=0)
        self.tracing_service.get_traces = MagicMock(return_value=mock_result)

        _from_ts = int(base_time.timestamp())
        _to_ts = int((base_time + datetime.timedelta(hours=2)).timestamp())

        self.client.get(
            f'{self.project_path}/traces',
            params={'_from': _from_ts, '_to': _to_ts, '_page': 3, '_limit': 10},
        )

        call_kwargs = self.tracing_service.get_traces.call_args.kwargs
        assert int(call_kwargs['_from'].timestamp()) == _from_ts
        assert int(call_kwargs['_to'].timestamp()) == _to_ts
        assert call_kwargs['group_uuids'] is None
        assert call_kwargs['key_uuids'] is None

    def test_get_traces_with_groups_filter(self):
        mock_result = Page.create(items=[], params=Params(page=1, size=50), total=0)
        self.tracing_service.get_traces = MagicMock(return_value=mock_result)

        group_uuid_1 = '550e8400-e29b-41d4-a716-446655440001'
        group_uuid_2 = '550e8400-e29b-41d4-a716-446655440002'

        response = self.client.get(
            f'{self.project_path}/traces',
            params={
                'groups': [group_uuid_1, group_uuid_2],
            },
        )

        assert response.status_code == 200
        call_kwargs = self.tracing_service.get_traces.call_args.kwargs
        assert call_kwargs['group_uuids'] == [UUID(group_uuid_1), UUID(group_uuid_2)]
        assert call_kwargs['key_uuids'] is None

    def test_get_traces_with_keys_filter(self):
        mock_result = Page.create(items=[], params=Params(page=1, size=50), total=0)
        self.tracing_service.get_traces = MagicMock(return_value=mock_result)

        key_uuid_1 = '660e8400-e29b-41d4-a716-446655440001'
        key_uuid_2 = '660e8400-e29b-41d4-a716-446655440002'

        response = self.client.get(
            f'{self.project_path}/traces',
            params={
                'keys': [key_uuid_1, key_uuid_2],
            },
        )

        assert response.status_code == 200
        call_kwargs = self.tracing_service.get_traces.call_args.kwargs
        assert call_kwargs['group_uuids'] is None
        assert call_kwargs['key_uuids'] == [UUID(key_uuid_1), UUID(key_uuid_2)]

    def test_get_traces_with_all_filters(self):
        mock_result = Page.create(items=[], params=Params(page=1, size=50), total=0)
        self.tracing_service.get_traces = MagicMock(return_value=mock_result)

        group_uuid = '550e8400-e29b-41d4-a716-446655440001'
        key_uuid = '660e8400-e29b-41d4-a716-446655440001'

        response = self.client.get(
            f'{self.project_path}/traces',
            params={
                'routes': ['my-route'],
                'groups': [group_uuid],
                'keys': [key_uuid],
            },
        )

        assert response.status_code == 200
        call_kwargs = self.tracing_service.get_traces.call_args.kwargs
        assert call_kwargs['route_names'] == [_r('my-route')]
        assert call_kwargs['group_uuids'] == [UUID(group_uuid)]
        assert call_kwargs['key_uuids'] == [UUID(key_uuid)]

    def test_get_traces_with_tags_filter(self):
        mock_result = Page.create(items=[], params=Params(page=1, size=50), total=0)
        self.tracing_service.get_traces = MagicMock(return_value=mock_result)

        response = self.client.get(
            f'{self.project_path}/traces',
            params={'tags': ['env=prod', 'cost_center=retail']},
        )

        assert response.status_code == 200
        call_kwargs = self.tracing_service.get_traces.call_args.kwargs
        assert call_kwargs['tags'] == ['env=prod', 'cost_center=retail']

    def test_get_span_by_id_success(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        mock_span = SpanDTO(
            trace_id='trace-123',
            span_id='span-456',
            span_name='test-span',
            request_uuid=UUID('12345678-1234-5678-1234-567812345678'),
            duration_ms=150.0,
            created_at=int(base_time.timestamp()),
            output_tokens=100,
            input_tokens=50,
            total_tokens=150,
            route_name='my-route',
            api_key_uuid=UUID('660e8400-e29b-41d4-a716-446655440003'),
            api_key_name='my-api-key',
            group_uuid=UUID('550e8400-e29b-41d4-a716-446655440003'),
            group_name='my-group',
            attributes={'custom.attr': 'value'},
            status_message=None,
            error_count=0,
            error_events=[],
        )
        self.tracing_service.get_span_by_id = MagicMock(return_value=mock_span)

        response = self.client.get(
            f'{self.project_path}/traces/trace-123/spans/span-456'
        )

        assert response.status_code == 200
        body = response.json()
        assert body['traceId'] == 'trace-123'
        assert body['spanId'] == 'span-456'
        assert body['spanName'] == 'test-span'
        assert body['durationMs'] == 150.0
        assert body['routeName'] == 'my-route'
        assert body['errorCount'] == 0

        call_kwargs = self.tracing_service.get_span_by_id.call_args.kwargs
        assert call_kwargs['trace_id'] == 'trace-123'
        assert call_kwargs['span_id'] == 'span-456'

    def test_get_span_by_id_not_found(self):
        self.tracing_service.get_span_by_id = MagicMock(
            side_effect=GatewayNotFoundError(
                "Span 'nonexistent' not found in trace 'trace-123'"
            )
        )

        response = self.client.get(
            f'{self.project_path}/traces/trace-123/spans/nonexistent'
        )

        assert response.status_code == 404
        body = response.json()
        assert 'not found' in body['error']['message']

    def test_get_span_by_id_with_error_events(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        mock_span = SpanDTO(
            trace_id='trace-error',
            span_id='span-error',
            span_name='error-span',
            request_uuid=None,
            duration_ms=200.0,
            created_at=int(base_time.timestamp()),
            output_tokens=0,
            input_tokens=0,
            total_tokens=0,
            route_name='error-route',
            api_key_uuid=None,
            api_key_name=None,
            group_uuid=None,
            group_name=None,
            attributes={},
            status_message='Connection timeout',
            error_count=1,
            error_events=[
                ErrorEvents(
                    timestamp=base_time,
                    name='exception',
                    attributes={
                        'error.type': 'TimeoutError',
                        'error.message': 'Connection timed out',
                    },
                ),
            ],
        )
        self.tracing_service.get_span_by_id = MagicMock(return_value=mock_span)

        response = self.client.get(
            f'{self.project_path}/traces/trace-error/spans/span-error'
        )

        assert response.status_code == 200
        body = response.json()
        assert body['statusMessage'] == 'Connection timeout'
        assert body['errorCount'] == 1
        assert len(body['errorEvents']) == 1
        assert body['errorEvents'][0]['name'] == 'exception'

    def test_get_span_by_id_with_none_uuids(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        mock_span = SpanDTO(
            trace_id='trace-no-uuid',
            span_id='span-no-uuid',
            span_name='no-uuid-span',
            request_uuid=None,
            duration_ms=50.0,
            created_at=int(base_time.timestamp()),
            output_tokens=0,
            input_tokens=0,
            total_tokens=0,
            route_name=None,
            api_key_uuid=None,
            api_key_name=None,
            group_uuid=None,
            group_name=None,
            attributes={'key': 'value'},
            status_message=None,
            error_count=0,
            error_events=[],
        )
        self.tracing_service.get_span_by_id = MagicMock(return_value=mock_span)

        response = self.client.get(
            f'{self.project_path}/traces/trace-no-uuid/spans/span-no-uuid'
        )

        assert response.status_code == 200
        body = response.json()
        assert 'requestUuid' not in body
        assert 'apiKeyUuid' not in body
        assert 'groupUuid' not in body
        assert 'routeName' not in body
        assert body['traceId'] == 'trace-no-uuid'
        assert body['errorCount'] == 0
