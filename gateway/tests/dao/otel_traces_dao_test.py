import datetime
import math
from uuid import UUID

from fastapi_pagination import Params
import pytest

from tests.common import db_mock
from tests.common.db_integration_ch import DatabaseIntegrationClickhouse
from tests.common.db_mock import TEST_PROJECT_UUID

from radicalbit_ai_gateway.db.dao.otel_traces_dao import OtelTracesDAO


class OtelTracesDAOTest(DatabaseIntegrationClickhouse):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.otel_traces_dao = OtelTracesDAO(cls.db)

    # --- get_span_latencies ---

    def test_get_span_latencies_empty(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        res = self.otel_traces_dao.get_span_latencies(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
        )

        assert res == []

    def test_get_span_latencies_returns_percentiles(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        # Insert 4 spans for 'invoke': 100ms, 200ms, 300ms, 400ms (in nanoseconds)
        durations_ms = [100, 200, 300, 400]
        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(minutes=i),
                span_name='invoke',
                duration_ns=ms * 1_000_000,
            )
            for i, ms in enumerate(durations_ms)
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_span_latencies(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
        )

        assert len(res) == 1
        span = res[0]
        assert span.span_name == 'invoke'
        assert span.p50 is not None
        assert span.p90 is not None
        assert span.p95 is not None
        assert span.p99 is not None
        # p50 should be between 100 and 400
        assert 100 <= span.p50 <= 400

    def test_get_span_latencies_groups_by_span_name(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time, span_name='invoke', duration_ns=100 * 1_000_000
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(minutes=1),
                span_name='invoke',
                duration_ns=200 * 1_000_000,
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(minutes=2),
                span_name='set_cached_response',
                duration_ns=10 * 1_000_000,
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(minutes=3),
                span_name='set_cached_response',
                duration_ns=20 * 1_000_000,
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_span_latencies(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
        )

        assert len(res) == 2
        span_names = {r.span_name for r in res}
        assert span_names == {'invoke', 'set_cached_response'}

    def test_get_span_latencies_filters_by_time_range(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time, span_name='invoke', duration_ns=100 * 1_000_000
            ),
            # Outside time range
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(hours=3),
                span_name='other_span',
                duration_ns=999 * 1_000_000,
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_span_latencies(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
        )

        span_names = {r.span_name for r in res}
        assert 'invoke' in span_names
        assert 'other_span' not in span_names

    def test_get_span_latencies_no_time_filter(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time, span_name='invoke', duration_ns=100 * 1_000_000
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(days=10),
                span_name='invoke',
                duration_ns=200 * 1_000_000,
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_span_latencies(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=None,
            _to=None,
        )

        assert len(res) == 1
        assert res[0].span_name == 'invoke'

    def test_get_span_latencies_duration_in_milliseconds(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        # Insert a single span with exactly 500ms
        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time, span_name='invoke', duration_ns=500 * 1_000_000
            )
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_span_latencies(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
        )

        assert len(res) == 1
        # With a single value, all percentiles should equal 500ms
        assert res[0].p50 == pytest.approx(500.0, abs=1.0)
        assert res[0].p99 == pytest.approx(500.0, abs=1.0)

    def test_get_span_latencies_filters_by_route_name(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                span_name='invoke',
                duration_ns=100 * 1_000_000,
                span_attributes={
                    'traceloop.association.properties.route_name': 'route-a'
                },
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(minutes=1),
                span_name='invoke',
                duration_ns=200 * 1_000_000,
                span_attributes={
                    'traceloop.association.properties.route_name': 'route-b'
                },
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_span_latencies(
            project_uuid=TEST_PROJECT_UUID,
            route_names=['route-a'],
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
        )

        assert len(res) == 1
        assert res[0].span_name == 'invoke'
        assert res[0].p50 == pytest.approx(100.0, abs=1.0)

    # --- get_category_latencies ---

    def test_get_category_latencies_groups_by_category(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(minutes=i),
                span_name='invoke',
                duration_ns=100_000_000,
                span_attributes={
                    'traceloop.association.properties.rb.gateway.operation_category': 'invocation'
                },
            )
            for i in range(3)
        ] + [
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(minutes=i + 3),
                span_name='get_cached_response',
                duration_ns=50_000_000,
                span_attributes={
                    'traceloop.association.properties.rb.gateway.operation_category': 'cache'
                },
            )
            for i in range(2)
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_category_latencies(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
        )

        categories = {r.category for r in res}
        assert 'invocation' in categories
        assert 'cache' in categories

    def test_get_category_latencies_excludes_empty_category(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                span_name='invoke',
                duration_ns=100_000_000,
                span_attributes={
                    'traceloop.association.properties.rb.gateway.operation_category': 'invocation'
                },
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(minutes=1),
                span_name='unknown_span',
                duration_ns=200_000_000,
                span_attributes={},
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_category_latencies(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            include_others=False,
        )

        categories = {r.category for r in res}
        assert 'invocation' in categories
        assert '' not in categories

    def test_get_category_latencies_includes_others(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                span_name='invoke',
                duration_ns=100_000_000,
                span_attributes={
                    'traceloop.association.properties.rb.gateway.operation_category': 'invocation'
                },
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(minutes=1),
                span_name='unknown_span',
                duration_ns=200_000_000,
                span_attributes={},
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_category_latencies(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            include_others=True,
        )

        categories = {r.category for r in res}
        assert 'invocation' in categories
        assert 'other' in categories

    # --- get_category_span_latencies ---

    def test_get_category_span_latencies_groups_by_category_and_name(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = (
            [
                db_mock.get_sample_otel_span(
                    timestamp=base_time + datetime.timedelta(minutes=i),
                    span_name='invoke_openai',
                    duration_ns=100_000_000,
                    span_attributes={
                        'traceloop.association.properties.rb.gateway.operation_category': 'invocation'
                    },
                )
                for i in range(2)
            ]
            + [
                db_mock.get_sample_otel_span(
                    timestamp=base_time + datetime.timedelta(minutes=i + 2),
                    span_name='invoke_anthropic',
                    duration_ns=150_000_000,
                    span_attributes={
                        'traceloop.association.properties.rb.gateway.operation_category': 'invocation'
                    },
                )
                for i in range(2)
            ]
            + [
                db_mock.get_sample_otel_span(
                    timestamp=base_time + datetime.timedelta(minutes=5),
                    span_name='get_cached_response',
                    duration_ns=50_000_000,
                    span_attributes={
                        'traceloop.association.properties.rb.gateway.operation_category': 'cache'
                    },
                )
            ]
        )
        self.insert(test_spans)

        res = self.otel_traces_dao.get_category_span_latencies(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
        )

        invocation_spans = [r for r in res if r.category == 'invocation']
        cache_spans = [r for r in res if r.category == 'cache']
        assert len(invocation_spans) == 2
        assert len(cache_spans) == 1
        invocation_names = {r.span_name for r in invocation_spans}
        assert invocation_names == {'invoke_openai', 'invoke_anthropic'}
        assert cache_spans[0].span_name == 'get_cached_response'

    def test_get_category_span_latencies_empty(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        res = self.otel_traces_dao.get_category_span_latencies(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
        )

        assert res == []

    # --- get_spans_by_trace_id ---

    def test_get_spans_by_trace_id_empty(self):
        """Test that empty list is returned for non-existent trace."""
        spans = self.otel_traces_dao.get_spans_by_trace_id(
            TEST_PROJECT_UUID, 'nonexistent-trace'
        )
        assert spans == []

    def test_get_spans_by_trace_id_single_span(self):
        """Test retrieving a single span by trace_id."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='trace-123',
                span_id='span-1',
                span_name='invoke',
                duration_ns=100_000_000,
                span_attributes={
                    'traceloop.association.properties.route_name': 'test-route',
                    'traceloop.association.properties.api_key_uuid': '660e8400-e29b-41d4-a716-446655440003',
                    'traceloop.association.properties.api_key_name': 'test-key',
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440003',
                    'traceloop.association.properties.group_name': 'test-group',
                },
            )
        ]
        self.insert(test_spans)

        spans = self.otel_traces_dao.get_spans_by_trace_id(
            TEST_PROJECT_UUID, 'trace-123'
        )

        assert len(spans) == 1
        span = spans[0]
        assert span.trace_id == 'trace-123'
        assert span.span_id == 'span-1'
        assert span.span_name == 'invoke'
        assert span.service_name == 'radicalbit-ai-gateway'
        assert span.duration == 100_000_000
        assert span.status_code == 'Unset'
        # ClickHouse returns empty string for missing map keys
        assert not span.parent_span_id
        assert span.route_name == 'test-route'
        assert span.api_key_uuid == '660e8400-e29b-41d4-a716-446655440003'
        assert span.api_key_name == 'test-key'
        assert span.group_uuid == '550e8400-e29b-41d4-a716-446655440003'
        assert span.group_name == 'test-group'

    def test_get_spans_by_trace_id_multiple_spans_ordered(self):
        """Test retrieving multiple spans ordered by timestamp."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='trace-multi',
                span_id='span-1',
                span_name='root',
                span_attributes={
                    'traceloop.association.properties.route_name': 'test-route',
                    'traceloop.association.properties.api_key_uuid': '660e8400-e29b-41d4-a716-446655440001',
                    'traceloop.association.properties.api_key_name': 'test-key',
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440001',
                    'traceloop.association.properties.group_name': 'test-group',
                },
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(milliseconds=10),
                trace_id='trace-multi',
                span_id='span-2',
                span_name='child',
                parent_span_id='span-1',
                span_attributes={
                    'traceloop.association.properties.route_name': 'test-route',
                    'traceloop.association.properties.api_key_uuid': '660e8400-e29b-41d4-a716-446655440001',
                    'traceloop.association.properties.api_key_name': 'test-key',
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440001',
                    'traceloop.association.properties.group_name': 'test-group',
                },
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(milliseconds=20),
                trace_id='trace-multi',
                span_id='span-3',
                span_name='grandchild',
                parent_span_id='span-2',
                span_attributes={
                    'traceloop.association.properties.route_name': 'test-route',
                    'traceloop.association.properties.api_key_uuid': '660e8400-e29b-41d4-a716-446655440001',
                    'traceloop.association.properties.api_key_name': 'test-key',
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440001',
                    'traceloop.association.properties.group_name': 'test-group',
                },
            ),
        ]
        self.insert(test_spans)

        spans = self.otel_traces_dao.get_spans_by_trace_id(
            TEST_PROJECT_UUID, 'trace-multi'
        )

        assert len(spans) == 3
        # Verify ordering by timestamp (ascending)
        timestamps = [s.timestamp for s in spans]
        assert timestamps == sorted(timestamps)
        # Verify parent-child relationships extracted from attributes
        # Find root span (no parent)
        root_spans = [s for s in spans if not s.parent_span_id]
        assert len(root_spans) == 1
        assert root_spans[0].span_id == 'span-1'
        # Find child spans
        child_spans = [s for s in spans if s.parent_span_id == 'span-1']
        assert len(child_spans) == 1
        assert child_spans[0].span_id == 'span-2'

    def test_get_spans_by_trace_id_with_error_status(self):
        """Test that error status codes are correctly retrieved."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='trace-error',
                span_id='span-error',
                status_code='ERROR',
                span_attributes={
                    'traceloop.association.properties.route_name': 'test-route',
                    'traceloop.association.properties.api_key_uuid': '660e8400-e29b-41d4-a716-446655440001',
                    'traceloop.association.properties.api_key_name': 'test-key',
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440001',
                    'traceloop.association.properties.group_name': 'test-group',
                },
            )
        ]
        self.insert(test_spans)

        spans = self.otel_traces_dao.get_spans_by_trace_id(
            TEST_PROJECT_UUID, 'trace-error'
        )

        assert len(spans) == 1
        assert spans[0].status_code == 'ERROR'

    def test_get_spans_by_trace_id_only_returns_requested_trace(self):
        """Test that only spans with matching trace_id are returned."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='trace-target',
                span_id='span-target',
                span_attributes={
                    'traceloop.association.properties.route_name': 'test-route',
                    'traceloop.association.properties.api_key_uuid': '660e8400-e29b-41d4-a716-446655440001',
                    'traceloop.association.properties.api_key_name': 'test-key',
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440001',
                    'traceloop.association.properties.group_name': 'test-group',
                },
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(milliseconds=10),
                trace_id='trace-other',
                span_id='span-other',
                span_attributes={
                    'traceloop.association.properties.route_name': 'other-route',
                    'traceloop.association.properties.api_key_uuid': '660e8400-e29b-41d4-a716-446655440005',
                    'traceloop.association.properties.api_key_name': 'other-key',
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440005',
                    'traceloop.association.properties.group_name': 'other-group',
                },
            ),
        ]
        self.insert(test_spans)

        spans = self.otel_traces_dao.get_spans_by_trace_id(
            TEST_PROJECT_UUID, 'trace-target'
        )

        assert len(spans) == 1
        assert spans[0].trace_id == 'trace-target'

    # --- get_spans_stats_by_request_uuids ---

    def _insert_span(
        self,
        timestamp: datetime.datetime,
        span_name: str = 'invoke',
        duration_ns: int = 100 * 1_000_000,
        status_code: str = 'STATUS_CODE_OK',
        span_attributes: dict | None = None,
    ):
        span = db_mock.get_sample_otel_span(
            timestamp=timestamp,
            span_name=span_name,
            duration_ns=duration_ns,
            status_code=status_code,
            span_attributes=span_attributes,
        )
        self.insert([span])

    def _insert_span_for_request(
        self,
        timestamp: datetime.datetime,
        request_uuid: str,
        span_name: str = 'invoke',
        status_code: str = 'STATUS_CODE_OK',
        input_tokens: int = 0,
        output_tokens: int = 0,
    ):
        attrs = {'traceloop.association.properties.request_uuid': request_uuid}
        if input_tokens:
            attrs['gen_ai.usage.input_tokens'] = str(input_tokens)
        if output_tokens:
            attrs['gen_ai.usage.output_tokens'] = str(output_tokens)
        self._insert_span(
            timestamp=timestamp,
            span_name=span_name,
            duration_ns=100 * 1_000_000,
            status_code=status_code,
            span_attributes=attrs,
        )

    def test_get_spans_stats_empty_input(self):
        res = self.otel_traces_dao.get_spans_stats_by_request_uuids([])
        assert res == {}

    def test_get_spans_stats_unknown_uuid(self):
        res = self.otel_traces_dao.get_spans_stats_by_request_uuids(['unknown-uuid'])
        assert res == {}

    def test_get_spans_stats_aggregates_span_count(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        req_uuid = 'req-aaa-111'
        self._insert_span_for_request(base_time, req_uuid, span_name='span-1')
        self._insert_span_for_request(
            base_time + datetime.timedelta(seconds=1), req_uuid, span_name='span-2'
        )
        self._insert_span_for_request(
            base_time + datetime.timedelta(seconds=2), req_uuid, span_name='span-3'
        )

        res = self.otel_traces_dao.get_spans_stats_by_request_uuids([req_uuid])

        assert req_uuid in res
        assert res[req_uuid].span_count == 3

    def test_get_spans_stats_counts_errors(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        req_uuid = 'req-bbb-222'
        self._insert_span_for_request(base_time, req_uuid, status_code='STATUS_CODE_OK')
        self._insert_span_for_request(
            base_time + datetime.timedelta(seconds=1), req_uuid, status_code='Error'
        )
        self._insert_span_for_request(
            base_time + datetime.timedelta(seconds=2), req_uuid, status_code='Error'
        )

        res = self.otel_traces_dao.get_spans_stats_by_request_uuids([req_uuid])

        assert res[req_uuid].span_count == 3
        assert res[req_uuid].error_count == 2

    def test_get_spans_stats_sums_tokens(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        req_uuid = 'req-ccc-333'
        self._insert_span_for_request(
            base_time, req_uuid, input_tokens=100, output_tokens=50
        )
        self._insert_span_for_request(
            base_time + datetime.timedelta(seconds=1),
            req_uuid,
            input_tokens=200,
            output_tokens=80,
        )

        res = self.otel_traces_dao.get_spans_stats_by_request_uuids([req_uuid])

        assert res[req_uuid].input_tokens == 300
        assert res[req_uuid].output_tokens == 130

    def test_get_spans_stats_no_tokens_defaults_to_zero(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        req_uuid = 'req-ddd-444'
        self._insert_span_for_request(base_time, req_uuid)

        res = self.otel_traces_dao.get_spans_stats_by_request_uuids([req_uuid])

        assert res[req_uuid].input_tokens == 0
        assert res[req_uuid].output_tokens == 0

    def test_get_spans_stats_isolates_by_request_uuid(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        req_a = 'req-eee-111'
        req_b = 'req-fff-222'
        self._insert_span_for_request(base_time, req_a, input_tokens=100)
        self._insert_span_for_request(
            base_time + datetime.timedelta(seconds=1), req_a, input_tokens=50
        )
        self._insert_span_for_request(
            base_time + datetime.timedelta(seconds=2), req_b, input_tokens=999
        )

        res = self.otel_traces_dao.get_spans_stats_by_request_uuids([req_a, req_b])

        assert res[req_a].input_tokens == 150
        assert res[req_a].span_count == 2
        assert res[req_b].input_tokens == 999
        assert res[req_b].span_count == 1

    def test_get_spans_stats_last_span_timestamp(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        req_uuid = 'req-ggg-555'
        t1 = base_time
        t2 = base_time + datetime.timedelta(seconds=5)
        self._insert_span_for_request(t1, req_uuid)
        self._insert_span_for_request(t2, req_uuid)

        res = self.otel_traces_dao.get_spans_stats_by_request_uuids([req_uuid])

        assert res[req_uuid].last_span is not None
        # last_span should be the max timestamp
        assert res[req_uuid].last_span >= t1

    # --- get_traces_chart_data ---

    def test_get_traces_chart_data_empty(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        res = self.otel_traces_dao.get_traces_chart_data(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            granularity='hours',
            timezone_offset_seconds=0,
        )

        assert res == []

    def test_get_traces_chart_data_returns_points(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        # Insert root spans (empty ParentSpanId)
        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='trace-1',
                span_id='span-1',
                status_code='Unset',
                parent_span_id='',
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(minutes=30),
                trace_id='trace-2',
                span_id='span-2',
                status_code='Error',
                parent_span_id='',
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_traces_chart_data(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            granularity='hours',
            timezone_offset_seconds=0,
        )

        assert len(res) == 2
        by_status = {p.trace_status: p.total_requests for p in res}
        assert by_status.get('success') == 1
        assert by_status.get('error') == 1

    def test_get_traces_chart_data_groups_by_status(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t1',
                status_code='Unset',
                parent_span_id='',
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t2',
                status_code='Unset',
                parent_span_id='',
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t3',
                status_code='Error',
                parent_span_id='',
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_traces_chart_data(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            granularity='hours',
            timezone_offset_seconds=0,
        )

        by_status = {p.trace_status: p.total_requests for p in res}
        assert by_status.get('success') == 2
        assert by_status.get('error') == 1

    def test_get_traces_chart_data_filters_by_route(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t1',
                status_code='Unset',
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.route_name': 'route-a'
                },
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t2',
                status_code='Unset',
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.route_name': 'route-b'
                },
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_traces_chart_data(
            project_uuid=TEST_PROJECT_UUID,
            route_names=['route-a'],
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            granularity='hours',
            timezone_offset_seconds=0,
        )

        assert len(res) == 1
        assert res[0].total_requests == 1

    def test_get_traces_chart_data_filters_by_time(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t1',
                status_code='Unset',
                parent_span_id='',
            ),
            # Outside time range
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(hours=3),
                trace_id='t2',
                status_code='Unset',
                parent_span_id='',
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_traces_chart_data(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            granularity='hours',
            timezone_offset_seconds=0,
        )

        assert len(res) == 1
        assert res[0].total_requests == 1

    def test_get_traces_chart_data_only_root_spans(self):
        """Test that child spans are not counted."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t1',
                span_id='span-root',
                status_code='Unset',
                parent_span_id='',  # Root span
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t1',
                span_id='span-child',
                status_code='Unset',
                parent_span_id='span-root',  # Child span - should be ignored
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_traces_chart_data(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            granularity='hours',
            timezone_offset_seconds=0,
        )

        # Only 1 root span should be counted
        assert len(res) == 1
        assert res[0].total_requests == 1

    def test_get_traces_chart_data_excludes_rootless_traces(self):
        """A trace with no root span must not bucket to the Unix epoch.

        Regression: anyIf over a trace with no empty-ParentSpanId span returns
        the epoch default (toDateTime(0)), which weekly-bucketed to 1969 and
        blew the chart range up to thousands of buckets.
        """
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            # Normal trace with a root span
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t1',
                span_id='span-root',
                status_code='Unset',
                parent_span_id='',
            ),
            # Orphan trace: only a child span, no root span
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t2',
                span_id='span-orphan-child',
                status_code='Unset',
                parent_span_id='span-missing-root',
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_traces_chart_data(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            granularity='weeks',
            timezone_offset_seconds=0,
        )

        # Only the trace with a root span is counted; the orphan is dropped.
        assert len(res) == 1
        assert res[0].total_requests == 1
        # No bucket should land at/near the Unix epoch.
        assert all(p.timestamp > 0 for p in res)

    # --- get_latencies ---

    def test_get_latencies_empty(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        res = self.otel_traces_dao.get_latencies(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
        )

        # ClickHouse returns nan for empty quantile results
        assert math.isnan(res.p50) or res.p50 is None
        assert math.isnan(res.p90) or res.p90 is None
        assert math.isnan(res.p95) or res.p95 is None
        assert math.isnan(res.p99) or res.p99 is None

    def test_get_latencies_returns_percentiles(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        # Insert root spans with different durations (in nanoseconds)
        durations_ms = [100, 200, 300, 400]
        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(minutes=i),
                trace_id=f'trace-{i}',
                span_id=f'span-{i}',
                duration_ns=ms * 1_000_000,
                parent_span_id='',  # Root span
            )
            for i, ms in enumerate(durations_ms)
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_latencies(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
        )

        assert res.p50 is not None
        assert res.p90 is not None
        assert res.p95 is not None
        assert res.p99 is not None
        # p50 should be between 100 and 400
        assert 100 <= res.p50 <= 400

    def test_get_latencies_in_milliseconds(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        # Insert a single span with exactly 500ms (500,000,000 ns)
        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='trace-1',
                span_id='span-1',
                duration_ns=500 * 1_000_000,
                parent_span_id='',
            )
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_latencies(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
        )

        # With a single value, all percentiles should equal 500ms
        assert res.p50 == pytest.approx(500.0, abs=1.0)
        assert res.p99 == pytest.approx(500.0, abs=1.0)

    def test_get_latencies_filters_by_route(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t1',
                duration_ns=100 * 1_000_000,
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.route_name': 'route-a'
                },
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t2',
                duration_ns=999 * 1_000_000,
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.route_name': 'route-b'
                },
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_latencies(
            project_uuid=TEST_PROJECT_UUID,
            route_names=['route-a'],
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
        )

        # Should only include route-a's 100ms
        assert res.p50 == pytest.approx(100.0, abs=1.0)

    def test_get_latencies_only_root_spans(self):
        """Test that child spans are not included in latency calculation."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t1',
                span_id='span-root',
                duration_ns=100 * 1_000_000,
                parent_span_id='',  # Root span
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t1',
                span_id='span-child',
                duration_ns=999 * 1_000_000,  # Much longer - should be ignored
                parent_span_id='span-root',  # Child span
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_latencies(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
        )

        # Should only consider root span's 100ms
        assert res.p50 == pytest.approx(100.0, abs=1.0)

    # --- get_root_traces_paginated ---

    def test_get_root_traces_empty(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        res = self.otel_traces_dao.get_root_traces_paginated(
            project_uuid=TEST_PROJECT_UUID,
            route_names=['nonexistent-route'],
            group_uuids=None,
            key_uuids=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            params=Params(page=1, size=10),
        )

        assert res.items == []
        assert res.total == 0

    def test_get_root_traces_root_spans_only(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='trace-1',
                span_id='span-root',
                duration_ns=100 * 1_000_000,
                parent_span_id='',  # Root span
                span_attributes={
                    'traceloop.association.properties.route_name': 'test-route',
                    'traceloop.association.properties.api_key_uuid': '660e8400-e29b-41d4-a716-446655440001',
                    'traceloop.association.properties.api_key_name': 'test-key',
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440001',
                    'traceloop.association.properties.group_name': 'test-group',
                },
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='trace-1',
                span_id='span-child',
                duration_ns=50 * 1_000_000,
                parent_span_id='span-root',  # Child - should be ignored
                span_attributes={
                    'traceloop.association.properties.route_name': 'test-route',
                },
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_root_traces_paginated(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            group_uuids=None,
            key_uuids=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            params=Params(page=1, size=10),
        )

        assert len(res.items) == 1
        assert res.items[0].trace_id == 'trace-1'
        assert res.items[0].duration_ms == pytest.approx(100.0, abs=0.01)

    def test_get_root_traces_ordered_by_timestamp_desc(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='trace-1',
                span_id='span-1',
                duration_ns=100 * 1_000_000,
                parent_span_id='',
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(minutes=10),
                trace_id='trace-2',
                span_id='span-2',
                duration_ns=200 * 1_000_000,
                parent_span_id='',
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_root_traces_paginated(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            group_uuids=None,
            key_uuids=None,
            _from=None,
            _to=None,
            params=Params(page=1, size=10),
        )

        assert len(res.items) == 2
        # Most recent first
        assert res.items[0].trace_id == 'trace-2'
        assert res.items[1].trace_id == 'trace-1'

    def test_get_root_traces_filters_by_route(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t1',
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.route_name': 'route-a'
                },
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t2',
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.route_name': 'route-b'
                },
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_root_traces_paginated(
            project_uuid=TEST_PROJECT_UUID,
            route_names=['route-a'],
            group_uuids=None,
            key_uuids=None,
            _from=None,
            _to=None,
            params=Params(page=1, size=10),
        )

        assert len(res.items) == 1
        assert res.items[0].trace_id == 't1'

    def test_get_root_traces_filters_by_time(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time, trace_id='t1', parent_span_id=''
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(hours=5),
                trace_id='t2',
                parent_span_id='',
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_root_traces_paginated(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            group_uuids=None,
            key_uuids=None,
            _from=base_time,
            _to=base_time + datetime.timedelta(hours=1),
            params=Params(page=1, size=10),
        )

        assert len(res.items) == 1
        assert res.items[0].trace_id == 't1'

    def test_get_root_traces_pagination(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(minutes=i),
                trace_id=f'trace-{i}',
                span_id=f'span-{i}',
                parent_span_id='',
            )
            for i in range(5)
        ]
        self.insert(test_spans)

        page1 = self.otel_traces_dao.get_root_traces_paginated(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            group_uuids=None,
            key_uuids=None,
            _from=None,
            _to=None,
            params=Params(page=1, size=2),
        )
        page2 = self.otel_traces_dao.get_root_traces_paginated(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            group_uuids=None,
            key_uuids=None,
            _from=None,
            _to=None,
            params=Params(page=2, size=2),
        )

        assert len(page1.items) == 2
        assert len(page2.items) == 2
        assert page1.total == 5
        # No overlap
        ids_p1 = {r.trace_id for r in page1.items}
        ids_p2 = {r.trace_id for r in page2.items}
        assert ids_p1.isdisjoint(ids_p2)

    def test_get_root_traces_extracts_metadata(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='trace-1',
                span_id='span-1',
                duration_ns=1500 * 1_000_000,  # 1500ms
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.route_name': 'my-route',
                    'traceloop.association.properties.api_key_uuid': '660e8400-e29b-41d4-a716-446655440002',
                    'traceloop.association.properties.api_key_name': 'my-api-key',
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440002',
                    'traceloop.association.properties.group_name': 'my-group',
                },
            )
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_root_traces_paginated(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            group_uuids=None,
            key_uuids=None,
            _from=None,
            _to=None,
            params=Params(page=1, size=10),
        )

        assert len(res.items) == 1
        row = res.items[0]
        assert row.trace_id == 'trace-1'
        assert row.route_name == 'my-route'
        assert row.api_key_uuid == '660e8400-e29b-41d4-a716-446655440002'
        assert row.api_key_name == 'my-api-key'
        assert row.group_uuid == '550e8400-e29b-41d4-a716-446655440002'
        assert row.group_name == 'my-group'
        assert row.duration_ms == pytest.approx(1500.0, abs=0.01)

    def test_get_root_traces_filters_by_group_uuid(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t1',
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440001'
                },
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t2',
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440002'
                },
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_root_traces_paginated(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            group_uuids=[UUID('550e8400-e29b-41d4-a716-446655440001')],
            key_uuids=None,
            _from=None,
            _to=None,
            params=Params(page=1, size=10),
        )

        assert len(res.items) == 1
        assert res.items[0].trace_id == 't1'

    def test_get_root_traces_filters_by_key_uuid(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t1',
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.api_key_uuid': '660e8400-e29b-41d4-a716-446655440001'
                },
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t2',
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.api_key_uuid': '660e8400-e29b-41d4-a716-446655440002'
                },
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_root_traces_paginated(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            group_uuids=None,
            key_uuids=[UUID('660e8400-e29b-41d4-a716-446655440001')],
            _from=None,
            _to=None,
            params=Params(page=1, size=10),
        )

        assert len(res.items) == 1
        assert res.items[0].trace_id == 't1'

    def test_get_root_traces_filters_by_multiple_groups(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t1',
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440001'
                },
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t2',
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440002'
                },
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t3',
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440003'
                },
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_root_traces_paginated(
            project_uuid=TEST_PROJECT_UUID,
            route_names=None,
            group_uuids=[
                UUID('550e8400-e29b-41d4-a716-446655440001'),
                UUID('550e8400-e29b-41d4-a716-446655440002'),
            ],
            key_uuids=None,
            _from=None,
            _to=None,
            params=Params(page=1, size=10),
        )

        assert len(res.items) == 2
        trace_ids = {r.trace_id for r in res.items}
        assert trace_ids == {'t1', 't2'}

    def test_get_root_traces_combined_filters(self):
        """Test that route, group, and key filters are combined with AND logic."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            # t1: route-a + group-a + key-a (matches all filters)
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t1',
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.route_name': 'route-a',
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440001',
                    'traceloop.association.properties.api_key_uuid': '660e8400-e29b-41d4-a716-446655440001',
                },
            ),
            # t2: route-a + group-a + key-b (fails key filter)
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t2',
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.route_name': 'route-a',
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440001',
                    'traceloop.association.properties.api_key_uuid': '660e8400-e29b-41d4-a716-446655440002',
                },
            ),
            # t3: route-a + group-b + key-a (fails group filter)
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t3',
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.route_name': 'route-a',
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440002',
                    'traceloop.association.properties.api_key_uuid': '660e8400-e29b-41d4-a716-446655440001',
                },
            ),
            # t4: route-b + group-a + key-a (fails route filter)
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t4',
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.route_name': 'route-b',
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440001',
                    'traceloop.association.properties.api_key_uuid': '660e8400-e29b-41d4-a716-446655440001',
                },
            ),
            # t5: route-a + group-b + key-b (fails group and key filters)
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='t5',
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.route_name': 'route-a',
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440002',
                    'traceloop.association.properties.api_key_uuid': '660e8400-e29b-41d4-a716-446655440002',
                },
            ),
        ]
        self.insert(test_spans)

        # Filter: route IN (route-a, route-b) AND group IN (group-a) AND key IN (key-a)
        res = self.otel_traces_dao.get_root_traces_paginated(
            project_uuid=TEST_PROJECT_UUID,
            route_names=['route-a', 'route-b'],
            group_uuids=[UUID('550e8400-e29b-41d4-a716-446655440001')],
            key_uuids=[UUID('660e8400-e29b-41d4-a716-446655440001')],
            _from=None,
            _to=None,
            params=Params(page=1, size=10),
        )

        # Only t1 and t4 match: (route-a OR route-b) AND group-a AND key-a
        # t1: route-a + group-a + key-a ✓
        # t4: route-b + group-a + key-a ✓
        assert len(res.items) == 2
        trace_ids = {r.trace_id for r in res.items}
        assert trace_ids == {'t1', 't4'}

    # --- get_spans_stats_by_trace_ids ---

    def test_get_spans_stats_by_trace_ids_empty_input(self):
        res = self.otel_traces_dao.get_spans_stats_by_trace_ids([])
        assert res == {}

    def test_get_spans_stats_by_trace_ids_unknown(self):
        res = self.otel_traces_dao.get_spans_stats_by_trace_ids(['unknown-trace-id'])
        assert res == {}

    def test_get_spans_stats_by_trace_ids_aggregates(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        trace_id = 'trace-123'

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id=trace_id,
                span_id='span-1',
                status_code='Unset',
                span_attributes={
                    'gen_ai.usage.input_tokens': '100',
                    'gen_ai.usage.output_tokens': '50',
                },
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time + datetime.timedelta(seconds=1),
                trace_id=trace_id,
                span_id='span-2',
                status_code='Error',
                span_attributes={
                    'gen_ai.usage.input_tokens': '200',
                    'gen_ai.usage.output_tokens': '80',
                },
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_spans_stats_by_trace_ids([trace_id])

        assert trace_id in res
        assert res[trace_id].span_count == 2
        assert res[trace_id].error_count == 1
        assert res[trace_id].input_tokens == 300
        assert res[trace_id].output_tokens == 130

    def test_get_spans_stats_by_trace_ids_isolates_by_trace_id(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='trace-a',
                span_id='span-a1',
                span_attributes={'gen_ai.usage.input_tokens': '100'},
            ),
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='trace-b',
                span_id='span-b1',
                span_attributes={'gen_ai.usage.input_tokens': '999'},
            ),
        ]
        self.insert(test_spans)

        res = self.otel_traces_dao.get_spans_stats_by_trace_ids(['trace-a', 'trace-b'])

        assert res['trace-a'].input_tokens == 100
        assert res['trace-a'].span_count == 1
        assert res['trace-b'].input_tokens == 999
        assert res['trace-b'].span_count == 1

    # --- get_span_by_trace_and_span_id ---

    def test_get_span_by_trace_and_span_id_not_found(self):
        """Test that None is returned when span not found."""
        result = self.otel_traces_dao.get_span_by_trace_and_span_id(
            TEST_PROJECT_UUID, 'nonexistent-trace', 'nonexistent-span'
        )
        assert result is None

    def test_get_span_by_trace_and_span_id_success(self):
        """Test successful span retrieval with all fields."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='trace-123',
                span_id='span-456',
                span_name='invoke',
                duration_ns=100_000_000,
                status_code='Unset',
                parent_span_id='',
                span_attributes={
                    'traceloop.association.properties.route_name': 'test-route',
                    'traceloop.association.properties.api_key_uuid': '660e8400-e29b-41d4-a716-446655440003',
                    'traceloop.association.properties.api_key_name': 'test-key',
                    'traceloop.association.properties.group_uuid': '550e8400-e29b-41d4-a716-446655440003',
                    'traceloop.association.properties.group_name': 'test-group',
                    'gen_ai.usage.input_tokens': '100',
                    'gen_ai.usage.output_tokens': '50',
                    'llm.usage.total_tokens': '150',
                    'traceloop.association.properties.request_uuid': '12345678-1234-5678-1234-567812345678',
                },
            )
        ]
        self.insert(test_spans)

        result = self.otel_traces_dao.get_span_by_trace_and_span_id(
            TEST_PROJECT_UUID, 'trace-123', 'span-456'
        )

        assert result is not None
        assert result.trace_id == 'trace-123'
        assert result.span_id == 'span-456'
        assert result.span_name == 'invoke'
        assert result.duration == 100_000_000
        assert result.status_code == 'Unset'
        assert result.route_name == 'test-route'
        assert result.api_key_uuid == '660e8400-e29b-41d4-a716-446655440003'
        assert result.api_key_name == 'test-key'
        assert result.group_uuid == '550e8400-e29b-41d4-a716-446655440003'
        assert result.group_name == 'test-group'
        assert result.output_tokens == '50'
        assert result.input_tokens == '100'
        assert result.total_tokens == '150'
        # Verify new fields
        assert result.span_attributes is not None
        assert result.status_message == ''
        assert result.events == []

    def test_get_span_by_trace_and_span_id_with_events(self):
        """Test that events are correctly retrieved as dictionaries."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        event_time_1 = base_time
        event_time_2 = base_time + datetime.timedelta(milliseconds=5)

        trace = db_mock.get_sample_otel_span(
            timestamp=base_time,
            trace_id='trace-with-events',
            span_id='span-events',
            span_name='invoke',
            span_attributes={
                'traceloop.association.properties.route_name': 'test-route',
                'gen_ai.usage.input_tokens': '100',
                'gen_ai.usage.output_tokens': '50',
            },
            duration_ns=100_000_000,
            status_code='Error',
            events_timestamp=[event_time_1, event_time_2],
            events_name=['event-1', 'exception'],
            events_attributes=[
                {'key': 'value'},
                {'error.type': 'test_error'},
            ],
        )
        self.insert([trace])

        result = self.otel_traces_dao.get_span_by_trace_and_span_id(
            TEST_PROJECT_UUID, 'trace-with-events', 'span-events'
        )

        assert result is not None
        assert result.events is not None
        assert len(result.events) == 2

        # Verify events are dictionaries with correct keys
        event1 = result.events[0]
        assert isinstance(event1, dict)
        assert 'timestamp' in event1
        assert 'name' in event1
        assert 'attributes' in event1
        assert event1['name'] == 'event-1'
        assert event1['attributes'] == {'key': 'value'}

        event2 = result.events[1]
        assert isinstance(event2, dict)
        assert event2['name'] == 'exception'
        assert event2['attributes'] == {'error.type': 'test_error'}

    def test_get_span_by_trace_and_span_id_with_status_message(self):
        """Test that status_message is correctly retrieved."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='trace-status-msg',
                span_id='span-status-msg',
                span_name='invoke',
                duration_ns=100_000_000,
                status_code='Error',
                parent_span_id='',
                span_attributes={},
                status_message='Something went wrong',
            )
        ]
        self.insert(test_spans)

        result = self.otel_traces_dao.get_span_by_trace_and_span_id(
            TEST_PROJECT_UUID, 'trace-status-msg', 'span-status-msg'
        )

        assert result is not None
        assert result.status_message == 'Something went wrong'

    def test_get_span_by_trace_and_span_id_wrong_trace(self):
        """Test that None is returned when span exists but in different trace."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='trace-correct',
                span_id='span-456',
                span_name='invoke',
                parent_span_id='',
            )
        ]
        self.insert(test_spans)

        result = self.otel_traces_dao.get_span_by_trace_and_span_id(
            TEST_PROJECT_UUID, 'wrong-trace', 'span-456'
        )

        assert result is None

    def test_get_span_by_trace_and_span_id_with_span_attributes(self):
        """Test that span_attributes are correctly retrieved as dict."""
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_spans = [
            db_mock.get_sample_otel_span(
                timestamp=base_time,
                trace_id='trace-attrs',
                span_id='span-attrs',
                span_name='invoke',
                parent_span_id='',
                span_attributes={
                    'custom.attr.1': 'value1',
                    'custom.attr.2': 'value2',
                    'traceloop.association.properties.route_name': 'test-route',
                },
            )
        ]
        self.insert(test_spans)

        result = self.otel_traces_dao.get_span_by_trace_and_span_id(
            TEST_PROJECT_UUID, 'trace-attrs', 'span-attrs'
        )

        assert result is not None
        assert result.span_attributes is not None
        assert result.span_attributes.get('custom.attr.1') == 'value1'
        assert result.span_attributes.get('custom.attr.2') == 'value2'
