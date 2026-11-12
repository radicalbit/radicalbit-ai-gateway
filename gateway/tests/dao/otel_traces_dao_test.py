import datetime
import math
from uuid import UUID

from fastapi_pagination import Params
import pytest

from tests.common import db_mock
from tests.common.db_integration_ch import DatabaseIntegrationClickhouse
from tests.common.db_mock import TEST_PROJECT_UUID

from radicalbit_ai_gateway.db.dao.otel_traces_dao import OtelTracesDAO
from radicalbit_ai_gateway.db.models.trace import SpanRecord, SpanStats
from radicalbit_ai_gateway.models.request_event_type import RequestType

T0 = datetime.datetime(2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc)
SEC = datetime.timedelta(seconds=1)
MIN = datetime.timedelta(minutes=1)
H = datetime.timedelta(hours=1)
D = datetime.timedelta(days=1)
WINDOW = {'_from': T0, '_to': T0 + H}
EMPTY_WINDOW = {'_from': T0 - D, '_to': T0 - D + H}
PROP = 'traceloop.association.properties.'
CATEGORY = f'{PROP}rb.gateway.operation_category'
TAGS = f'{PROP}tags'
IN_TOKENS = 'gen_ai.usage.input_tokens'
OUT_TOKENS = 'gen_ai.usage.output_tokens'
GROUP_1 = '550e8400-e29b-41d4-a716-446655440001'
GROUP_2 = '550e8400-e29b-41d4-a716-446655440002'
GROUP_3 = '550e8400-e29b-41d4-a716-446655440003'
KEY_1 = '660e8400-e29b-41d4-a716-446655440001'
KEY_2 = '660e8400-e29b-41d4-a716-446655440002'
KEY_3 = '660e8400-e29b-41d4-a716-446655440003'


def _ms(ms):
    return ms * 1_000_000


def _meta(route='', key='', key_name='', group='', group_name=''):
    """Trace attributes as the gateway stamps them, empty ones left out."""
    attrs = {
        'route_name': route,
        'api_key_uuid': key,
        'api_key_name': key_name,
        'group_uuid': group,
        'group_name': group_name,
    }
    return {f'{PROP}{k}': v for k, v in attrs.items() if v}


def _span(at, **kwargs):
    return db_mock.get_sample_otel_span(timestamp=at, **kwargs)


def _approx(*values):
    return tuple(pytest.approx(v, abs=1.0) for v in values)


