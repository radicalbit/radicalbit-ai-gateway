"""Ranked MCP key usage over the `event` table, against a real ClickHouse.

Every case asserts on the rows an operator would see: who is in the table, in
what order, with what count and what last call. Nothing here looks at how the
SQL is put together.
"""

import datetime
import uuid

from fastapi_pagination import Params

from tests.common import db_mock
from tests.common.db_integration_ch import DatabaseIntegrationClickhouse

from radicalbit_ai_gateway.db.dao.event_dao import EventDAO

PROJECT_A = uuid.UUID('11111111-1111-1111-1111-111111111111')
PROJECT_B = uuid.UUID('22222222-2222-2222-2222-222222222222')

KEY_1 = uuid.UUID(int=1)
KEY_2 = uuid.UUID(int=2)
KEY_3 = uuid.UUID(int=3)
GROUP_1 = uuid.UUID(int=101)
GROUP_2 = uuid.UUID(int=102)

BASE_TIME = datetime.datetime(2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc)


def mcp_event(
    project_uuid: uuid.UUID = PROJECT_A,
    api_key_uuid: uuid.UUID = KEY_1,
    api_key_name: str = 'key-one',
    group_uuid: uuid.UUID = GROUP_1,
    group_name: str = 'group-one',
    route_name: str = 'route-a',
    timestamp: datetime.datetime = BASE_TIME,
    tags: list[str] | None = None,
    event_type: str = 'MCP_INVOCATION',
    mcp_method: str = 'tools/call',
    mcp_alias: str = 'files',
):
    return db_mock.get_sample_event(
        event_type=event_type,
        project_uuid=project_uuid,
        api_key_uuid=api_key_uuid,
        api_key_name=api_key_name,
        group_uuid=group_uuid,
        group_name=group_name,
        route_name=route_name,
        timestamp=timestamp,
        tags=tags,
        mcp_method=mcp_method,
        mcp_alias=mcp_alias,
    )


