import datetime
import unittest
from unittest.mock import MagicMock
import uuid

from radicalbit_ai_gateway.db.dao.request_event_dao import RequestEventDAO
from radicalbit_ai_gateway.db.models.event import (
    ErrorRequestChartDataPoint,
    ErrorRoute,
    RequestChartDataPoint,
    RequestGroupedChartDataPoint,
)
from radicalbit_ai_gateway.models.event_dto import (
    ChartDataSeriesDTO,
    RequestChartDataDTO,
    RequestGroupedChartDataDTO,
)
from radicalbit_ai_gateway.models.tag_dto import TagKeysDTO, TagKeyValuesDTO
from radicalbit_ai_gateway.services.request_event_service import RequestEventService
from radicalbit_ai_gateway.utils.chart_utils import calculate_increment_percentage


class RequestEventServiceTest(unittest.TestCase):
    TEST_PROJECT_UUID = uuid.UUID('12345678-1234-5678-1234-567812345678')
    TEST_PROJECT_NAME = 'rb-gateway'

    @classmethod
    def setUpClass(cls):
        cls.request_event_dao = MagicMock(spec_set=RequestEventDAO)
        cls.gateway_config = MagicMock()
        cls.gateway_config.routes = {}
        cls.request_event_service = RequestEventService(
            request_event_dao=cls.request_event_dao,
        )

    def test_get_request_chart_data(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        mocked_request_chart_data = [
            RequestChartDataPoint(bucket=base_time, total_requests=2),
            RequestChartDataPoint(
                bucket=base_time + datetime.timedelta(hours=1), total_requests=3
            ),
        ]
        self.request_event_dao.get_request_chart_data = MagicMock(
            return_value=mocked_request_chart_data
        )

        _from = base_time
        _to = base_time + datetime.timedelta(hours=2)

        res = self.request_event_service.get_request_chart_data(
            self.TEST_PROJECT_UUID, 'rb-gateway', _from, _to, 'hours'
        )

        expected = RequestChartDataDTO(
            total=5,
            granularity='hours',
            timestamp=[
                int((base_time + datetime.timedelta(hours=i)).timestamp())
                for i in range(3)
            ],
            data=[2, 3, 0],
        )
        assert res == expected

    def test_get_request_chart_data_empty(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        self.request_event_dao.get_request_chart_data = MagicMock(return_value=[])

        _from = base_time
        _to = base_time + datetime.timedelta(hours=2)

        res = self.request_event_service.get_request_chart_data(
            self.TEST_PROJECT_UUID, 'rb-gateway', _from, _to, 'hours'
        )

        expected = RequestChartDataDTO(
            total=0, granularity='hours', timestamp=[], data=[]
        )
        assert res == expected

    def test_get_request_chart_data_forwards_tags(self):
        self.request_event_dao.get_request_chart_data = MagicMock(return_value=[])
        tags = ['env=prod', 'cost_center=retail']

        self.request_event_service.get_request_chart_data(
            self.TEST_PROJECT_UUID, 'rb-gateway', None, None, 'hours', tags=tags
        )

        self.request_event_dao.get_request_chart_data.assert_called_once()
        assert (
            self.request_event_dao.get_request_chart_data.call_args.kwargs['tags']
            == tags
        )

    def test_get_request_grouped_chart_data(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        mocked_data = [
            RequestGroupedChartDataPoint(
                bucket=base_time, success_count=2, error_count=1
            ),
            RequestGroupedChartDataPoint(
                bucket=base_time + datetime.timedelta(hours=1),
                success_count=3,
                error_count=0,
            ),
        ]
        self.request_event_dao.get_request_chart_data_grouped = MagicMock(
            return_value=mocked_data
        )

        _from = base_time
        _to = base_time + datetime.timedelta(hours=2)

        res = self.request_event_service.get_request_grouped_chart_data(
            self.TEST_PROJECT_UUID, 'rb-gateway', _from, _to, 'hours'
        )

        all_timestamps = [
            int((base_time + datetime.timedelta(hours=i)).timestamp()) for i in range(3)
        ]
        expected = RequestGroupedChartDataDTO(
            total=6,
            granularity='hours',
            timestamp=all_timestamps,
            data=[
                ChartDataSeriesDTO(name='success', data=[2.0, 3.0, 0.0]),
                ChartDataSeriesDTO(name='error', data=[1.0, 0.0, 0.0]),
            ],
        )
        assert res == expected

    def test_get_request_grouped_chart_data_empty(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        self.request_event_dao.get_request_chart_data_grouped = MagicMock(
            return_value=[]
        )

        res = self.request_event_service.get_request_grouped_chart_data(
            self.TEST_PROJECT_UUID,
            'rb-gateway',
            base_time,
            base_time + datetime.timedelta(hours=2),
            'hours',
        )

        expected = RequestGroupedChartDataDTO(
            total=0,
            granularity='hours',
            timestamp=[],
            data=[],
        )
        assert res == expected

    def test_get_most_requested_route(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        self.request_event_dao.get_most_requested_route = MagicMock(
            return_value='route-a'
        )
        # The service fills gaps, so with a 2-hour range, it generates 3 buckets
        # Last two data points will be [10, 0], resulting in ((0-10)/10)*100 = -100%
        self.request_event_dao.get_request_chart_data = MagicMock(
            return_value=[
                RequestChartDataPoint(bucket=base_time, total_requests=5),
                RequestChartDataPoint(
                    bucket=base_time + datetime.timedelta(hours=1), total_requests=10
                ),
            ]
        )

        res = self.request_event_service.get_most_requested_route(
            self.TEST_PROJECT_UUID,
            self.gateway_config,
            base_time,
            base_time + datetime.timedelta(hours=2),
        )

        assert res is not None
        assert res.name == 'route-a'
        # Gap filling creates [5, 10, 0], so last two are [10, 0] -> ((0-10)/10)*100 = -100
        assert res.increment_percentage == -100.0

    def test_get_most_requested_route_positive_increment(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        self.request_event_dao.get_most_requested_route = MagicMock(
            return_value='route-a'
        )
        # Data [3, 4] with 2-hour range creates 3 buckets via gap filling: [3, 4, 0]
        # Last two are [4, 0], but we want to test [3, 4] -> ((4-3)/3)*100 = 33.333...%
        # So we use 1-hour range to get exactly [3, 4] as last two buckets
        self.request_event_dao.get_request_chart_data = MagicMock(
            return_value=[
                RequestChartDataPoint(bucket=base_time, total_requests=3),
                RequestChartDataPoint(
                    bucket=base_time + datetime.timedelta(hours=1), total_requests=4
                ),
            ]
        )

        res = self.request_event_service.get_most_requested_route(
            self.TEST_PROJECT_UUID,
            self.gateway_config,
            base_time,
            base_time + datetime.timedelta(hours=1),
        )

        assert res is not None
        assert res.name == 'route-a'
        # With 1-hour range, gap filling creates [3, 4], so ((4-3)/3)*100 = 33.333...%
        assert res.increment_percentage == 33.33333333333333

    def test_get_most_requested_route_negative_increment(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        self.request_event_dao.get_most_requested_route = MagicMock(
            return_value='route-b'
        )
        # Data [3, 1] -> ((1-3)/3)*100 = -66.666...%
        self.request_event_dao.get_request_chart_data = MagicMock(
            return_value=[
                RequestChartDataPoint(bucket=base_time, total_requests=3),
                RequestChartDataPoint(
                    bucket=base_time + datetime.timedelta(hours=1), total_requests=1
                ),
            ]
        )

        res = self.request_event_service.get_most_requested_route(
            self.TEST_PROJECT_UUID,
            self.gateway_config,
            base_time,
            base_time + datetime.timedelta(hours=1),
        )

        assert res is not None
        assert res.name == 'route-b'
        assert res.increment_percentage == -66.66666666666666

    def test_get_most_requested_route_zero_increment(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        self.request_event_dao.get_most_requested_route = MagicMock(
            return_value='route-c'
        )
        # Data [7, 7] -> ((7-7)/7)*100 = 0.0%
        self.request_event_dao.get_request_chart_data = MagicMock(
            return_value=[
                RequestChartDataPoint(bucket=base_time, total_requests=7),
                RequestChartDataPoint(
                    bucket=base_time + datetime.timedelta(hours=1), total_requests=7
                ),
            ]
        )

        res = self.request_event_service.get_most_requested_route(
            self.TEST_PROJECT_UUID,
            self.gateway_config,
            base_time,
            base_time + datetime.timedelta(hours=1),
        )

        assert res is not None
        assert res.name == 'route-c'
        assert res.increment_percentage == 0.0

    def test_get_most_requested_route_division_by_zero(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        self.request_event_dao.get_most_requested_route = MagicMock(
            return_value='route-d'
        )
        # Data [0, 5] -> previous bucket is 0, returns 100.0 (special case)
        self.request_event_dao.get_request_chart_data = MagicMock(
            return_value=[
                RequestChartDataPoint(bucket=base_time, total_requests=0),
                RequestChartDataPoint(
                    bucket=base_time + datetime.timedelta(hours=1), total_requests=5
                ),
            ]
        )

        res = self.request_event_service.get_most_requested_route(
            self.TEST_PROJECT_UUID,
            self.gateway_config,
            base_time,
            base_time + datetime.timedelta(hours=1),
        )

        assert res is not None
        assert res.name == 'route-d'
        assert res.increment_percentage == 100.0

    def test_get_most_requested_route_insufficient_data(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        self.request_event_dao.get_most_requested_route = MagicMock(
            return_value='route-e'
        )
        # Only 1 data point -> cannot calculate increment, returns 0.0
        self.request_event_dao.get_request_chart_data = MagicMock(
            return_value=[
                RequestChartDataPoint(bucket=base_time, total_requests=5),
            ]
        )

        res = self.request_event_service.get_most_requested_route(
            self.TEST_PROJECT_UUID,
            self.gateway_config,
            base_time,
            base_time + datetime.timedelta(hours=0),
        )

        assert res is not None
        assert res.name == 'route-e'
        assert res.increment_percentage == 0.0

    def test_get_most_requested_route_both_zero(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        self.request_event_dao.get_most_requested_route = MagicMock(
            return_value='route-e'
        )
        # Both data point at 0 -> cannot calculate increment, returns 0.0
        self.request_event_dao.get_request_chart_data = MagicMock(
            return_value=[
                RequestChartDataPoint(bucket=base_time, total_requests=0),
                RequestChartDataPoint(
                    bucket=base_time + datetime.timedelta(hours=1), total_requests=0
                ),
            ]
        )

        res = self.request_event_service.get_most_requested_route(
            self.TEST_PROJECT_UUID,
            self.gateway_config,
            base_time,
            base_time + datetime.timedelta(hours=0),
        )

        assert res is not None
        assert res.name == 'route-e'
        assert res.increment_percentage == 0.0

    def test_get_most_requested_route_none(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        self.request_event_dao.get_most_requested_route = MagicMock(return_value=None)

        res = self.request_event_service.get_most_requested_route(
            self.TEST_PROJECT_UUID,
            self.gateway_config,
            base_time,
            base_time + datetime.timedelta(hours=2),
        )

        assert res is None

    def test_calculate_increment_percentage_division_by_zero(self):
        result = calculate_increment_percentage([0, 5])
        assert result == 100.0

    def test_calculate_increment_percentage_insufficient_data(self):
        result = calculate_increment_percentage([5])
        assert result == 0.0

    def test_calculate_increment_both_zero(self):
        result = calculate_increment_percentage([0, 0])
        assert result == 0.0

    def test_calculate_increment_percentage_normal(self):
        result = calculate_increment_percentage([5, 10])
        assert result == 100.0  # ((10-5)/5)*100

    def test_calculate_increment_percentage_negative(self):
        result = calculate_increment_percentage([10, 5])
        assert result == -50.0  # ((5-10)/10)*100

    def test_get_most_requested_error_route_none(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        self.request_event_dao.get_most_route_with_error = MagicMock(return_value=None)

        res = self.request_event_service.get_most_requested_error_route(
            self.TEST_PROJECT_UUID,
            self.gateway_config,
            base_time,
            base_time + datetime.timedelta(hours=2),
        )

        assert res is None

    def test_get_most_requested_error_route(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        self.request_event_dao.get_most_route_with_error = MagicMock(
            return_value=ErrorRoute(route_name='route-a', error_perc=0.6)
        )
        self.request_event_dao.get_request_error_chart_data = MagicMock(
            return_value=[
                ErrorRequestChartDataPoint(bucket=base_time, total_requests=3),
                ErrorRequestChartDataPoint(
                    bucket=base_time + datetime.timedelta(hours=1), total_requests=2
                ),
            ]
        )

        _from = base_time
        _to = base_time + datetime.timedelta(hours=2)

        res = self.request_event_service.get_most_requested_error_route(
            self.TEST_PROJECT_UUID, self.gateway_config, _from, _to
        )

        assert res is not None
        assert res.name == 'route-a'
        assert res.chart.total == 0.6
        assert res.chart.data == [3, 2, 0]
        # Gap filling creates [3, 2, 0], so last two are [2, 0] -> ((0-2)/2)*100 = -100
        assert res.increment_percentage == -100.0

    def test_get_most_requested_error_route_empty_chart(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        self.request_event_dao.get_most_route_with_error = MagicMock(
            return_value=ErrorRoute(route_name='route-a', error_perc=0.1)
        )
        self.request_event_dao.get_request_error_chart_data = MagicMock(return_value=[])

        res = self.request_event_service.get_most_requested_error_route(
            self.TEST_PROJECT_UUID,
            self.gateway_config,
            base_time,
            base_time + datetime.timedelta(hours=2),
        )

        assert res is not None
        assert res.name == 'route-a'
        assert res.increment_percentage == 0.0
        assert res.chart.total == 0
        assert res.chart.data == []

    def test_get_tag_keys(self):
        self.request_event_dao.get_distinct_tags = MagicMock(
            return_value=[
                'app=my-app',
                'cost_center=retail',
                'env=prod',
                'env=staging',
            ]
        )

        res = self.request_event_service.get_tag_keys(self.TEST_PROJECT_UUID)

        expected = TagKeysDTO(tag_keys=['app', 'cost_center', 'env'])
        assert res == expected
        self.request_event_dao.get_distinct_tags.assert_called_once_with(
            self.TEST_PROJECT_UUID
        )

    def test_get_tag_keys_empty(self):
        self.request_event_dao.get_distinct_tags = MagicMock(return_value=[])

        res = self.request_event_service.get_tag_keys(self.TEST_PROJECT_UUID)

        assert res == TagKeysDTO(tag_keys=[])

    def test_get_tag_key_values(self):
        self.request_event_dao.get_distinct_tag_values = MagicMock(
            return_value=['prod', 'staging']
        )

        res = self.request_event_service.get_tag_key_values(
            self.TEST_PROJECT_UUID, 'env'
        )

        assert res == TagKeyValuesDTO(tag_values=['prod', 'staging'])
        self.request_event_dao.get_distinct_tag_values.assert_called_once_with(
            self.TEST_PROJECT_UUID, 'env'
        )

    def test_get_tag_key_values_empty(self):
        self.request_event_dao.get_distinct_tag_values = MagicMock(return_value=[])

        res = self.request_event_service.get_tag_key_values(
            self.TEST_PROJECT_UUID, 'unknown'
        )

        assert res == TagKeyValuesDTO(tag_values=[])
