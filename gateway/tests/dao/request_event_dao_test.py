import datetime

import pytest

from tests.common import db_mock
from tests.common.db_integration_ch import DatabaseIntegrationClickhouse

from radicalbit_ai_gateway.db.dao.request_event_dao import RequestEventDAO
from radicalbit_ai_gateway.models.request_event_type import RequestStatus, RequestType


class RequestEventDAOTest(DatabaseIntegrationClickhouse):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.request_event_dao = RequestEventDAO(cls.db)

    def test_get_request_chart_data(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='rb-gateway',
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(minutes=30),
                route_name='rb-gateway',
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(hours=1),
                route_name='rb-gateway',
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(hours=1, minutes=30),
                route_name='rb-gateway',
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=2)

        res = self.request_event_dao.get_request_chart_data(
            None, 'rb-gateway', _from, _to, 'hours', 0
        )
        assert res is not None
        assert len(res) == 2
        assert res[0].bucket == base_time
        assert res[0].total_requests == 2
        assert res[1].bucket == base_time + datetime.timedelta(hours=1)
        assert res[1].total_requests == 2

    def test_get_request_chart_data_empty(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        _from = base_time
        _to = base_time + datetime.timedelta(hours=2)

        res = self.request_event_dao.get_request_chart_data(
            None, 'rb-gateway', _from, _to, 'hours', 0
        )
        assert res is not None
        assert len(res) == 0

    def test_get_request_chart_data_timezone(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='rb-gateway',
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(hours=1),
                route_name='rb-gateway',
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=2)

        # GMT+1 = 3600 seconds offset
        # With GMT+1, 10:00 UTC is 11:00 local time
        # The event at 10:00 UTC should fall into the 11:00 local hour bucket
        res = self.request_event_dao.get_request_chart_data(
            None, 'rb-gateway', _from, _to, 'hours', 3600
        )
        assert res is not None
        assert len(res) == 2
        # Total counts should be correct regardless of timezone
        assert res[0].total_requests == 1
        assert res[1].total_requests == 1
        # The timestamps should be properly computed (Unix timestamps are timezone-aware)
        assert res[0].timestamp > 0
        assert res[1].timestamp > 0

    def test_get_request_chart_data_multiple_days(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='rb-gateway',
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(hours=12),
                route_name='rb-gateway',
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(days=1),
                route_name='rb-gateway',
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(days=1, hours=12),
                route_name='rb-gateway',
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(days=2)

        res = self.request_event_dao.get_request_chart_data(
            None, 'rb-gateway', _from, _to, 'days', 0
        )
        assert res is not None
        assert len(res) == 2
        assert res[0].bucket == base_time.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        assert res[0].total_requests == 2
        assert res[1].bucket == (base_time + datetime.timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        assert res[1].total_requests == 2

    def test_get_request_chart_data_filters_by_route(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='rb-gateway',
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='other-route',
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(hours=1),
                route_name='rb-gateway',
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(hours=1),
                route_name='other-route',
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=2)

        # Query only for rb-gateway
        res = self.request_event_dao.get_request_chart_data(
            None, 'rb-gateway', _from, _to, 'hours', 0
        )
        assert res is not None
        assert len(res) == 2
        assert res[0].total_requests == 1
        assert res[1].total_requests == 1

    def test_get_most_requested_route(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_request_event(timestamp=base_time, route_name='route-a'),
            db_mock.get_sample_request_event(timestamp=base_time, route_name='route-a'),
            db_mock.get_sample_request_event(timestamp=base_time, route_name='route-b'),
        ]
        self.insert(test_events)

        res = self.request_event_dao.get_most_requested_route(
            None,
            ['route-a', 'route-b'],
            base_time,
            base_time + datetime.timedelta(hours=1),
        )
        assert res == 'route-a'

    def test_get_most_requested_route_empty(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        res = self.request_event_dao.get_most_requested_route(
            None, ['route-a'], base_time, base_time + datetime.timedelta(hours=1)
        )
        assert res is None

    def test_get_request_stats_global_empty(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        res = self.request_event_dao.get_request_stats_global(
            None, _from=base_time, _to=base_time + datetime.timedelta(hours=2)
        )
        assert res.successful_requests == 0
        assert res.error_requests == 0
        assert res.total_requests == 0
        assert res.last_request_timestamp is None

    def test_get_request_stats_global_aggregates_all_routes(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-a',
                http_status_code=200,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(minutes=10),
                route_name='route-b',
                http_status_code=200,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(minutes=20),
                route_name='route-a',
                request_status=RequestStatus.UNHANDLED_ERROR,
                http_status_code=500,
            ),
        ]
        self.insert(test_events)

        res = self.request_event_dao.get_request_stats_global(
            None, _from=base_time, _to=base_time + datetime.timedelta(hours=1)
        )
        assert res.successful_requests == 2
        assert res.error_requests == 1
        assert res.total_requests == 3
        assert res.last_request_timestamp is not None

    def test_get_request_stats_counts_an_mcp_error_over_http_200_as_an_error(self):
        """MCP returns JSON-RPC failures as an `error` body over HTTP 200.

        Classifying on HTTP_STATUS_CODE counted these as successes here while
        get_error_breakdown, which reads REQUEST_STATUS, counted them as errors —
        two contradictory numbers in one dashboard response.
        """
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-a',
                request_type=RequestType.MCP,
                request_status=RequestStatus.SUCCESS,
                http_status_code=200,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(minutes=10),
                route_name='route-a',
                request_type=RequestType.MCP,
                request_status=RequestStatus.HANDLED_ERROR,
                http_status_code=200,
                error_type='mcp_jsonrpc_error',
                error_code='-32602',
            ),
        ]
        self.insert(test_events)

        res = self.request_event_dao.get_request_stats_global(
            None, _from=base_time, _to=base_time + datetime.timedelta(hours=1)
        )
        assert res.successful_requests == 1
        assert res.error_requests == 1
        assert res.total_requests == 2

    def test_get_request_stats_global_filters_by_time_range(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-a',
                http_status_code=200,
            ),
            # outside the query range
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(hours=3),
                route_name='route-b',
                http_status_code=200,
            ),
        ]
        self.insert(test_events)

        res = self.request_event_dao.get_request_stats_global(
            None, _from=base_time, _to=base_time + datetime.timedelta(hours=1)
        )
        assert res.successful_requests == 1
        assert res.total_requests == 1

    def test_get_request_stats_global_no_time_filter(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-a',
                http_status_code=200,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(days=10),
                route_name='route-b',
                http_status_code=200,
            ),
        ]
        self.insert(test_events)

        res = self.request_event_dao.get_request_stats_global(
            None, _from=None, _to=None
        )
        assert res.successful_requests == 2
        assert res.total_requests == 2

    # --- get_most_route_with_error ---

    def test_get_most_route_with_error(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-a',
                request_status=RequestStatus.HANDLED_ERROR,
                http_status_code=500,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-a',
                request_status=RequestStatus.UNHANDLED_ERROR,
                http_status_code=500,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-b',
                request_status=RequestStatus.HANDLED_ERROR,
                http_status_code=500,
            ),
        ]
        self.insert(test_events)

        res = self.request_event_dao.get_most_route_with_error(
            None,
            ['route-a', 'route-b'],
            base_time,
            base_time + datetime.timedelta(hours=1),
        )
        assert res is not None
        assert res.route_name == 'route-a'
        assert res.error_perc == 100.0

    def test_get_most_route_with_error_empty(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        res = self.request_event_dao.get_most_route_with_error(
            None,
            ['route-a', 'route-b'],
            base_time,
            base_time + datetime.timedelta(hours=1),
        )
        assert res is None

    def test_get_most_route_with_error_no_errors(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-a',
                request_status=RequestStatus.SUCCESS,
                http_status_code=200,
            ),
        ]
        self.insert(test_events)

        res = self.request_event_dao.get_most_route_with_error(
            None,
            ['route-a', 'route-b'],
            base_time,
            base_time + datetime.timedelta(hours=1),
        )
        assert res is None

    def test_get_most_route_with_error_filters_by_time_range(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-a',
                request_status=RequestStatus.HANDLED_ERROR,
                http_status_code=500,
            ),
            # outside the query range
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(hours=3),
                route_name='route-a',
                request_status=RequestStatus.HANDLED_ERROR,
                http_status_code=500,
            ),
        ]
        self.insert(test_events)

        res = self.request_event_dao.get_most_route_with_error(
            None,
            ['route-a', 'route-b'],
            base_time,
            base_time + datetime.timedelta(hours=1),
        )
        assert res is not None
        assert res.route_name == 'route-a'
        assert res.error_perc == 100.0

    def test_get_most_route_with_error_partial_error_rate(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            # route-a: 2 errors out of 5 requests = 0.4
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-a',
                request_status=RequestStatus.HANDLED_ERROR,
                http_status_code=500,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-a',
                request_status=RequestStatus.UNHANDLED_ERROR,
                http_status_code=500,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-a',
                request_status=RequestStatus.SUCCESS,
                http_status_code=200,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-a',
                request_status=RequestStatus.SUCCESS,
                http_status_code=200,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-a',
                request_status=RequestStatus.SUCCESS,
                http_status_code=200,
            ),
        ]
        self.insert(test_events)

        res = self.request_event_dao.get_most_route_with_error(
            None,
            ['route-a', 'route-b'],
            base_time,
            base_time + datetime.timedelta(hours=1),
        )
        assert res is not None
        assert res.route_name == 'route-a'
        assert res.error_perc == pytest.approx(0.4 * 100)

    def test_get_most_route_with_error_picks_highest_error_percentage(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            # route-a: 1 error out of 4 requests = 0.25
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-a',
                request_status=RequestStatus.HANDLED_ERROR,
                http_status_code=500,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-a',
                request_status=RequestStatus.SUCCESS,
                http_status_code=200,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-a',
                request_status=RequestStatus.SUCCESS,
                http_status_code=200,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-a',
                request_status=RequestStatus.SUCCESS,
                http_status_code=200,
            ),
            # route-b: 2 errors out of 3 requests ≈ 0.6667
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-b',
                request_status=RequestStatus.HANDLED_ERROR,
                http_status_code=500,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-b',
                request_status=RequestStatus.UNHANDLED_ERROR,
                http_status_code=500,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='route-b',
                request_status=RequestStatus.SUCCESS,
                http_status_code=200,
            ),
        ]
        self.insert(test_events)

        res = self.request_event_dao.get_most_route_with_error(
            None,
            ['route-a', 'route-b'],
            base_time,
            base_time + datetime.timedelta(hours=1),
        )
        assert res is not None
        assert res.route_name == 'route-b'
        assert res.error_perc == pytest.approx(2.0 / 3.0 * 100)

    # --- get_request_chart_data_grouped ---

    def test_get_request_chart_data_grouped(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='rb-gateway',
                request_status=RequestStatus.SUCCESS,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(minutes=30),
                route_name='rb-gateway',
                request_status=RequestStatus.HANDLED_ERROR,
                http_status_code=500,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(hours=1),
                route_name='rb-gateway',
                request_status=RequestStatus.SUCCESS,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(hours=1, minutes=30),
                route_name='rb-gateway',
                request_status=RequestStatus.SUCCESS,
            ),
        ]
        self.insert(test_events)

        res = self.request_event_dao.get_request_chart_data_grouped(
            None,
            'rb-gateway',
            base_time,
            base_time + datetime.timedelta(hours=2),
            'hours',
            0,
        )
        assert len(res) == 2
        assert res[0].bucket == base_time
        assert res[0].success_count == 1
        assert res[0].error_count == 1
        assert res[1].bucket == base_time + datetime.timedelta(hours=1)
        assert res[1].success_count == 2
        assert res[1].error_count == 0

    def test_get_request_chart_data_grouped_empty(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        res = self.request_event_dao.get_request_chart_data_grouped(
            None,
            'rb-gateway',
            base_time,
            base_time + datetime.timedelta(hours=2),
            'hours',
            0,
        )
        assert len(res) == 0

    # --- get_request_error_chart_data ---

    def test_get_request_error_chart_data(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='rb-gateway',
                request_status=RequestStatus.HANDLED_ERROR,
                http_status_code=500,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(minutes=30),
                route_name='rb-gateway',
                request_status=RequestStatus.UNHANDLED_ERROR,
                http_status_code=500,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time + datetime.timedelta(hours=1),
                route_name='rb-gateway',
                request_status=RequestStatus.HANDLED_ERROR,
                http_status_code=500,
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=2)

        res = self.request_event_dao.get_request_error_chart_data(
            None, 'rb-gateway', 'hours', _from, _to, 0
        )
        assert res is not None
        assert len(res) == 2
        assert res[0].bucket == base_time
        assert res[0].total_requests == 2
        assert res[1].bucket == base_time + datetime.timedelta(hours=1)
        assert res[1].total_requests == 1

    def test_get_request_error_chart_data_empty(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        res = self.request_event_dao.get_request_error_chart_data(
            None,
            'rb-gateway',
            'hours',
            base_time,
            base_time + datetime.timedelta(hours=2),
            0,
        )
        assert res is not None
        assert len(res) == 0

    def test_get_request_error_chart_data_none_route(self):
        res = self.request_event_dao.get_request_error_chart_data(
            None, None, 'hours', None, None, 0
        )
        assert res is not None
        assert len(res) == 0

    def test_get_request_error_chart_data_excludes_success(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='rb-gateway',
                request_status=RequestStatus.SUCCESS,
                http_status_code=200,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='rb-gateway',
                request_status=RequestStatus.HANDLED_ERROR,
                http_status_code=500,
            ),
        ]
        self.insert(test_events)

        res = self.request_event_dao.get_request_error_chart_data(
            None,
            'rb-gateway',
            'hours',
            base_time,
            base_time + datetime.timedelta(hours=1),
            0,
        )
        assert len(res) == 1
        assert res[0].total_requests == 1

    def test_get_request_error_chart_data_filters_by_route(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='rb-gateway',
                request_status=RequestStatus.HANDLED_ERROR,
                http_status_code=500,
            ),
            db_mock.get_sample_request_event(
                timestamp=base_time,
                route_name='other-route',
                request_status=RequestStatus.HANDLED_ERROR,
                http_status_code=500,
            ),
        ]
        self.insert(test_events)

        res = self.request_event_dao.get_request_error_chart_data(
            None,
            'rb-gateway',
            'hours',
            base_time,
            base_time + datetime.timedelta(hours=1),
            0,
        )
        assert len(res) == 1
        assert res[0].total_requests == 1
