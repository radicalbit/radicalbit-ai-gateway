import datetime

import pytest

from tests.common import db_mock
from tests.common.db_integration_ch import DatabaseIntegrationClickhouse

from radicalbit_ai_gateway.db.dao.request_event_dao import RequestEventDAO
from radicalbit_ai_gateway.db.models.event import RequestStats
from radicalbit_ai_gateway.models.request_event_type import RequestStatus, RequestType

T0 = datetime.datetime(2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc)
H = datetime.timedelta(hours=1)
M = datetime.timedelta(minutes=1)
D = datetime.timedelta(days=1)
S = RequestStatus.SUCCESS
HE = RequestStatus.HANDLED_ERROR
UE = RequestStatus.UNHANDLED_ERROR


def _event(route, at, status=S, **kwargs):
    return db_mock.get_sample_request_event(
        timestamp=at,
        route_name=route,
        request_status=status,
        http_status_code=200 if status == S else 500,
        **kwargs,
    )


def _midnight(at):
    return at.replace(hour=0, minute=0, second=0, microsecond=0)


class RequestEventDAOTest(DatabaseIntegrationClickhouse):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.request_event_dao = RequestEventDAO(cls.db)

    def test_chart_data_buckets_filter_route_status_and_time(self):
        dao = self.request_event_dao
        window = (T0, T0 + 2 * H)
        empty_window = (T0 - D, T0 - D + 2 * H)
        two_days = (T0, T0 + 2 * D)
        self.insert(
            [
                _event('rb-gateway', T0),
                _event('rb-gateway', T0 + 30 * M, HE),
                _event('rb-gateway', T0 + H),
                _event('rb-gateway', T0 + H + 30 * M),
                _event('rb-gateway', T0 + 12 * H),
                _event('rb-gateway', T0 + D),
                _event('rb-gateway', T0 + D + 12 * H, UE),
                _event('other-route', T0, HE),
                _event('other-route', T0 + 30 * M, UE),
                _event('other-route', T0 + H, HE),
                _event('other-route', T0 + H),
            ]
        )

        def chart(_from, _to, granularity, tz=0, route='rb-gateway'):
            res = dao.get_request_chart_data(None, route, _from, _to, granularity, tz)
            return [(p.bucket, p.total_requests) for p in res]

        def grouped(_from, _to, granularity):
            res = dao.get_request_chart_data_grouped(
                None, 'rb-gateway', _from, _to, granularity, 0
            )
            return [(p.bucket, p.success_count, p.error_count) for p in res]

        def errors(route, _from, _to, granularity='hours'):
            res = dao.get_request_error_chart_data(
                None, route, granularity, _from, _to, 0
            )
            return [(p.bucket, p.total_requests) for p in res]

        # Hourly buckets count rb-gateway only; other-route is filtered out.
        assert chart(*window, 'hours') == [(T0, 2), (T0 + H, 2)]
        # A whole-hour offset keeps hour buckets on the same instants.
        hourly_gmt1 = dao.get_request_chart_data(
            None, 'rb-gateway', *window, 'hours', 3600
        )
        assert [(p.bucket, p.total_requests, p.timestamp) for p in hourly_gmt1] == [
            (T0, 2, int(T0.timestamp())),
            (T0 + H, 2, int((T0 + H).timestamp())),
        ]
        assert chart(*two_days, 'days') == [
            (_midnight(T0), 5),
            (_midnight(T0 + D), 2),
        ]
        # GMT+3: 22:00 UTC falls into the next local day, buckets start 21:00 UTC.
        local_midnight = _midnight(T0) - 3 * H
        assert chart(*two_days, 'days', tz=3 * 3600) == [
            (local_midnight, 4),
            (local_midnight + D, 2),
            (local_midnight + 2 * D, 1),
        ]
        assert grouped(*window, 'hours') == [(T0, 1, 1), (T0 + H, 2, 0)]
        # The error chart drops successes and other routes.
        assert errors('other-route', *window) == [(T0, 2), (T0 + H, 1)]
        assert errors('rb-gateway', *two_days, 'days') == [
            (_midnight(T0), 1),
            (_midnight(T0 + D), 1),
        ]
        assert errors(None, None, None) == []
        assert chart(*empty_window, 'hours') == []
        assert grouped(*empty_window, 'hours') == []
        assert errors('rb-gateway', *empty_window) == []

    def test_request_stats_global_and_most_requested_route(self):
        dao = self.request_event_dao
        window = (T0, T0 + H)
        routes = ['route-a', 'route-b']
        assert dao.get_request_stats_global(None, *window) == RequestStats()
        assert dao.get_most_requested_route(None, routes, *window) is None

        self.insert(
            [
                _event('route-a', T0),
                _event('route-b', T0 + 10 * M),
                _event('route-a', T0 + 20 * M, UE),
                # MCP returns JSON-RPC failures as an `error` body over HTTP 200:
                # REQUEST_STATUS, not HTTP_STATUS_CODE, classifies it as an error.
                db_mock.get_sample_request_event(
                    timestamp=T0 + 30 * M,
                    route_name='route-a',
                    request_type=RequestType.MCP,
                    request_status=HE,
                    http_status_code=200,
                    error_type='mcp_jsonrpc_error',
                    error_code='-32602',
                ),
                # Outside the window.
                _event('route-b', T0 + 3 * H),
                _event('route-b', T0 + 10 * D),
            ]
        )

        stats = dao.get_request_stats_global
        assert stats(None, *window) == RequestStats(
            successful_requests=2,
            error_requests=2,
            total_requests=4,
            last_request_timestamp=T0 + 30 * M,
        )
        assert stats(None, None, None) == RequestStats(
            successful_requests=4,
            error_requests=2,
            total_requests=6,
            last_request_timestamp=T0 + 10 * D,
        )
        assert {
            'window': dao.get_most_requested_route(None, routes, *window),
            'later': dao.get_most_requested_route(
                None, routes, T0 + 2 * H, T0 + 11 * D
            ),
            'no_routes': dao.get_most_requested_route(None, [], None, None),
        } == {'window': 'route-a', 'later': 'route-b', 'no_routes': None}

    def test_get_most_route_with_error(self):
        # Each day is a separate scenario, queried over its own one-hour window.
        days = [T0 + n * D for n in range(6)]
        self.insert(
            [
                # day 1: successes only.
                _event('route-a', days[1]),
                # day 2: route-a 2 errors out of 5 requests.
                _event('route-a', days[2], HE),
                _event('route-a', days[2], UE),
                *[_event('route-a', days[2]) for _ in range(3)],
                # day 3: route-a 1/4, route-b 2/3, route-c (not configured) 1/1.
                _event('route-a', days[3], HE),
                *[_event('route-a', days[3]) for _ in range(3)],
                _event('route-b', days[3], HE),
                _event('route-b', days[3], UE),
                _event('route-b', days[3]),
                _event('route-c', days[3], HE),
                # day 4: route-a 2/2, route-b 1/2; route-a successes outside the
                # window would drop it to 2/5 if they were counted.
                _event('route-a', days[4], HE),
                _event('route-a', days[4], UE),
                _event('route-b', days[4], HE),
                _event('route-b', days[4]),
                *[_event('route-a', days[4] + 3 * H) for _ in range(3)],
                # day 5: a single failed request is enough: route-b 1/4.
                *[_event('route-a', days[5]) for _ in range(2)],
                _event('route-b', days[5], HE),
                *[_event('route-b', days[5]) for _ in range(3)],
            ]
        )

        def worst(day):
            res = self.request_event_dao.get_most_route_with_error(
                None, ['route-a', 'route-b'], day, day + H
            )
            return res and (res.route_name, res.error_perc)

        assert [worst(day) for day in days] == [
            None,
            None,
            ('route-a', pytest.approx(40.0)),
            ('route-b', pytest.approx(200 / 3)),
            ('route-a', 100.0),
            ('route-b', 25.0),
        ]
        assert (
            self.request_event_dao.get_most_route_with_error(None, [], None, None)
            is None
        )
