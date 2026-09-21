import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock
from uuid import UUID

from fastapi_pagination import Page, Params

from radicalbit_ai_gateway.db.dao.event_dao import EventDAO
from radicalbit_ai_gateway.models.mcp_usage_dto import McpKeyUsageDTO
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
        cls.mcp_usage_service = McpUsageService(event_dao=cls.event_dao)

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