class EventDAOMcpKeyUsageTest(DatabaseIntegrationClickhouse):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.event_dao = EventDAO(cls.db)

    def usage(
        self,
        route_names: list[str] | None = None,
        _from: datetime.datetime | None = None,
        _to: datetime.datetime | None = None,
        tags: list[str] | None = None,
        page: int = 1,
        size: int = 50,
    ):
        return self.event_dao.get_mcp_key_usage_paginated(
            project_uuid=PROJECT_A,
            route_names=route_names,
            _from=_from,
            _to=_to,
            params=Params(page=page, size=size),
            tags=tags,
        )

    def test_each_filter_narrows_the_table_to_the_matching_keys(self):
        """One data set, one query per filter. Routes and values of one tag
        key are ORed, different tag keys are ANDed, the window is inclusive,
        and other event types and other projects never count.
        """
        end = BASE_TIME + datetime.timedelta(hours=1)
        half = BASE_TIME + datetime.timedelta(minutes=30)
        before = BASE_TIME - datetime.timedelta(minutes=1)
        after = end + datetime.timedelta(minutes=1)
        prod_retail = ['env=prod', 'cost_center=retail']
        key_2 = {
            'api_key_uuid': KEY_2,
            'api_key_name': 'key-two',
            'group_uuid': GROUP_2,
            'group_name': 'group-two',
        }
        key_3 = {'api_key_uuid': KEY_3, 'api_key_name': 'key-three'}
        self.insert(
            [
                mcp_event(timestamp=BASE_TIME, tags=prod_retail),
                mcp_event(timestamp=end, tags=prod_retail),
                mcp_event(
                    route_name='route-b', timestamp=half, tags=['env=staging'], **key_2
                ),
                mcp_event(
                    route_name='route-c', timestamp=before, tags=['env=prod'], **key_3
                ),
                mcp_event(
                    route_name='route-c', timestamp=after, tags=['env=dev'], **key_3
                ),
                *(
                    mcp_event(event_type=event_type, **key_2)
                    for event_type in ('MODEL_INVOCATION', 'REQUEST', 'GUARDRAIL')
                ),
                mcp_event(project_uuid=PROJECT_B, **key_2),
            ]
        )
        k1 = (KEY_1, 'key-one', GROUP_1, 'group-one')
        k2 = (KEY_2, 'key-two', GROUP_2, 'group-two')
        k3 = (KEY_3, 'key-three', GROUP_1, 'group-one')

        for filters, expected in (
            ({}, [(*k3, 2, after), (*k1, 2, end), (*k2, 1, half)]),
            ({'_from': BASE_TIME, '_to': end}, [(*k1, 2, end), (*k2, 1, half)]),
            ({'route_names': ['route-a']}, [(*k1, 2, end)]),
            (
                {'route_names': ['route-a', 'route-b']},
                [(*k1, 2, end), (*k2, 1, half)],
            ),
            ({'route_names': ['route-z']}, []),
            (
                {'tags': ['env=prod', 'env=staging']},
                [(*k1, 2, end), (*k2, 1, half), (*k3, 1, before)],
            ),
            ({'tags': prod_retail}, [(*k1, 2, end)]),
            ({'tags': ['env=unknown']}, []),
        ):
            with self.subTest(**filters):
                res = self.usage(**filters)

                assert [tuple(row) for row in res.items] == expected
                assert res.total == len(expected)

    def test_all_four_filters_compose(self):
        in_window = BASE_TIME + datetime.timedelta(minutes=30)
        self.insert(
            [
                # The only row that survives every filter.
                mcp_event(
                    route_name='agents',
                    timestamp=in_window,
                    tags=['env=prod'],
                ),
                # Right route and tag, outside the window.
                mcp_event(
                    api_key_uuid=KEY_2,
                    route_name='agents',
                    timestamp=BASE_TIME - datetime.timedelta(days=1),
                    tags=['env=prod'],
                ),
                # Right window and tag, wrong route.
                mcp_event(
                    api_key_uuid=KEY_2,
                    route_name='chat',
                    timestamp=in_window,
                    tags=['env=prod'],
                ),
                # Right route and window, wrong tag.
                mcp_event(
                    api_key_uuid=KEY_3,
                    route_name='agents',
                    timestamp=in_window,
                    tags=['env=staging'],
                ),
                # Everything right, wrong project.
                mcp_event(
                    project_uuid=PROJECT_B,
                    api_key_uuid=KEY_3,
                    route_name='agents',
                    timestamp=in_window,
                    tags=['env=prod'],
                ),
            ]
        )

        res = self.usage(
            route_names=['agents'],
            _from=BASE_TIME,
            _to=BASE_TIME + datetime.timedelta(hours=1),
            tags=['env=prod'],
        )

        assert [tuple(row) for row in res.items] == [
            (KEY_1, 'key-one', GROUP_1, 'group-one', 1, in_window)
        ]
        assert res.total == 1

    def test_rows_rank_by_count_then_last_call_then_key_across_pages(self):
        """Two keys sharing a name stay two rows, and a full tie on count and
        last call ranks by key, so no key shows up on two pages.
        """
        later = BASE_TIME + datetime.timedelta(hours=1)
        key_4 = uuid.UUID(int=4)
        self.insert(
            [
                # KEY_3 leads on count.
                *(mcp_event(api_key_uuid=KEY_3) for _ in range(3)),
                # The rest tie on count; KEY_2 called last.
                mcp_event(api_key_uuid=KEY_2, timestamp=later),
                # KEY_4 and KEY_1 tie on everything, name included.
                mcp_event(api_key_uuid=key_4, api_key_name='same-name'),
                mcp_event(api_key_uuid=KEY_1, api_key_name='same-name'),
            ]
        )

        page1 = self.usage(page=1, size=2)
        page2 = self.usage(page=2, size=2)

        assert [(row.key_uuid, row.counter) for row in page1.items] == [
            (KEY_3, 3),
            (KEY_2, 1),
        ]
        assert [(row.key_uuid, row.key_name) for row in page2.items] == [
            (KEY_1, 'same-name'),
            (key_4, 'same-name'),
        ]
        assert (page1.total, page2.total) == (4, 4)