class OtelTracesDAOTest(DatabaseIntegrationClickhouse):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.otel_traces_dao = OtelTracesDAO(cls.db)

    def test_get_span_latencies(self):
        durations = [
            ('invoke', 100),
            ('invoke', 200),
            ('invoke', 300),
            ('invoke', 400),
            ('set_cached_response', 10),
            ('set_cached_response', 20),
            ('single', 500),
        ]
        self.insert(
            [
                *[
                    _span(T0 + i * MIN, span_name=name, duration_ns=_ms(ms))
                    for i, (name, ms) in enumerate(durations)
                ],
                # Outside the window: only seen without a time filter.
                _span(T0 + 10 * D, span_name='invoke', duration_ns=_ms(1000)),
            ]
        )

        def latencies(**window):
            res = self.otel_traces_dao.get_span_latencies(
                project_uuid=TEST_PROJECT_UUID, route_names=None, **window
            )
            return [(r.span_name, (r.p50, r.p90, r.p95, r.p99)) for r in res]

        # Durations come back in milliseconds, one row per span name.
        assert latencies(**WINDOW) == [
            ('invoke', _approx(250, 370, 385, 397)),
            ('set_cached_response', _approx(15, 19, 19.5, 19.9)),
            ('single', _approx(500, 500, 500, 500)),
        ]
        assert latencies(_from=None, _to=None) == [
            ('invoke', _approx(300, 760, 880, 976)),
            ('set_cached_response', _approx(15, 19, 19.5, 19.9)),
            ('single', _approx(500, 500, 500, 500)),
        ]

    def test_category_latencies(self):
        def categorized(at, name, ms, category):
            return _span(
                at,
                span_name=name,
                duration_ns=_ms(ms),
                span_attributes={CATEGORY: category} if category else {},
            )

        self.insert(
            [
                categorized(T0, 'invoke_openai', 100, 'invocation'),
                categorized(T0 + MIN, 'invoke_openai', 100, 'invocation'),
                categorized(T0 + 2 * MIN, 'invoke_anthropic', 150, 'invocation'),
                categorized(T0 + 3 * MIN, 'invoke_anthropic', 150, 'invocation'),
                categorized(T0 + 4 * MIN, 'get_cached_response', 50, 'cache'),
                categorized(T0 + 5 * MIN, 'unknown_span', 200, ''),
            ]
        )
        dao = self.otel_traces_dao
        args = {'project_uuid': TEST_PROJECT_UUID, 'route_names': None, **WINDOW}

        def by_category(include_others):
            res = dao.get_category_latencies(**args, include_others=include_others)
            return [(r.category, r.p50, r.p99) for r in res]

        def by_category_and_span(include_others, **window):
            res = dao.get_category_span_latencies(
                **{**args, **window}, include_others=include_others
            )
            return [(r.category, r.span_name, r.p50) for r in res]

        cache = ('cache', *_approx(50, 50))
        invocation = ('invocation', *_approx(125, 150))
        # Spans without a category are dropped unless include_others.
        assert by_category(False) == [cache, invocation]
        assert by_category(True) == [cache, invocation, ('other', *_approx(200, 200))]
        spans = [
            ('cache', 'get_cached_response', pytest.approx(50, abs=1.0)),
            ('invocation', 'invoke_anthropic', pytest.approx(150, abs=1.0)),
            ('invocation', 'invoke_openai', pytest.approx(100, abs=1.0)),
        ]
        assert by_category_and_span(False) == spans
        assert by_category_and_span(True) == [
            *spans,
            ('other', 'unknown_span', pytest.approx(200, abs=1.0)),
        ]
        assert by_category_and_span(False, **EMPTY_WINDOW) == []

    def test_get_spans_by_trace_id(self):
        meta = _meta('test-route', KEY_1, 'test-key', GROUP_1, 'test-group')
        self.insert(
            [
                _span(
                    T0,
                    trace_id='trace-123',
                    span_id='span-1',
                    duration_ns=_ms(100),
                    span_attributes=meta,
                ),
                # Inserted out of order: spans come back by timestamp.
                _span(
                    T0 + 20 * MIN,
                    trace_id='trace-multi',
                    span_id='span-3',
                    span_name='grandchild',
                    parent_span_id='span-2',
                    span_attributes=meta,
                ),
                _span(
                    T0,
                    trace_id='trace-multi',
                    span_id='span-1',
                    span_name='root',
                    span_attributes=meta,
                ),
                _span(
                    T0 + 10 * MIN,
                    trace_id='trace-multi',
                    span_id='span-2',
                    span_name='child',
                    parent_span_id='span-1',
                    span_attributes=meta,
                ),
                _span(
                    T0,
                    trace_id='trace-error',
                    span_id='span-error',
                    status_code='ERROR',
                    span_attributes={**meta, TAGS: 'env=prod'},
                ),
                _span(
                    T0,
                    trace_id='trace-other',
                    span_id='span-other',
                    span_attributes=_meta('other-route', KEY_2, 'other-key'),
                ),
            ]
        )

        def record(trace_id, span_id, at=T0, **fields):
            return SpanRecord(
                **{
                    'timestamp': at,
                    'trace_id': trace_id,
                    'request_uuid': '',
                    'span_id': span_id,
                    'span_name': 'invoke',
                    'service_name': 'radicalbit-ai-gateway',
                    'duration': _ms(100),
                    'status_code': 'Unset',
                    'parent_span_id': '',
                    'route_name': 'test-route',
                    'api_key_uuid': KEY_1,
                    'api_key_name': 'test-key',
                    'group_uuid': GROUP_1,
                    'group_name': 'test-group',
                    'output_tokens': '',
                    'input_tokens': '',
                    **fields,
                }
            )

        def spans(trace_id):
            return self.otel_traces_dao.get_spans_by_trace_id(
                TEST_PROJECT_UUID, trace_id
            )

        assert {
            trace_id: spans(trace_id)
            for trace_id in ('trace-123', 'trace-multi', 'trace-error', 'missing')
        } == {
            'trace-123': [record('trace-123', 'span-1')],
            'trace-multi': [
                record('trace-multi', 'span-1', span_name='root'),
                record(
                    'trace-multi',
                    'span-2',
                    T0 + 10 * MIN,
                    span_name='child',
                    parent_span_id='span-1',
                ),
                record(
                    'trace-multi',
                    'span-3',
                    T0 + 20 * MIN,
                    span_name='grandchild',
                    parent_span_id='span-2',
                ),
            ],
            'trace-error': [
                record(
                    'trace-error', 'span-error', status_code='ERROR', tags=['env=prod']
                )
            ],
            'missing': [],
        }

    def test_get_span_by_trace_and_span_id(self):
        request_uuid = '12345678-1234-5678-1234-567812345678'
        full_attrs = {
            **_meta('test-route', KEY_3, 'test-key', GROUP_3, 'test-group'),
            IN_TOKENS: '100',
            OUT_TOKENS: '50',
            f'{PROP}request_uuid': request_uuid,
        }
        self.insert(
            [
                _span(
                    T0,
                    trace_id='trace-123',
                    span_id='span-456',
                    span_attributes=full_attrs,
                ),
                _span(
                    T0,
                    trace_id='trace-with-events',
                    span_id='span-events',
                    status_code='Error',
                    status_message='Something went wrong',
                    span_attributes={'custom.attr.1': 'value1'},
                    events_timestamp=[T0, T0 + datetime.timedelta(milliseconds=5)],
                    events_name=['event-1', 'exception'],
                    events_attributes=[{'key': 'value'}, {'error.type': 'test_error'}],
                ),
            ]
        )
        get = self.otel_traces_dao.get_span_by_trace_and_span_id
        project_attr = {f'{PROP}project_uuid': str(TEST_PROJECT_UUID)}
        assert get(TEST_PROJECT_UUID, 'trace-123', 'span-456') == SpanRecord(
            timestamp=T0,
            trace_id='trace-123',
            request_uuid=request_uuid,
            span_id='span-456',
            span_name='invoke',
            service_name='radicalbit-ai-gateway',
            duration=_ms(100),
            status_code='Unset',
            parent_span_id='',
            route_name='test-route',
            api_key_uuid=KEY_3,
            api_key_name='test-key',
            group_uuid=GROUP_3,
            group_name='test-group',
            output_tokens='50',
            input_tokens='100',
            span_attributes={**project_attr, **full_attrs},
            status_message='',
            events=[],
        )
        with_events = get(TEST_PROJECT_UUID, 'trace-with-events', 'span-events')
        assert (
            with_events.status_code,
            with_events.status_message,
            with_events.span_attributes,
            [(e['name'], e['attributes']) for e in with_events.events],
        ) == (
            'Error',
            'Something went wrong',
            {**project_attr, 'custom.attr.1': 'value1'},
            [
                ('event-1', {'key': 'value'}),
                ('exception', {'error.type': 'test_error'}),
            ],
        )
        assert [sorted(e) for e in with_events.events] == [
            ['attributes', 'name', 'timestamp']
        ] * 2
        assert get(TEST_PROJECT_UUID, 'nonexistent-trace', 'nonexistent-span') is None
        # The span exists, but in another trace.
        assert get(TEST_PROJECT_UUID, 'wrong-trace', 'span-456') is None

    def test_spans_stats_by_request_uuid_and_trace_id(self):
        def span(request, at, status='STATUS_CODE_OK', tokens=(0, 0)):
            attrs = {f'{PROP}request_uuid': request}
            if tokens[0]:
                attrs[IN_TOKENS] = str(tokens[0])
            if tokens[1]:
                attrs[OUT_TOKENS] = str(tokens[1])
            return _span(
                at,
                trace_id=f'trace-{request}',
                status_code=status,
                span_attributes=attrs,
            )

        self.insert(
            [
                span('req-a', T0, tokens=(100, 50)),
                span('req-a', T0 + 5 * SEC, 'Error', tokens=(200, 80)),
                span('req-a', T0 + SEC, 'Error'),
                # No token attributes: sums default to zero.
                span('req-b', T0),
                span('req-c', T0 + 2 * SEC, tokens=(999, 0)),
            ]
        )
        expected = {
            'req-a': SpanStats(
                span_count=3,
                error_count=2,
                input_tokens=300,
                output_tokens=130,
                last_span=T0 + 5 * SEC,
            ),
            'req-b': SpanStats(span_count=1, last_span=T0),
            'req-c': SpanStats(span_count=1, input_tokens=999, last_span=T0 + 2 * SEC),
        }
        dao = self.otel_traces_dao
        assert dao.get_spans_stats_by_request_uuids([]) == {}
        assert dao.get_spans_stats_by_request_uuids([*expected, 'unknown']) == expected
        assert dao.get_spans_stats_by_request_uuids(['req-b']) == {
            'req-b': expected['req-b']
        }
        assert dao.get_spans_stats_by_trace_ids([]) == {}
        assert dao.get_spans_stats_by_trace_ids(
            [f'trace-{r}' for r in (*expected, 'unknown')]
        ) == {f'trace-{r}': stats for r, stats in expected.items()}

    def test_get_traces_chart_data(self):
        def root(trace_id, at, status='Unset'):
            return _span(at, trace_id=trace_id, span_id='root', status_code=status)

        def child(trace_id, at, status='Unset', parent='root'):
            return _span(
                at,
                trace_id=trace_id,
                span_id='child',
                status_code=status,
                parent_span_id=parent,
            )

        self.insert(
            [
                root('t1', T0),
                root('t2', T0 + 30 * MIN),
                # A child span does not count as a trace of its own.
                child('t2', T0 + 30 * MIN),
                root('t3', T0, 'Error'),
                root('t4', T0 + 40 * MIN, 'Error'),
                # A root that is fine with a failed child is a warning.
                root('t5', T0),
                child('t5', T0, 'Error'),
                # Orphan trace: only a child span, no root span.
                child('t6', T0, parent='span-missing-root'),
                root('t7', T0 + 1 * H + 30 * MIN),
            ]
        )

        def chart(granularity, **window):
            res = self.otel_traces_dao.get_traces_chart_data(
                project_uuid=TEST_PROJECT_UUID,
                route_names=None,
                **(window or {'_from': T0, '_to': T0 + 2 * H}),
                granularity=granularity,
                timezone_offset_seconds=0,
            )
            return sorted(
                (p.bucket, p.timestamp, p.trace_status, p.total_requests) for p in res
            )

        t0, t1 = int(T0.timestamp()), int((T0 + H).timestamp())
        assert chart('hours') == [
            (T0, t0, 'error', 2),
            (T0, t0, 'success', 2),
            (T0, t0, 'warning', 1),
            (T0 + H, t1, 'success', 1),
        ]
        # The orphan must not bucket to the Unix epoch: weeks start on Monday
        # and come back as naive UTC dates.
        week = datetime.datetime(2025, 1, 6)
        week_ts = int(week.replace(tzinfo=datetime.timezone.utc).timestamp())
        assert chart('weeks') == [
            (week, week_ts, 'error', 2),
            (week, week_ts, 'success', 3),
            (week, week_ts, 'warning', 1),
        ]
        assert chart('hours', **EMPTY_WINDOW) == []

    def test_get_latencies(self):
        roots = [100, 200, 300, 400]
        self.insert(
            [
                *[
                    _span(T0 + i * MIN, trace_id=f'trace-{i}', duration_ns=_ms(ms))
                    for i, ms in enumerate(roots)
                ],
                # A much longer child span is not a trace latency.
                _span(
                    T0,
                    trace_id='trace-0',
                    span_id='child',
                    duration_ns=_ms(999),
                    parent_span_id='span001',
                ),
                _span(T0 + D, trace_id='single', duration_ns=_ms(500)),
            ]
        )

        def latencies(_from):
            res = self.otel_traces_dao.get_latencies(
                project_uuid=TEST_PROJECT_UUID,
                route_names=None,
                _from=_from,
                _to=_from + H,
            )
            return (res.p50, res.p90, res.p95, res.p99)

        assert latencies(T0) == _approx(250, 370, 385, 397)
        assert latencies(T0 + D) == _approx(500, 500, 500, 500)

    def test_get_root_traces_paginated(self):
        days = [T0 + n * D for n in range(4)]
        roots = []

        def root(trace_id, day, name='invoke', ms=100, **attrs):
            at = day + len(roots) * SEC
            roots.append((at, trace_id))
            return _span(
                at,
                trace_id=trace_id,
                span_id=f'root-{trace_id}',
                span_name=name,
                duration_ns=_ms(ms),
                span_attributes=attrs,
            )

        def filtered(m, route, group, key):
            return root(m, days[1], **_meta(route, key, group=group))

        request_types = {
            't-chat': 'chat_completions.workflow',
            't-responses': 'responses.workflow',
            't-embed': 'embeddings.workflow',
            't-audio': 'audio_transcriptions.workflow',
            't-decision': 'decision_model.workflow',
            't-mcp': 'mcp_request.workflow',
            't-other': 'something_else',
        }
        self.insert(
            [
                # day 0: metadata, child spans and other projects are skipped.
                root(
                    'meta',
                    days[0],
                    ms=1500,
                    **_meta('my-route', KEY_2, 'my-api-key', GROUP_2, 'my-group'),
                ),
                _span(
                    days[0],
                    trace_id='meta',
                    span_id='child',
                    duration_ns=_ms(50),
                    parent_span_id='root-meta',
                ),
                root('later', days[0], ms=200),
                _span(
                    days[0],
                    trace_id='foreign',
                    span_attributes={f'{PROP}project_uuid': GROUP_3},
                ),
                # day 1: route, group and key filters combine with AND.
                filtered('f1', 'route-a', GROUP_1, KEY_1),
                filtered('f2', 'route-a', GROUP_1, KEY_2),
                filtered('f3', 'route-a', GROUP_2, KEY_1),
                filtered('f4', 'route-b', GROUP_1, KEY_1),
                filtered('f5', 'route-a', GROUP_2, KEY_2),
                filtered('f6', 'route-c', GROUP_3, KEY_3),
                # day 2: same tag key OR's, different keys AND.
                root('g1', days[2], **{TAGS: 'env=prod,cost_center=retail'}),
                root('g2', days[2], **{TAGS: 'env=staging,cost_center=retail'}),
                root('g3', days[2], **{TAGS: 'env=prod,cost_center=marketing'}),
                root('g4', days[2]),
                # day 3: the request type comes from the root span name.
                *[root(t, days[3], name) for t, name in request_types.items()],
            ]
        )
        dao = self.otel_traces_dao

        def page(day=None, page=1, size=20, **filters):
            args = dict.fromkeys(
                ['route_names', 'group_uuids', 'key_uuids', '_from', '_to']
            )
            if day:
                args.update(_from=day, _to=day + D)
            return dao.get_root_traces_paginated(
                project_uuid=TEST_PROJECT_UUID,
                params=Params(page=page, size=size),
                **{**args, **filters},
            )

        def ids(day=None, **filters):
            return [r.trace_id for r in page(day, **filters).items]

        # Most recent first, root spans only, metadata from the root's attributes.
        rows = [
            (
                r.trace_id,
                r.route_name,
                r.api_key_uuid,
                r.api_key_name,
                r.group_uuid,
                r.group_name,
                r.duration_ms,
                r.tags,
                r.request_type,
            )
            for r in page(days[0]).items
        ]
        assert rows == [
            ('later', '', '', '', '', '', pytest.approx(200.0, abs=0.01), [], ''),
            (
                'meta',
                'my-route',
                KEY_2,
                'my-api-key',
                GROUP_2,
                'my-group',
                pytest.approx(1500.0, abs=0.01),
                [],
                '',
            ),
        ]

        group_1, group_2 = UUID(GROUP_1), UUID(GROUP_2)
        assert {
            'group': ids(days[1], group_uuids=[group_1]),
            'key': ids(days[1], key_uuids=[UUID(KEY_1)]),
            'groups': ids(days[1], group_uuids=[group_1, group_2]),
            'route': ids(days[1], route_names=['route-b']),
            'combined': ids(
                days[1],
                route_names=['route-a', 'route-b'],
                group_uuids=[group_1],
                key_uuids=[UUID(KEY_1)],
            ),
        } == {
            'group': ['f4', 'f2', 'f1'],
            'key': ['f4', 'f3', 'f1'],
            'groups': ['f5', 'f4', 'f3', 'f2', 'f1'],
            'route': ['f4'],
            'combined': ['f4', 'f1'],
        }

        assert {r.trace_id: r.tags for r in page(days[2]).items} == {
            'g1': ['env=prod', 'cost_center=retail'],
            'g2': ['env=staging', 'cost_center=retail'],
            'g3': ['env=prod', 'cost_center=marketing'],
            'g4': [],
        }
        assert ids(days[2], tags=['env=prod', 'env=staging', 'cost_center=retail']) == [
            'g2',
            'g1',
        ]

        assert {r.trace_id: r.request_type for r in page(days[3]).items} == {
            't-chat': 'chat_completions',
            't-responses': 'chat_completions',
            't-embed': 'embeddings',
            't-audio': 'transcriptions',
            't-decision': 'decision_model',
            't-mcp': 'mcp',
            't-other': '',
        }
        by_type = page(
            days[3], request_types=[RequestType.CHAT_COMPLETIONS, RequestType.MCP]
        )
        assert ([r.trace_id for r in by_type.items], by_type.total) == (
            ['t-mcp', 't-responses', 't-chat'],
            3,
        )

        # Pages split the whole list, newest first, without overlap.
        newest_first = [trace_id for _, trace_id in sorted(roots, reverse=True)]
        page_1, page_2 = page(size=2), page(page=2, size=2)
        assert (
            [r.trace_id for r in page_1.items],
            [r.trace_id for r in page_2.items],
            page_1.total,
        ) == (newest_first[:2], newest_first[2:4], len(roots))

    # --- filters shared by the latency, chart and trace list queries ---

    def _query_all(self, route_names=None, _from=None, _to=None, tags=None):
        """Run each filtered query; return what each one saw."""
        dao = self.otel_traces_dao
        filters = {
            'project_uuid': TEST_PROJECT_UUID,
            'route_names': route_names,
            '_from': _from,
            '_to': _to,
            'tags': tags,
        }
        return {
            'span_latencies': [
                (r.span_name, r.p50) for r in dao.get_span_latencies(**filters)
            ],
            'latencies': dao.get_latencies(**filters).p50,
            'chart': sum(
                p.total_requests
                for p in dao.get_traces_chart_data(**filters, granularity='hours')
            ),
            'traces': [
                r.trace_id
                for r in dao.get_root_traces_paginated(
                    **filters,
                    group_uuids=None,
                    key_uuids=None,
                    params=Params(page=1, size=10),
                ).items
            ],
        }

    def test_queries_apply_route_time_and_tag_filters(self):
        base_time = T0
        window = {'_from': base_time, '_to': base_time + H}

        empty = self._query_all(**window)
        assert empty['span_latencies'] == []
        # ClickHouse returns nan for empty quantile results
        assert empty['latencies'] is None or math.isnan(empty['latencies'])
        assert empty['chart'] == 0
        assert empty['traces'] == []

        def root_span(trace_id, name, ms, at, route, tag):
            return _span(
                at,
                trace_id=trace_id,
                parent_span_id='',
                span_name=name,
                duration_ns=_ms(ms),
                span_attributes={f'{PROP}route_name': route, TAGS: tag},
            )

        kept = root_span('kept', 'invoke', 100, base_time, 'route-a', 'env=prod')
        # Each decoy differs from the kept span in one filtered dimension only.
        cases = {
            'route': (
                ('route-b', base_time, 'env=prod'),
                {'route_names': ['route-a']},
            ),
            'time': (('route-a', base_time + 3 * H, 'env=prod'), window),
            'tags': (('route-a', base_time, 'env=staging'), {'tags': ['env=prod']}),
        }
        for dimension, ((route, at, tag), filters) in cases.items():
            with self.subTest(dimension=dimension):
                self.insert([kept, root_span('decoy', 'other', 999, at, route, tag)])

                res = self._query_all(**filters)

                assert res['span_latencies'] == [
                    ('invoke', pytest.approx(100.0, abs=1.0))
                ]
                assert res['latencies'] == pytest.approx(100.0, abs=1.0)
                assert res['chart'] == 1
                assert res['traces'] == ['kept']
                self.clean()
