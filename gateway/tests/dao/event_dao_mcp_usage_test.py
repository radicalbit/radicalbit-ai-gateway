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

    def test_no_mcp_traffic_returns_an_empty_page(self):
        self.insert([mcp_event(event_type='MODEL_INVOCATION')])

        res = self.usage()

        assert res.items == []
        assert res.total == 0

    def test_one_row_per_key_with_count_and_last_call(self):
        last_call = BASE_TIME + datetime.timedelta(hours=2)
        self.insert(
            [
                mcp_event(timestamp=BASE_TIME),
                mcp_event(timestamp=BASE_TIME + datetime.timedelta(hours=1)),
                mcp_event(timestamp=last_call),
                mcp_event(
                    api_key_uuid=KEY_2,
                    api_key_name='key-two',
                    group_uuid=GROUP_2,
                    group_name='group-two',
                    timestamp=BASE_TIME,
                ),
            ]
        )

        res = self.usage()

        assert res.total == 2
        first, second = res.items
        assert first.key_uuid == KEY_1
        assert first.key_name == 'key-one'
        assert first.group_uuid == GROUP_1
        assert first.group_name == 'group-one'
        assert first.counter == 3
        assert first.last_call == last_call
        assert second.key_uuid == KEY_2
        assert second.counter == 1
        assert second.last_call == BASE_TIME

    def test_two_keys_sharing_a_name_stay_two_rows(self):
        self.insert(
            [
                mcp_event(api_key_uuid=KEY_1, api_key_name='same-name'),
                mcp_event(api_key_uuid=KEY_2, api_key_name='same-name'),
            ]
        )

        res = self.usage()

        assert res.total == 2
        assert [row.key_uuid for row in res.items] == [KEY_1, KEY_2]
        assert {row.key_name for row in res.items} == {'same-name'}

    def test_other_event_types_are_not_counted(self):
        self.insert(
            [
                mcp_event(),
                mcp_event(event_type='MODEL_INVOCATION'),
                mcp_event(event_type='REQUEST'),
                mcp_event(event_type='GUARDRAIL'),
            ]
        )

        res = self.usage()

        assert res.total == 1
        assert res.items[0].counter == 1

    def test_another_project_is_not_counted(self):
        self.insert(
            [
                mcp_event(),
                mcp_event(project_uuid=PROJECT_B, api_key_uuid=KEY_2),
            ]
        )

        res = self.usage()

        assert res.total == 1
        assert res.items[0].key_uuid == KEY_1

    def test_time_window_boundaries_are_inclusive(self):
        before = BASE_TIME - datetime.timedelta(minutes=1)
        after = BASE_TIME + datetime.timedelta(hours=1, minutes=1)
        self.insert(
            [
                mcp_event(timestamp=before),
                mcp_event(timestamp=BASE_TIME),
                mcp_event(timestamp=BASE_TIME + datetime.timedelta(hours=1)),
                mcp_event(timestamp=after),
            ]
        )

        res = self.usage(_from=BASE_TIME, _to=BASE_TIME + datetime.timedelta(hours=1))

        assert res.total == 1
        assert res.items[0].counter == 2
        assert res.items[0].last_call == BASE_TIME + datetime.timedelta(hours=1)

    def test_a_single_route_narrows_the_table(self):
        self.insert(
            [
                mcp_event(route_name='route-a'),
                mcp_event(route_name='route-b', api_key_uuid=KEY_2),
            ]
        )

        res = self.usage(route_names=['route-a'])

        assert res.total == 1
        assert res.items[0].key_uuid == KEY_1

    def test_multiple_routes_are_ored(self):
        self.insert(
            [
                mcp_event(route_name='route-a'),
                mcp_event(route_name='route-b', api_key_uuid=KEY_2),
                mcp_event(route_name='route-c', api_key_uuid=KEY_3),
            ]
        )

        res = self.usage(route_names=['route-a', 'route-b'])

        assert res.total == 2
        assert {row.key_uuid for row in res.items} == {KEY_1, KEY_2}

    def test_a_route_matching_nothing_returns_an_empty_page(self):
        self.insert([mcp_event(route_name='route-a')])

        res = self.usage(route_names=['route-z'])

        assert res.items == []
        assert res.total == 0

    def test_tag_values_of_the_same_key_are_ored(self):
        self.insert(
            [
                mcp_event(tags=['env=prod']),
                mcp_event(api_key_uuid=KEY_2, tags=['env=staging']),
                mcp_event(api_key_uuid=KEY_3, tags=['env=dev']),
            ]
        )

        res = self.usage(tags=['env=prod', 'env=staging'])

        assert res.total == 2
        assert {row.key_uuid for row in res.items} == {KEY_1, KEY_2}

    def test_tags_of_different_keys_are_anded(self):
        self.insert(
            [
                mcp_event(tags=['env=prod', 'cost_center=retail']),
                mcp_event(api_key_uuid=KEY_2, tags=['env=prod']),
                mcp_event(api_key_uuid=KEY_3, tags=['cost_center=retail']),
            ]
        )

        res = self.usage(tags=['env=prod', 'cost_center=retail'])

        assert res.total == 1
        assert res.items[0].key_uuid == KEY_1

    def test_a_tag_matching_nothing_returns_an_empty_page(self):
        self.insert([mcp_event(tags=['env=prod'])])

        res = self.usage(tags=['env=unknown'])

        assert res.items == []
        assert res.total == 0

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

        assert res.total == 1
        assert res.items[0].key_uuid == KEY_1
        assert res.items[0].counter == 1
        assert res.items[0].last_call == in_window

    def test_rows_rank_by_count_then_last_call_then_key(self):
        later = BASE_TIME + datetime.timedelta(hours=1)
        self.insert(
            [
                # KEY_3 leads on count.
                mcp_event(api_key_uuid=KEY_3, timestamp=BASE_TIME),
                mcp_event(api_key_uuid=KEY_3, timestamp=BASE_TIME),
                mcp_event(api_key_uuid=KEY_3, timestamp=BASE_TIME),
                # KEY_1 and KEY_2 tie on count; KEY_2 called last.
                mcp_event(api_key_uuid=KEY_1, timestamp=BASE_TIME),
                mcp_event(api_key_uuid=KEY_2, timestamp=later),
            ]
        )

        res = self.usage()

        assert [row.key_uuid for row in res.items] == [KEY_3, KEY_2, KEY_1]

    def test_a_pair_tied_on_count_and_last_call_ranks_by_key(self):
        self.insert(
            [
                mcp_event(api_key_uuid=KEY_2, timestamp=BASE_TIME),
                mcp_event(api_key_uuid=KEY_1, timestamp=BASE_TIME),
            ]
        )

        res = self.usage()

        assert [row.key_uuid for row in res.items] == [KEY_1, KEY_2]

    def test_page_two_returns_the_rest_without_repeating_page_one(self):
        keys = [uuid.UUID(int=10 + i) for i in range(5)]
        events = []
        for rank, key in enumerate(keys):
            # Descending counts: 5, 4, 3, 2, 1.
            events.extend(
                mcp_event(api_key_uuid=key, api_key_name=f'key-{rank}')
                for _ in range(5 - rank)
            )
        self.insert(events)

        page1 = self.usage(page=1, size=2)
        page2 = self.usage(page=2, size=2)

        assert page1.total == 5
        assert page2.total == 5
        assert [row.key_uuid for row in page1.items] == keys[:2]
        assert [row.key_uuid for row in page2.items] == keys[2:4]
        assert [row.counter for row in page2.items] == [3, 2]
