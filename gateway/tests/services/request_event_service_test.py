import datetime
import unittest
from unittest.mock import MagicMock
import uuid

import pytest

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

    def setUp(self):
        self.request_event_dao = MagicMock(spec_set=RequestEventDAO)
        self.gateway_config = MagicMock()
        self.gateway_config.routes = {}
        self.request_event_service = RequestEventService(
            request_event_dao=self.request_event_dao,
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

        assert res.name == 'route-a'
        # Gap filling creates [5, 10, 0], so last two are [10, 0] -> ((0-10)/10)*100 = -100
        assert res.increment_percentage == -100.0

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


@pytest.mark.parametrize(
    ('data', 'expected'),
    [
        ([5], 0.0),  # fewer than two buckets
        ([0, 0], 0.0),  # no increment
        ([0, 5], 100.0),  # previous bucket 0 -> full increment
        ([5, 10], 100.0),
        ([3, 4], 33.33333333333333),
        ([10, 5], -50.0),
        ([3, 1], -66.66666666666666),
        ([7, 7], 0.0),
    ],
)
def test_calculate_increment_percentage(data, expected):
    assert calculate_increment_percentage(data) == expected
