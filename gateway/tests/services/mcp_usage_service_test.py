import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock
from uuid import UUID

from fastapi_pagination import Page, Params

from radicalbit_ai_gateway.db.dao.event_dao import EventDAO
from radicalbit_ai_gateway.db.models.event import InvocationChartDataPoint
from radicalbit_ai_gateway.models.mcp_usage_dto import McpKeyUsageDTO
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.services.mcp_usage_service import McpUsageService

PROJECT_UUID = UUID('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
KEY_UUID = UUID('660e8400-e29b-41d4-a716-446655440003')
GROUP_UUID = UUID('550e8400-e29b-41d4-a716-446655440003')

LAST_CALL = datetime.datetime(2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc)


def row(
    key_uuid: UUID = KEY_UUID,
    key_name: str = 'my-key',
    group_uuid: UUID = GROUP_UUID,
    group_name: str = 'my-group',
    counter: int = 3,
    last_call: datetime.datetime = LAST_CALL,
) -> SimpleNamespace:
    """Stand in for the DAO row, which is a SQLAlchemy `Row`."""
    return SimpleNamespace(
        key_uuid=key_uuid,
        key_name=key_name,
        group_uuid=group_uuid,
        group_name=group_name,
        counter=counter,
        last_call=last_call,
    )


class McpUsageServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.event_dao = MagicMock(spec_set=EventDAO)
        cls.key_service = MagicMock(spec_set=KeyService)
        cls.group_service = MagicMock(spec_set=GroupService)
        cls.mcp_usage_service = McpUsageService(
            event_dao=cls.event_dao,
            key_service=cls.key_service,
            group_service=cls.group_service,
        )

    def usage(self, params: Params = Params(page=1, size=50), **kwargs):
        defaults = {
            'project_uuid': PROJECT_UUID,
            'route_names': None,
            '_from': None,
            '_to': None,
            'tags': None,
        }
        return self.mcp_usage_service.get_mcp_key_usage(
            **{
                **defaults,
                **kwargs,
                'params': params,
            }
        )

    def test_rows_become_dtos(self):
        params = Params(page=1, size=50)
        self.event_dao.get_mcp_key_usage_paginated = MagicMock(
            return_value=Page.create([row()], params, total=1)
        )

        res = self.usage(params)

        assert res.items == [
            McpKeyUsageDTO(
                key_name='my-key',
                key_uuid=KEY_UUID,
                group_name='my-group',
                group_uuid=GROUP_UUID,
                counter=3,
                last_call=int(LAST_CALL.timestamp()),
            )
        ]

    def test_last_call_is_epoch_seconds(self):
        params = Params(page=1, size=50)
        self.event_dao.get_mcp_key_usage_paginated = MagicMock(
            return_value=Page.create([row(last_call=LAST_CALL)], params, total=1)
        )

        res = self.usage(params)

        assert res.items[0].last_call == 1736330400

    def test_no_traffic_is_an_empty_page(self):
        params = Params(page=1, size=50)
        self.event_dao.get_mcp_key_usage_paginated = MagicMock(
            return_value=Page.create([], params, total=0)
        )

        res = self.usage(params)

        assert res.items == []
        assert res.total == 0

    def test_the_page_envelope_keeps_the_dao_total(self):
        params = Params(page=2, size=2)
        self.event_dao.get_mcp_key_usage_paginated = MagicMock(
            return_value=Page.create([row(), row(key_name='other')], params, total=7)
        )

        res = self.usage(params)

        assert res.total == 7
        assert res.page == 2
        assert res.size == 2
        assert res.pages == 4
        assert len(res.items) == 2

    def test_every_filter_reaches_the_dao(self):
        params = Params(page=3, size=10)
        _from = LAST_CALL
        _to = LAST_CALL + datetime.timedelta(hours=1)
        self.event_dao.get_mcp_key_usage_paginated = MagicMock(
            return_value=Page.create([], params, total=0)
        )

        self.usage(
            params,
            route_names=['agents', 'chat'],
            _from=_from,
            _to=_to,
            tags=['env=prod'],
        )

        call_kwargs = self.event_dao.get_mcp_key_usage_paginated.call_args.kwargs
        assert call_kwargs == {
            'project_uuid': PROJECT_UUID,
            'route_names': ['agents', 'chat'],
            '_from': _from,
            '_to': _to,
            'params': params,
            'tags': ['env=prod'],
        }


def point(
    bucket: datetime.datetime,
    group_by_value: str,
    value: int,
) -> InvocationChartDataPoint:
    return InvocationChartDataPoint(
        bucket=bucket, group_by_value=group_by_value, value=value
    )


BUCKET_0 = datetime.datetime(2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc)
BUCKET_1 = BUCKET_0 + datetime.timedelta(hours=1)
BUCKET_2 = BUCKET_0 + datetime.timedelta(hours=2)


class McpServerChartDataTest(unittest.TestCase):
    """The chart a caller receives, never how the query is built."""

    def setUp(self):
        self.event_dao = MagicMock(spec_set=EventDAO)
        self.key_service = MagicMock(spec_set=KeyService)
        self.group_service = MagicMock(spec_set=GroupService)
        self.service = McpUsageService(
            event_dao=self.event_dao,
            key_service=self.key_service,
            group_service=self.group_service,
        )

    def chart(self, points, **kwargs):
        self.event_dao.get_mcp_server_chart_data = MagicMock(return_value=points)
        defaults = {
            'project_uuid': PROJECT_UUID,
            'route_names': None,
            '_from': BUCKET_0,
            '_to': BUCKET_2,
            'tags': None,
        }
        return self.service.get_mcp_server_chart_data(**{**defaults, **kwargs})

    def test_an_empty_window_still_answers(self):
        res = self.chart([])

        assert res.granularity == 'hours'
        assert res.timestamp == []
        assert res.data == []
        assert res.total == 0

    def test_one_series_per_server_with_a_shared_axis(self):
        res = self.chart(
            [
                point(BUCKET_0, 'files', 2),
                point(BUCKET_0, 'search', 1),
                point(BUCKET_2, 'files', 4),
            ]
        )

        assert res.timestamp == [
            int(BUCKET_0.timestamp()),
            int(BUCKET_1.timestamp()),
            int(BUCKET_2.timestamp()),
        ]
        assert [(s.name, s.data) for s in res.data] == [
            ('files', [2, 0, 4]),
            ('search', [1, 0, 0]),
        ]

    def test_grouping_by_services_carries_no_uuid(self):
        res = self.chart([point(BUCKET_0, 'files', 1)], group_by='services')

        assert res.data[0].uuid is None

    def test_an_unresolved_alias_gets_its_own_series(self):
        res = self.chart(
            [point(BUCKET_0, '', 3), point(BUCKET_0, 'files', 1)],
            group_by='services',
        )

        assert [(s.name, s.data[0]) for s in res.data] == [('', 3), ('files', 1)]
        assert res.total == 4

    def test_group_names_are_resolved_and_carry_their_uuid(self):
        self.group_service.get_names_by_uuids = MagicMock(
            return_value={GROUP_UUID: 'retail'}
        )

        res = self.chart([point(BUCKET_0, str(GROUP_UUID), 5)], group_by='groups')

        assert res.data[0].name == 'retail'
        assert res.data[0].uuid == GROUP_UUID

    def test_key_names_are_resolved_and_carry_their_uuid(self):
        self.key_service.get_names_by_uuids = MagicMock(
            return_value={KEY_UUID: 'agent-key'}
        )

        res = self.chart([point(BUCKET_0, str(KEY_UUID), 5)], group_by='keys')

        assert res.data[0].name == 'agent-key'
        assert res.data[0].uuid == KEY_UUID

    def test_a_deleted_key_falls_back_to_a_labelled_name(self):
        self.key_service.get_names_by_uuids = MagicMock(return_value={})

        res = self.chart([point(BUCKET_0, str(KEY_UUID), 5)], group_by='keys')

        assert res.data[0].name == f'Deleted Key ({str(KEY_UUID)[:8]})'
        assert res.data[0].uuid == KEY_UUID

    def test_a_deleted_group_falls_back_to_a_labelled_name(self):
        self.group_service.get_names_by_uuids = MagicMock(return_value={})

        res = self.chart([point(BUCKET_0, str(GROUP_UUID), 5)], group_by='groups')

        assert res.data[0].name == f'Deleted Group ({str(GROUP_UUID)[:8]})'

    def test_two_groups_sharing_a_name_stay_two_series(self):
        other = UUID('550e8400-e29b-41d4-a716-446655440009')
        self.group_service.get_names_by_uuids = MagicMock(
            return_value={GROUP_UUID: 'retail', other: 'retail'}
        )

        res = self.chart(
            [point(BUCKET_0, str(GROUP_UUID), 2), point(BUCKET_0, str(other), 3)],
            group_by='groups',
        )

        assert len(res.data) == 2
        assert {s.uuid for s in res.data} == {GROUP_UUID, other}
        assert res.total == 5

    def test_the_total_is_the_sum_across_every_series(self):
        res = self.chart(
            [
                point(BUCKET_0, 'files', 2),
                point(BUCKET_1, 'files', 3),
                point(BUCKET_0, 'search', 7),
            ]
        )

        assert res.total == 12

    def test_counts_stay_integers(self):
        res = self.chart([point(BUCKET_0, 'files', 2)])

        assert all(isinstance(value, int) for value in res.data[0].data)
        assert isinstance(res.total, int)

    def test_the_granularity_follows_the_requested_range(self):
        res = self.chart(
            [point(BUCKET_0, 'files', 1)],
            _from=BUCKET_0 - datetime.timedelta(days=10),
            _to=BUCKET_0,
        )

        assert res.granularity == 'days'
        assert (
            self.event_dao.get_mcp_server_chart_data.call_args.kwargs['granularity']
            == 'days'
        )

    def test_every_filter_reaches_the_dao(self):
        self.chart(
            [],
            route_names=['agents'],
            group_by='keys',
            tags=['env=prod'],
        )

        call_kwargs = self.event_dao.get_mcp_server_chart_data.call_args.kwargs
        assert call_kwargs['route_names'] == ['agents']
        assert call_kwargs['group_by'] == 'keys'
        assert call_kwargs['tags'] == ['env=prod']
        assert call_kwargs['project_uuid'] == PROJECT_UUID
