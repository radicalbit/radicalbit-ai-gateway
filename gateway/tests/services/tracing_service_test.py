import datetime
import unittest
from unittest.mock import MagicMock
from uuid import UUID

from fastapi_pagination import Page, Params
import pytest

from radicalbit_ai_gateway.db.dao.otel_traces_dao import OtelTracesDAO
from radicalbit_ai_gateway.db.models.trace import (
    CategoryLatencies,
    CategorySpanLatencies,
    SpanLatencies,
    SpanRecord,
    SpanStats,
    TraceLatencies,
    TracesChartDataPoint,
)
from radicalbit_ai_gateway.models.trace_dto import (
    GroupedSpanLatenciesDTO,
    LatenciesDTO,
    SpanDTO,
    SpanLatenciesDTO,
    TraceDTO,
    TracesChartDataDTO,
    TraceStatus,
)
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.services.tracing_service import TracingService
from radicalbit_ai_gateway.utils.exceptions import GatewayNotFoundError

PROJECT_UUID = UUID('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')


class TracingServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.otel_traces_dao = MagicMock(spec_set=OtelTracesDAO)
        cls.key_service = MagicMock(spec_set=KeyService)
        cls.group_service = MagicMock(spec_set=GroupService)
        cls.tracing_service = TracingService(
            otel_traces_dao=cls.otel_traces_dao,
            key_service=cls.key_service,
            group_service=cls.group_service,
        )

    def setUp(self):
        # Default: name resolution returns names for common test UUIDs
        self.key_service.get_names_by_uuids.reset_mock()
        self.key_service.get_names_by_uuids.return_value = {
            UUID('660e8400-e29b-41d4-a716-446655440003'): 'test-key',
            UUID('660e8400-e29b-41d4-a716-446655440004'): 'my-key',
        }
        self.group_service.get_names_by_uuids.reset_mock()
        self.group_service.get_names_by_uuids.return_value = {
            UUID('550e8400-e29b-41d4-a716-446655440003'): 'test-group',
            UUID('550e8400-e29b-41d4-a716-446655440004'): 'my-group',
        }

    def test_get_traces_chart_data(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        self.otel_traces_dao.get_traces_chart_data = MagicMock(
            return_value=[
                TracesChartDataPoint(
                    bucket=base_time, trace_status='success', total_requests=7
                ),
                TracesChartDataPoint(
                    bucket=base_time, trace_status='error', total_requests=1
                ),
            ]
        )

        _from = base_time
        _to = base_time + datetime.timedelta(hours=1)

        res = self.tracing_service.get_traces_chart_data(
            project_uuid=PROJECT_UUID,
            route_names=['rb-gateway'],
            _from=_from,
            _to=_to,
            granularity='hours',
        )

        assert isinstance(res, TracesChartDataDTO)
        assert res.granularity == 'hours'
        assert len(res.timestamp) == 2
        assert res.total == 8
        series = {s.name: s.data for s in res.data}
        assert series['success'][0] == 7.0
        assert series['warning'][0] == 0.0
        assert series['error'][0] == 1.0

    def test_get_traces_chart_data_empty(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        self.otel_traces_dao.get_traces_chart_data = MagicMock(return_value=[])

        res = self.tracing_service.get_traces_chart_data(
            project_uuid=PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=2),
            granularity='hours',
        )

        assert res == TracesChartDataDTO(
            granularity='hours', timestamp=[], data=[], total=0
        )

    def test_get_traces_chart_data_merges_error_statuses(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        self.otel_traces_dao.get_traces_chart_data = MagicMock(
            return_value=[
                TracesChartDataPoint(
                    bucket=base_time, trace_status='success', total_requests=5
                ),
                TracesChartDataPoint(
                    bucket=base_time, trace_status='error', total_requests=2
                ),
                TracesChartDataPoint(
                    bucket=base_time, trace_status='success', total_requests=3
                ),
            ]
        )

        _from = base_time
        _to = base_time + datetime.timedelta(hours=0)

        res = self.tracing_service.get_traces_chart_data(
            project_uuid=PROJECT_UUID,
            route_names=None,
            _from=_from,
            _to=_to,
            granularity='hours',
        )

        series = {s.name: s.data for s in res.data}
        assert res.total == 10
        assert series['success'][0] == 8.0  # success(5) + success(3)
        assert series['warning'][0] == 0.0
        assert series['error'][0] == 2.0

    def test_get_traces_chart_data_no_route_filter(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        self.otel_traces_dao.get_traces_chart_data = MagicMock(
            return_value=[
                TracesChartDataPoint(
                    bucket=base_time, trace_status='success', total_requests=10
                ),
            ]
        )

        res = self.tracing_service.get_traces_chart_data(
            project_uuid=PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=0),
            granularity='hours',
        )

        self.otel_traces_dao.get_traces_chart_data.assert_called_once()
        call_args = self.otel_traces_dao.get_traces_chart_data.call_args
        assert call_args.args[1] is None  # route_names is None
        assert res.total == 10
        series = {s.name: s.data for s in res.data}
        assert series['success'][0] == 10.0
        assert series['warning'][0] == 0.0
        assert series['error'][0] == 0.0

    def test_get_latencies(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        self.otel_traces_dao.get_latencies = MagicMock(
            return_value=TraceLatencies(p50=100.0, p90=200.0, p95=250.0, p99=400.0)
        )

        res = self.tracing_service.get_latencies(
            project_uuid=PROJECT_UUID,
            route_names=['route-a'],
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
        )

        assert isinstance(res, LatenciesDTO)
        assert res.p50 == 100.0
        assert res.p90 == 200.0
        assert res.p95 == 250.0
        assert res.p99 == 400.0

    def test_get_latencies_no_data(self):
        self.otel_traces_dao.get_latencies = MagicMock(return_value=TraceLatencies())

        res = self.tracing_service.get_latencies(
            project_uuid=PROJECT_UUID,
            route_names=None,
            _from=None,
            _to=None,
        )

        assert isinstance(res, LatenciesDTO)
        assert res.p50 is None
        assert res.p90 is None
        assert res.p95 is None
        assert res.p99 is None

    def test_get_latencies_no_route_filter(self):
        self.otel_traces_dao.get_latencies = MagicMock(
            return_value=TraceLatencies(p50=50.0, p90=90.0, p95=95.0, p99=99.0)
        )

        self.tracing_service.get_latencies(
            project_uuid=PROJECT_UUID,
            route_names=None,
            _from=None,
            _to=None,
        )

        call_args = self.otel_traces_dao.get_latencies.call_args
        assert call_args.args[1] is None  # route_names is None

    def test_get_span_latencies(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        self.otel_traces_dao.get_span_latencies = MagicMock(
            return_value=[
                SpanLatencies(
                    span_name='invoke', p50=100.0, p90=200.0, p95=250.0, p99=400.0
                ),
                SpanLatencies(
                    span_name='set_cached_response',
                    p50=10.0,
                    p90=20.0,
                    p95=25.0,
                    p99=40.0,
                ),
            ]
        )

        res = self.tracing_service.get_span_latencies(
            project_uuid=PROJECT_UUID,
            route_names=['route-a'],
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
        )

        assert isinstance(res, SpanLatenciesDTO)
        assert len(res.data) == 2
        invoke = next(s for s in res.data if s.span_name == 'invoke')
        assert invoke.p50 == 100.0
        assert invoke.p90 == 200.0
        assert invoke.p95 == 250.0
        assert invoke.p99 == 400.0

    def test_get_span_latencies_empty(self):
        self.otel_traces_dao.get_span_latencies = MagicMock(return_value=[])

        res = self.tracing_service.get_span_latencies(
            project_uuid=PROJECT_UUID,
            route_names=None,
            _from=None,
            _to=None,
        )

        assert isinstance(res, SpanLatenciesDTO)
        assert res.data == []

    def test_get_span_latencies_no_route_filter(self):
        self.otel_traces_dao.get_span_latencies = MagicMock(
            return_value=[
                SpanLatencies(
                    span_name='invoke', p50=50.0, p90=90.0, p95=95.0, p99=99.0
                )
            ]
        )

        self.tracing_service.get_span_latencies(
            project_uuid=PROJECT_UUID,
            route_names=None,
            _from=None,
            _to=None,
        )

        call_args = self.otel_traces_dao.get_span_latencies.call_args
        assert call_args.args[1] is None  # route_names is None

    # --- get_grouped_span_latencies tests ---

    def test_get_grouped_span_latencies(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        self.otel_traces_dao.get_category_latencies = MagicMock(
            return_value=[
                CategoryLatencies(
                    category='invocation',
                    p50=100.0,
                    p90=200.0,
                    p95=250.0,
                    p99=400.0,
                ),
                CategoryLatencies(
                    category='cache', p50=10.0, p90=20.0, p95=25.0, p99=40.0
                ),
            ]
        )
        self.otel_traces_dao.get_category_span_latencies = MagicMock(
            return_value=[
                CategorySpanLatencies(
                    category='invocation',
                    span_name='invoke_openai',
                    p50=90.0,
                    p90=180.0,
                    p95=230.0,
                    p99=380.0,
                ),
                CategorySpanLatencies(
                    category='invocation',
                    span_name='invoke_anthropic',
                    p50=110.0,
                    p90=220.0,
                    p95=270.0,
                    p99=420.0,
                ),
                CategorySpanLatencies(
                    category='cache',
                    span_name='get_cached_response',
                    p50=5.0,
                    p90=10.0,
                    p95=15.0,
                    p99=20.0,
                ),
            ]
        )

        res = self.tracing_service.get_grouped_span_latencies(
            project_uuid=PROJECT_UUID,
            route_names=['route-a'],
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
        )

        assert isinstance(res, GroupedSpanLatenciesDTO)
        assert len(res.data) == 2

        invocation = next(c for c in res.data if c.category == 'invocation')
        assert invocation.p50 == 100.0
        assert len(invocation.spans) == 2
        span_names = {s.span_name for s in invocation.spans}
        assert span_names == {'invoke_openai', 'invoke_anthropic'}

        cache = next(c for c in res.data if c.category == 'cache')
        assert cache.p50 == 10.0
        assert len(cache.spans) == 1
        assert cache.spans[0].span_name == 'get_cached_response'

    def test_get_grouped_span_latencies_empty(self):
        self.otel_traces_dao.get_category_latencies = MagicMock(return_value=[])
        self.otel_traces_dao.get_category_span_latencies = MagicMock(return_value=[])

        res = self.tracing_service.get_grouped_span_latencies(
            project_uuid=PROJECT_UUID,
            route_names=None,
            _from=None,
            _to=None,
        )

        assert isinstance(res, GroupedSpanLatenciesDTO)
        assert res.data == []

    def test_get_grouped_span_latencies_with_others(self):
        self.otel_traces_dao.get_category_latencies = MagicMock(return_value=[])
        self.otel_traces_dao.get_category_span_latencies = MagicMock(return_value=[])

        self.tracing_service.get_grouped_span_latencies(
            project_uuid=PROJECT_UUID,
            route_names=None,
            _from=None,
            _to=None,
            include_others=True,
        )

        cat_call = self.otel_traces_dao.get_category_latencies.call_args
        span_call = self.otel_traces_dao.get_category_span_latencies.call_args
        assert cat_call.args[4] is True  # include_others
        assert span_call.args[4] is True  # include_others

    # --- get_trace_by_id tests ---

    def test_get_trace_by_id_not_found(self):
        """Test that GatewayNotFoundError is raised when trace not found."""
        self.otel_traces_dao.get_spans_by_trace_id = MagicMock(return_value=[])

        with pytest.raises(GatewayNotFoundError):
            self.tracing_service.get_trace_by_id(PROJECT_UUID, 'nonexistent-trace')

    def test_get_trace_by_id_single_span(self):
        """Test retrieving a trace with a single span."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        request_uuid = '12345678-1234-5678-1234-567812345678'
        self.otel_traces_dao.get_spans_by_trace_id = MagicMock(
            return_value=[
                SpanRecord(
                    timestamp=base_time,
                    trace_id='trace-123',
                    request_uuid=request_uuid,
                    span_id='span-1',
                    span_name='invoke',
                    service_name='ai-gateway',
                    duration=100_000_000,
                    status_code='Unset',
                    parent_span_id='',
                    route_name='test-route',
                    api_key_uuid='660e8400-e29b-41d4-a716-446655440003',
                    api_key_name='test-key',
                    group_uuid='550e8400-e29b-41d4-a716-446655440003',
                    group_name='test-group',
                )
            ]
        )

        result = self.tracing_service.get_trace_by_id(PROJECT_UUID, 'trace-123')

        assert isinstance(result, TraceDTO)
        assert result.trace_id == 'trace-123'
        assert result.request_uuid == UUID('12345678-1234-5678-1234-567812345678')
        assert result.root_span_id == 'span-1'
        assert result.trace_status == TraceStatus.SUCCESS

    def test_get_trace_by_id_includes_tags(self):
        """TraceDTO.tags comes straight from the root span's parsed tags."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        self.otel_traces_dao.get_spans_by_trace_id = MagicMock(
            return_value=[
                SpanRecord(
                    timestamp=base_time,
                    trace_id='trace-tags',
                    request_uuid='',
                    span_id='span-1',
                    span_name='invoke',
                    service_name='ai-gateway',
                    duration=100_000_000,
                    status_code='Unset',
                    parent_span_id='',
                    route_name='test-route',
                    api_key_uuid='',
                    api_key_name='',
                    group_uuid='',
                    group_name='',
                    tags=['env=prod', 'cost_center=retail'],
                )
            ]
        )

        result = self.tracing_service.get_trace_by_id(PROJECT_UUID, 'trace-tags')

        assert result.tags == ['env=prod', 'cost_center=retail']

    def test_get_trace_by_id_single_span_no_request_uuid(self):
        """Test retrieving a trace without request_uuid."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        self.otel_traces_dao.get_spans_by_trace_id = MagicMock(
            return_value=[
                SpanRecord(
                    timestamp=base_time,
                    trace_id='trace-no-uuid',
                    request_uuid='',
                    span_id='span-1',
                    span_name='invoke',
                    service_name='ai-gateway',
                    duration=100_000_000,
                    status_code='Unset',
                    parent_span_id='',
                    route_name='test-route',
                    api_key_uuid='660e8400-e29b-41d4-a716-446655440003',
                    api_key_name='test-key',
                    group_uuid='550e8400-e29b-41d4-a716-446655440003',
                    group_name='test-group',
                )
            ]
        )

        result = self.tracing_service.get_trace_by_id(PROJECT_UUID, 'trace-no-uuid')

        assert result.request_uuid is None
        assert result.total_spans == 1
        assert result.duration_ms == 100.0
        assert result.error_count == 0
        assert result.created_at == int(base_time.timestamp())
        assert result.latest_span_ts == int(base_time.timestamp())
        assert result.output_tokens == 0
        assert result.input_tokens == 0
        assert result.total_tokens == 0
        assert result.route_name == 'test-route'
        assert result.api_key_uuid == UUID('660e8400-e29b-41d4-a716-446655440003')
        assert result.api_key_name == 'test-key'
        assert result.group_uuid == UUID('550e8400-e29b-41d4-a716-446655440003')
        assert result.group_name == 'test-group'
        assert result.tree is not None
        assert result.tree.span_id == 'span-1'

    def test_get_trace_by_id_with_hierarchy(self):
        """Test building hierarchical tree from multiple spans."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        request_uuid = '12345678-1234-5678-1234-567812345678'
        self.otel_traces_dao.get_spans_by_trace_id = MagicMock(
            return_value=[
                SpanRecord(
                    timestamp=base_time,
                    trace_id='trace-hierarchy',
                    request_uuid=request_uuid,
                    span_id='span-root',
                    span_name='request',
                    service_name='ai-gateway',
                    duration=200_000_000,
                    status_code='Unset',
                    parent_span_id='',
                    route_name='test-route',
                    api_key_uuid='660e8400-e29b-41d4-a716-446655440003',
                    api_key_name='test-key',
                    group_uuid='550e8400-e29b-41d4-a716-446655440003',
                    group_name='test-group',
                ),
                SpanRecord(
                    timestamp=base_time + datetime.timedelta(milliseconds=10),
                    trace_id='trace-hierarchy',
                    request_uuid=request_uuid,
                    span_id='span-child',
                    span_name='process',
                    service_name='ai-gateway',
                    duration=180_000_000,
                    status_code='Unset',
                    parent_span_id='span-root',
                    route_name='test-route',
                    api_key_uuid='660e8400-e29b-41d4-a716-446655440003',
                    api_key_name='test-key',
                    group_uuid='550e8400-e29b-41d4-a716-446655440003',
                    group_name='test-group',
                ),
                SpanRecord(
                    timestamp=base_time + datetime.timedelta(milliseconds=20),
                    trace_id='trace-hierarchy',
                    request_uuid=request_uuid,
                    span_id='span-grandchild',
                    span_name='llm_call',
                    service_name='ai-gateway',
                    duration=100_000_000,
                    status_code='Unset',
                    parent_span_id='span-child',
                    route_name='test-route',
                    api_key_uuid='660e8400-e29b-41d4-a716-446655440003',
                    api_key_name='test-key',
                    group_uuid='550e8400-e29b-41d4-a716-446655440003',
                    group_name='test-group',
                ),
            ]
        )

        result = self.tracing_service.get_trace_by_id(PROJECT_UUID, 'trace-hierarchy')

        assert result.total_spans == 3
        assert result.root_span_id == 'span-root'
        assert result.trace_status == TraceStatus.SUCCESS
        # Verify tree structure
        assert result.tree is not None
        assert result.tree.span_id == 'span-root'
        assert len(result.tree.children) == 1
        child = result.tree.children[0]
        assert child.span_id == 'span-child'
        assert len(child.children) == 1
        grandchild = child.children[0]
        assert grandchild.span_id == 'span-grandchild'
        assert grandchild.children == []

    def test_get_trace_by_id_with_errors(self):
        """Test error count is calculated correctly — root span error gives ERROR."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        request_uuid = '12345678-1234-5678-1234-567812345678'
        self.otel_traces_dao.get_spans_by_trace_id = MagicMock(
            return_value=[
                SpanRecord(
                    timestamp=base_time,
                    trace_id='trace-error',
                    request_uuid=request_uuid,
                    span_id='span-1',
                    span_name='request',
                    service_name='ai-gateway',
                    duration=100_000_000,
                    status_code='ERROR',
                    parent_span_id='',
                    route_name='test-route',
                    api_key_uuid='660e8400-e29b-41d4-a716-446655440003',
                    api_key_name='test-key',
                    group_uuid='550e8400-e29b-41d4-a716-446655440003',
                    group_name='test-group',
                ),
                SpanRecord(
                    timestamp=base_time + datetime.timedelta(milliseconds=10),
                    trace_id='trace-error',
                    request_uuid=request_uuid,
                    span_id='span-2',
                    span_name='child',
                    service_name='ai-gateway',
                    duration=50_000_000,
                    status_code='ERROR',
                    parent_span_id='span-1',
                    route_name='test-route',
                    api_key_uuid='660e8400-e29b-41d4-a716-446655440003',
                    api_key_name='test-key',
                    group_uuid='550e8400-e29b-41d4-a716-446655440003',
                    group_name='test-group',
                ),
                SpanRecord(
                    timestamp=base_time + datetime.timedelta(milliseconds=20),
                    trace_id='trace-error',
                    request_uuid=request_uuid,
                    span_id='span-3',
                    span_name='ok_child',
                    service_name='ai-gateway',
                    duration=30_000_000,
                    status_code='Unset',
                    parent_span_id='span-1',
                    route_name='test-route',
                    api_key_uuid='660e8400-e29b-41d4-a716-446655440003',
                    api_key_name='test-key',
                    group_uuid='550e8400-e29b-41d4-a716-446655440003',
                    group_name='test-group',
                ),
            ]
        )

        result = self.tracing_service.get_trace_by_id(PROJECT_UUID, 'trace-error')

        assert result.error_count == 2
        assert result.trace_status == TraceStatus.ERROR

    def test_get_trace_by_id_duration_calculation(self):
        """Test that duration is calculated from max span duration."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        request_uuid = '12345678-1234-5678-1234-567812345678'
        self.otel_traces_dao.get_spans_by_trace_id = MagicMock(
            return_value=[
                SpanRecord(
                    timestamp=base_time,
                    trace_id='trace-duration',
                    request_uuid=request_uuid,
                    span_id='span-1',
                    span_name='root',
                    service_name='ai-gateway',
                    duration=200_000_000,  # 200ms
                    status_code='Unset',
                    parent_span_id='',
                    route_name='test-route',
                    api_key_uuid='660e8400-e29b-41d4-a716-446655440003',
                    api_key_name='test-key',
                    group_uuid='550e8400-e29b-41d4-a716-446655440003',
                    group_name='test-group',
                ),
                SpanRecord(
                    timestamp=base_time + datetime.timedelta(milliseconds=10),
                    trace_id='trace-duration',
                    request_uuid=request_uuid,
                    span_id='span-2',
                    span_name='child',
                    service_name='ai-gateway',
                    duration=350_000_000,  # 350ms - this is the max
                    status_code='Unset',
                    parent_span_id='span-1',
                    route_name='test-route',
                    api_key_uuid='660e8400-e29b-41d4-a716-446655440003',
                    api_key_name='test-key',
                    group_uuid='550e8400-e29b-41d4-a716-446655440003',
                    group_name='test-group',
                ),
            ]
        )

        result = self.tracing_service.get_trace_by_id(PROJECT_UUID, 'trace-duration')

        # Duration should be the max of all spans
        assert result.duration_ms == 350.0
        assert result.trace_status == TraceStatus.SUCCESS

    def test_get_trace_by_id_warning_child_error(self):
        """Test WARNING: root span OK but child span has error."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        request_uuid = '12345678-1234-5678-1234-567812345678'
        self.otel_traces_dao.get_spans_by_trace_id = MagicMock(
            return_value=[
                SpanRecord(
                    timestamp=base_time,
                    trace_id='trace-warn',
                    request_uuid=request_uuid,
                    span_id='span-root',
                    span_name='request',
                    service_name='ai-gateway',
                    duration=200_000_000,
                    status_code='Unset',
                    parent_span_id='',
                    route_name='test-route',
                    api_key_uuid='660e8400-e29b-41d4-a716-446655440003',
                    api_key_name='test-key',
                    group_uuid='550e8400-e29b-41d4-a716-446655440003',
                    group_name='test-group',
                ),
                SpanRecord(
                    timestamp=base_time + datetime.timedelta(milliseconds=10),
                    trace_id='trace-warn',
                    request_uuid=request_uuid,
                    span_id='span-child',
                    span_name='llm_call',
                    service_name='ai-gateway',
                    duration=100_000_000,
                    status_code='ERROR',
                    parent_span_id='span-root',
                    route_name='test-route',
                    api_key_uuid='660e8400-e29b-41d4-a716-446655440003',
                    api_key_name='test-key',
                    group_uuid='550e8400-e29b-41d4-a716-446655440003',
                    group_name='test-group',
                ),
            ]
        )

        result = self.tracing_service.get_trace_by_id(PROJECT_UUID, 'trace-warn')

        assert result.error_count == 1
        assert result.trace_status == TraceStatus.WARNING

    # --- get_traces (list) tests ---

    def test_get_traces(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        trace_id = 'trace-123'
        request_uuid = '12345678-1234-5678-1234-567812345678'

        # Create a mock row object that has attributes
        mock_row = MagicMock()
        mock_row.trace_id = trace_id
        mock_row.request_uuid = request_uuid
        mock_row.route_name = 'my-route'
        mock_row.group_name = 'my-group'
        mock_row.group_uuid = '550e8400-e29b-41d4-a716-446655440004'
        mock_row.api_key_name = 'my-key'
        mock_row.api_key_uuid = '660e8400-e29b-41d4-a716-446655440004'
        mock_row.duration_ms = 1500.0
        mock_row.created_at = base_time

        mock_page = MagicMock(spec=Page)
        mock_page.items = [mock_row]
        mock_page.total = 1

        self.otel_traces_dao.get_root_traces_paginated = MagicMock(
            return_value=mock_page
        )
        self.otel_traces_dao.get_spans_stats_by_trace_ids = MagicMock(
            return_value={
                trace_id: SpanStats(
                    span_count=3,
                    error_count=1,
                    input_tokens=200,
                    output_tokens=300,
                    last_span=base_time + datetime.timedelta(seconds=1),
                )
            }
        )
        self.otel_traces_dao.get_root_span_error_by_trace_ids = MagicMock(
            return_value=set()  # Root span has no error
        )

        res = self.tracing_service.get_traces(
            project_uuid=PROJECT_UUID,
            route_names=['my-route'],
            group_uuids=None,
            key_uuids=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            params=Params(page=1, size=50),
        )

        assert isinstance(res, Page)
        assert res.total == 1
        assert res.page == 1
        assert res.size == 50
        assert len(res.items) == 1

        item = res.items[0]
        assert item.trace_id == trace_id
        assert item.request_uuid == UUID(request_uuid)
        assert item.route_name == 'my-route'
        assert item.group_name == 'my-group'
        assert item.group_uuid == UUID('550e8400-e29b-41d4-a716-446655440004')
        assert item.api_key_name == 'my-key'
        assert item.api_key_uuid == UUID('660e8400-e29b-41d4-a716-446655440004')
        assert item.duration_ms == 1500.0
        assert item.total_spans == 3
        assert item.error_count == 1
        assert item.trace_status == TraceStatus.WARNING  # Child errors, root OK
        assert item.input_tokens == 200
        assert item.output_tokens == 300
        assert item.total_tokens == 500
        assert item.created_at == int(base_time.timestamp())
        assert item.latest_span_ts == int(
            (base_time + datetime.timedelta(seconds=1)).timestamp()
        )

    def test_get_traces_includes_tags(self):
        """TraceDTO.tags comes straight from the paginated row, no extra DAO call."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        trace_id = 'trace-tags'

        mock_row = MagicMock()
        mock_row.trace_id = trace_id
        mock_row.request_uuid = ''
        mock_row.route_name = 'my-route'
        mock_row.group_name = None
        mock_row.group_uuid = ''
        mock_row.api_key_name = None
        mock_row.api_key_uuid = ''
        mock_row.duration_ms = 1500.0
        mock_row.created_at = base_time
        mock_row.tags = ['env=prod']

        mock_page = MagicMock(spec=Page)
        mock_page.items = [mock_row]
        mock_page.total = 1

        self.otel_traces_dao.get_root_traces_paginated = MagicMock(
            return_value=mock_page
        )
        self.otel_traces_dao.get_spans_stats_by_trace_ids = MagicMock(return_value={})
        self.otel_traces_dao.get_root_span_error_by_trace_ids = MagicMock(
            return_value=set()
        )

        res = self.tracing_service.get_traces(
            project_uuid=PROJECT_UUID,
            route_names=None,
            group_uuids=None,
            key_uuids=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            params=Params(page=1, size=50),
            tags=['env=prod'],
        )

        assert res.items[0].tags == ['env=prod']
        call_args = self.otel_traces_dao.get_root_traces_paginated.call_args
        assert call_args.kwargs['tags'] == ['env=prod']

    def test_get_traces_page_offset_conversion(self):
        """Test that params are passed correctly to the paginated DAO method."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        mock_page = MagicMock(spec=Page)
        mock_page.items = []
        mock_page.total = 100

        self.otel_traces_dao.get_root_traces_paginated = MagicMock(
            return_value=mock_page
        )

        self.tracing_service.get_traces(
            project_uuid=PROJECT_UUID,
            route_names=None,
            group_uuids=None,
            key_uuids=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            params=Params(page=3, size=10),
        )

        call_args = self.otel_traces_dao.get_root_traces_paginated.call_args
        # Verify params are passed correctly (now at position 6)
        assert call_args.args[6] == Params(page=3, size=10)

    def test_get_traces_empty(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        mock_page = MagicMock(spec=Page)
        mock_page.items = []
        mock_page.total = 0

        self.otel_traces_dao.get_root_traces_paginated = MagicMock(
            return_value=mock_page
        )

        res = self.tracing_service.get_traces(
            project_uuid=PROJECT_UUID,
            route_names=None,
            group_uuids=None,
            key_uuids=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            params=Params(page=1, size=50),
        )

        assert isinstance(res, Page)
        assert res.total == 0
        assert res.items == []

    def test_get_traces_no_span_data(self):
        """Test that get_traces uses defaults when no span stats available."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        trace_id = 'trace-456'

        # Create a mock row object that has attributes
        mock_row = MagicMock()
        mock_row.trace_id = trace_id
        mock_row.request_uuid = ''
        mock_row.route_name = 'my-route'
        mock_row.group_name = ''
        mock_row.group_uuid = ''
        mock_row.api_key_name = 'my-key'
        mock_row.api_key_uuid = ''
        mock_row.duration_ms = 500.0
        mock_row.created_at = base_time

        mock_page = MagicMock(spec=Page)
        mock_page.items = [mock_row]
        mock_page.total = 1

        self.otel_traces_dao.get_root_traces_paginated = MagicMock(
            return_value=mock_page
        )
        self.otel_traces_dao.get_spans_stats_by_trace_ids = MagicMock(return_value={})
        self.otel_traces_dao.get_root_span_error_by_trace_ids = MagicMock(
            return_value=set()
        )

        res = self.tracing_service.get_traces(
            project_uuid=PROJECT_UUID,
            route_names=None,
            group_uuids=None,
            key_uuids=None,
            _from=None,
            _to=None,
            params=Params(page=1, size=50),
        )

        item = res.items[0]
        assert item.total_spans == 0
        assert item.error_count == 0
        assert item.trace_status == TraceStatus.SUCCESS  # No errors
        assert item.total_tokens == 0
        assert item.request_uuid is None
        # When no span data, use created_at as fallback for latest_span_ts
        assert item.latest_span_ts == int(base_time.timestamp())

    def test_get_traces_trace_status_ok(self):
        """Test trace status SUCCESS: root OK + no child errors."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        trace_id = 'trace-ok'
        request_uuid = '11111111-1111-1111-1111-111111111111'

        mock_row = MagicMock()
        mock_row.trace_id = trace_id
        mock_row.request_uuid = request_uuid
        mock_row.route_name = 'my-route'
        mock_row.group_name = ''
        mock_row.group_uuid = ''
        mock_row.api_key_name = ''
        mock_row.api_key_uuid = ''
        mock_row.duration_ms = 100.0
        mock_row.created_at = base_time

        mock_page = MagicMock(spec=Page)
        mock_page.items = [mock_row]
        mock_page.total = 1

        self.otel_traces_dao.get_root_traces_paginated = MagicMock(
            return_value=mock_page
        )
        self.otel_traces_dao.get_spans_stats_by_trace_ids = MagicMock(
            return_value={
                trace_id: SpanStats(
                    span_count=1,
                    error_count=0,
                    input_tokens=0,
                    output_tokens=0,
                    last_span=base_time,
                )
            }
        )
        self.otel_traces_dao.get_root_span_error_by_trace_ids = MagicMock(
            return_value=set()
        )

        res = self.tracing_service.get_traces(
            project_uuid=PROJECT_UUID,
            route_names=None,
            group_uuids=None,
            key_uuids=None,
            _from=None,
            _to=None,
            params=Params(page=1, size=50),
        )

        item = res.items[0]
        assert item.error_count == 0
        assert item.trace_status == TraceStatus.SUCCESS

    def test_get_traces_trace_status_warning(self):
        """Test trace status WARNING: root OK + child errors."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        trace_id = 'trace-warning'
        request_uuid = '22222222-2222-2222-2222-222222222222'

        mock_row = MagicMock()
        mock_row.trace_id = trace_id
        mock_row.request_uuid = request_uuid
        mock_row.route_name = 'my-route'
        mock_row.group_name = ''
        mock_row.group_uuid = ''
        mock_row.api_key_name = ''
        mock_row.api_key_uuid = ''
        mock_row.duration_ms = 100.0
        mock_row.created_at = base_time

        mock_page = MagicMock(spec=Page)
        mock_page.items = [mock_row]
        mock_page.total = 1

        self.otel_traces_dao.get_root_traces_paginated = MagicMock(
            return_value=mock_page
        )
        self.otel_traces_dao.get_spans_stats_by_trace_ids = MagicMock(
            return_value={
                trace_id: SpanStats(
                    span_count=3,
                    error_count=1,
                    input_tokens=0,
                    output_tokens=0,
                    last_span=base_time,
                )
            }
        )
        self.otel_traces_dao.get_root_span_error_by_trace_ids = MagicMock(
            return_value=set()  # Root OK
        )

        res = self.tracing_service.get_traces(
            project_uuid=PROJECT_UUID,
            route_names=None,
            group_uuids=None,
            key_uuids=None,
            _from=None,
            _to=None,
            params=Params(page=1, size=50),
        )

        item = res.items[0]
        assert item.error_count == 1
        assert item.trace_status == TraceStatus.WARNING

    def test_get_traces_trace_status_error(self):
        """Test trace status ERROR: root span has error."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        trace_id = 'trace-error'
        request_uuid = '33333333-3333-3333-3333-333333333333'

        mock_row = MagicMock()
        mock_row.trace_id = trace_id
        mock_row.request_uuid = request_uuid
        mock_row.route_name = 'my-route'
        mock_row.group_name = ''
        mock_row.group_uuid = ''
        mock_row.api_key_name = ''
        mock_row.api_key_uuid = ''
        mock_row.duration_ms = 100.0
        mock_row.created_at = base_time

        mock_page = MagicMock(spec=Page)
        mock_page.items = [mock_row]
        mock_page.total = 1

        self.otel_traces_dao.get_root_traces_paginated = MagicMock(
            return_value=mock_page
        )
        self.otel_traces_dao.get_spans_stats_by_trace_ids = MagicMock(
            return_value={
                trace_id: SpanStats(
                    span_count=2,
                    error_count=1,
                    input_tokens=0,
                    output_tokens=0,
                    last_span=base_time,
                )
            }
        )
        self.otel_traces_dao.get_root_span_error_by_trace_ids = MagicMock(
            return_value={trace_id}  # Root span has error
        )

        res = self.tracing_service.get_traces(
            project_uuid=PROJECT_UUID,
            route_names=None,
            group_uuids=None,
            key_uuids=None,
            _from=None,
            _to=None,
            params=Params(page=1, size=50),
        )

        item = res.items[0]
        assert item.error_count == 1
        assert item.trace_status == TraceStatus.ERROR

    def test_get_traces_with_group_filter(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        mock_page = MagicMock(spec=Page)
        mock_page.items = []
        mock_page.total = 0

        self.otel_traces_dao.get_root_traces_paginated = MagicMock(
            return_value=mock_page
        )

        self.tracing_service.get_traces(
            project_uuid=PROJECT_UUID,
            route_names=None,
            group_uuids=[
                UUID('550e8400-e29b-41d4-a716-446655440001'),
                UUID('550e8400-e29b-41d4-a716-446655440002'),
            ],
            key_uuids=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            params=Params(page=1, size=50),
        )

        call_args = self.otel_traces_dao.get_root_traces_paginated.call_args
        assert call_args.args[2] == [
            UUID('550e8400-e29b-41d4-a716-446655440001'),
            UUID('550e8400-e29b-41d4-a716-446655440002'),
        ]  # group_uuids
        assert call_args.args[3] is None  # key_uuids

    def test_get_traces_with_key_filter(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        mock_page = MagicMock(spec=Page)
        mock_page.items = []
        mock_page.total = 0

        self.otel_traces_dao.get_root_traces_paginated = MagicMock(
            return_value=mock_page
        )

        self.tracing_service.get_traces(
            project_uuid=PROJECT_UUID,
            route_names=None,
            group_uuids=None,
            key_uuids=[
                UUID('660e8400-e29b-41d4-a716-446655440001'),
                UUID('660e8400-e29b-41d4-a716-446655440002'),
            ],
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            params=Params(page=1, size=50),
        )

        call_args = self.otel_traces_dao.get_root_traces_paginated.call_args
        assert call_args.args[2] is None  # group_uuids
        assert call_args.args[3] == [
            UUID('660e8400-e29b-41d4-a716-446655440001'),
            UUID('660e8400-e29b-41d4-a716-446655440002'),
        ]  # key_uuids

    def test_get_traces_with_combined_filters(self):
        """Test that all filters are passed correctly to DAO when combined."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        mock_page = MagicMock(spec=Page)
        mock_page.items = []
        mock_page.total = 0

        self.otel_traces_dao.get_root_traces_paginated = MagicMock(
            return_value=mock_page
        )

        self.tracing_service.get_traces(
            project_uuid=PROJECT_UUID,
            route_names=['route-a', 'route-b'],
            group_uuids=[UUID('550e8400-e29b-41d4-a716-446655440001')],
            key_uuids=[
                UUID('660e8400-e29b-41d4-a716-446655440001'),
                UUID('660e8400-e29b-41d4-a716-446655440002'),
            ],
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            params=Params(page=2, size=25),
        )

        call_args = self.otel_traces_dao.get_root_traces_paginated.call_args
        assert call_args.args[1] == ['route-a', 'route-b']  # route_names
        assert call_args.args[2] == [
            UUID('550e8400-e29b-41d4-a716-446655440001')
        ]  # group_uuids
        assert call_args.args[3] == [
            UUID('660e8400-e29b-41d4-a716-446655440001'),
            UUID('660e8400-e29b-41d4-a716-446655440002'),
        ]  # key_uuids
        assert call_args.args[6] == Params(page=2, size=25)  # params

    # --- get_span_by_id tests ---

    def test_get_span_by_id_not_found(self):
        """Test that GatewayNotFoundError is raised when span not found."""
        self.otel_traces_dao.get_span_by_trace_and_span_id = MagicMock(
            return_value=None
        )

        with pytest.raises(GatewayNotFoundError) as exc_info:
            self.tracing_service.get_span_by_id(PROJECT_UUID, 'trace-123', 'span-456')

        assert "Span 'span-456' not found in trace 'trace-123'" in str(exc_info.value)

    def test_get_span_by_id_success(self):
        """Test retrieving a span with all fields."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        self.otel_traces_dao.get_span_by_trace_and_span_id = MagicMock(
            return_value=SpanRecord(
                timestamp=base_time,
                trace_id='trace-123',
                request_uuid='12345678-1234-5678-1234-567812345678',
                span_id='span-456',
                span_name='invoke',
                service_name='ai-gateway',
                duration=100_000_000,  # 100ms in nanoseconds
                status_code='Unset',
                parent_span_id='parent-span',
                route_name='test-route',
                api_key_uuid='660e8400-e29b-41d4-a716-446655440003',
                api_key_name='test-key-clickhouse',  # stale name
                group_uuid='550e8400-e29b-41d4-a716-446655440003',
                group_name='test-group-clickhouse',  # stale name
                output_tokens='100',
                input_tokens='200',
                total_tokens='300',
                span_attributes={'custom.attr': 'value'},
                status_message=None,
                events=[],
            )
        )

        self.key_service.get_names_by_uuids.return_value = {
            UUID('660e8400-e29b-41d4-a716-446655440003'): 'test-key'
        }
        self.group_service.get_names_by_uuids.return_value = {
            UUID('550e8400-e29b-41d4-a716-446655440003'): 'test-group'
        }

        result = self.tracing_service.get_span_by_id(
            PROJECT_UUID, 'trace-123', 'span-456'
        )

        assert isinstance(result, SpanDTO)
        assert result.trace_id == 'trace-123'
        assert result.span_id == 'span-456'
        assert result.span_name == 'invoke'
        assert result.request_uuid == UUID('12345678-1234-5678-1234-567812345678')
        assert result.duration_ms == 100.0  # 100ms
        assert result.created_at == int(base_time.timestamp())
        assert result.output_tokens == 100
        assert result.input_tokens == 200
        assert result.total_tokens == 300
        assert result.route_name == 'test-route'
        assert result.api_key_uuid == UUID('660e8400-e29b-41d4-a716-446655440003')
        assert result.api_key_name == 'test-key'
        assert result.group_uuid == UUID('550e8400-e29b-41d4-a716-446655440003')
        assert result.group_name == 'test-group'
        assert result.attributes == {'custom.attr': 'value'}
        assert result.status_message is None
        assert result.error_count == 0
        assert result.error_events == []

    def test_get_span_by_id_with_error_events(self):
        """Test that error events are converted from events list."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        self.otel_traces_dao.get_span_by_trace_and_span_id = MagicMock(
            return_value=SpanRecord(
                timestamp=base_time,
                trace_id='trace-123',
                request_uuid='12345678-1234-5678-1234-567812345678',
                span_id='span-456',
                span_name='invoke',
                service_name='ai-gateway',
                duration=100_000_000,
                status_code='Error',
                parent_span_id='',
                route_name='test-route',
                api_key_uuid='660e8400-e29b-41d4-a716-446655440003',
                api_key_name='test-key',
                group_uuid='550e8400-e29b-41d4-a716-446655440003',
                group_name='test-group',
                output_tokens='50',
                input_tokens='100',
                total_tokens='150',
                span_attributes={},
                status_message='Something went wrong',
                events=[
                    {
                        'name': 'exception',
                        'timestamp': '2025-01-08T10:00:00Z',
                        'attributes': {'error.type': 'TimeoutError'},
                    },
                    {
                        'name': 'exception',
                        'timestamp': '2025-01-08T10:00:02Z',
                        'attributes': {'error.type': 'ValueError'},
                    },
                ],
            )
        )

        result = self.tracing_service.get_span_by_id(
            PROJECT_UUID, 'trace-123', 'span-456'
        )

        assert len(result.error_events) == 2
        assert result.error_count == 2
        # Check first exception event
        assert result.error_events[0].name == 'exception'
        assert result.error_events[0].attributes == {'error.type': 'TimeoutError'}
        # Check second exception event
        assert result.error_events[1].name == 'exception'
        assert result.error_events[1].attributes == {'error.type': 'ValueError'}
        # Check status_message is passed through
        assert result.status_message == 'Something went wrong'

    def test_get_span_by_id_without_events(self):
        """Test that empty error_events list is returned when no events."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        self.otel_traces_dao.get_span_by_trace_and_span_id = MagicMock(
            return_value=SpanRecord(
                timestamp=base_time,
                trace_id='trace-123',
                request_uuid='12345678-1234-5678-1234-567812345678',
                span_id='span-456',
                span_name='invoke',
                service_name='ai-gateway',
                duration=100_000_000,
                status_code='Unset',
                parent_span_id='',
                route_name='test-route',
                api_key_uuid='660e8400-e29b-41d4-a716-446655440003',
                api_key_name='test-key',
                group_uuid='550e8400-e29b-41d4-a716-446655440003',
                group_name='test-group',
                output_tokens='',
                input_tokens='',
                total_tokens='',
                span_attributes={},
                status_message=None,
                events=[],
            )
        )

        result = self.tracing_service.get_span_by_id(
            PROJECT_UUID, 'trace-123', 'span-456'
        )

        assert result.error_events == []
        assert result.error_count == 0
        # Empty strings for tokens should be parsed as 0
        assert result.output_tokens == 0
        assert result.input_tokens == 0
        assert result.total_tokens == 0

    def test_get_span_by_id_with_empty_uuids(self):
        """Test that empty UUIDs are handled correctly and converted to None."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        self.otel_traces_dao.get_span_by_trace_and_span_id = MagicMock(
            return_value=SpanRecord(
                timestamp=base_time,
                trace_id='trace-123',
                request_uuid='',
                span_id='span-456',
                span_name='invoke',
                service_name='ai-gateway',
                duration=100_000_000,
                status_code='Unset',
                parent_span_id='',
                route_name='',
                api_key_uuid='',
                api_key_name='',
                group_uuid='',
                group_name='',
                output_tokens='10',
                input_tokens='20',
                total_tokens='30',
                span_attributes={'key': 'value'},
                status_message=None,
                events=[],
            )
        )

        result = self.tracing_service.get_span_by_id(
            PROJECT_UUID, 'trace-123', 'span-456'
        )

        assert result.request_uuid is None
        assert result.api_key_uuid is None
        assert result.group_uuid is None
        assert result.route_name is None
        assert result.api_key_name is None
        assert result.group_name is None
        assert result.error_count == 0
