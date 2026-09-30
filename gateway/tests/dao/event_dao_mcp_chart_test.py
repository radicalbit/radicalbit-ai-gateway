"""Bucketed MCP invocations over the `event` table, against a real ClickHouse.

Every case asserts on the buckets an operator would see on the chart: which
series exist, in which bucket, with what count. Nothing here looks at how the
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
GROUP_1 = uuid.UUID(int=101)
GROUP_2 = uuid.UUID(int=102)

BASE_TIME = datetime.datetime(2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc)


def mcp_event(
    project_uuid: uuid.UUID = PROJECT_A,
    api_key_uuid: uuid.UUID = KEY_1,
    group_uuid: uuid.UUID = GROUP_1,
    route_name: str = 'route-a',
    timestamp: datetime.datetime = BASE_TIME,
    tags: list[str] | None = None,
    event_type: str = 'MCP_INVOCATION',
    mcp_method: str = 'tools/call',
    mcp_alias: str = 'files',
    mcp_target: str = 'read_file',
):
    return db_mock.get_sample_event(
        event_type=event_type,
        project_uuid=project_uuid,
        api_key_uuid=api_key_uuid,
        api_key_name='key-one',
        group_uuid=group_uuid,
        group_name='group-one',
        route_name=route_name,
        timestamp=timestamp,
        tags=tags,
        mcp_method=mcp_method,
        mcp_alias=mcp_alias,
        mcp_target=mcp_target,
    )


class EventDAOMcpServerChartTest(DatabaseIntegrationClickhouse):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.event_dao = EventDAO(cls.db)

    def chart(
        self,
        group_by: str = 'services',
        granularity: str = 'hours',
        route_names: list[str] | None = None,
        _from: datetime.datetime | None = None,
        _to: datetime.datetime | None = None,
        tags: list[str] | None = None,
        timezone_offset_seconds: int = 0,
        project_uuid: uuid.UUID = PROJECT_A,
    ):
        return self.event_dao.get_mcp_server_chart_data(
            project_uuid=project_uuid,
            route_names=route_names,
            _from=_from,
            _to=_to,
            granularity=granularity,
            group_by=group_by,
            timezone_offset_seconds=timezone_offset_seconds,
            tags=tags,
        )

    def buckets(self, points) -> list[tuple[int, str, int]]:
        return [(p.timestamp, p.group_by_value, p.value) for p in points]

    def test_an_empty_window_returns_no_points(self):
        self.insert([mcp_event(timestamp=BASE_TIME)])

        res = self.chart(
            _from=BASE_TIME + datetime.timedelta(days=1),
            _to=BASE_TIME + datetime.timedelta(days=2),
        )

        assert res == []

    def test_counts_per_bucket_per_server(self):
        self.insert(
            [
                mcp_event(mcp_alias='files', timestamp=BASE_TIME),
                mcp_event(
                    mcp_alias='files',
                    timestamp=BASE_TIME + datetime.timedelta(minutes=30),
                ),
                mcp_event(
                    mcp_alias='files',
                    timestamp=BASE_TIME + datetime.timedelta(hours=1),
                ),
                mcp_event(mcp_alias='search', timestamp=BASE_TIME),
            ]
        )

        res = self.chart()

        hour_0 = int(BASE_TIME.timestamp())
        hour_1 = int((BASE_TIME + datetime.timedelta(hours=1)).timestamp())
        assert self.buckets(res) == [
            (hour_0, 'files', 2),
            (hour_0, 'search', 1),
            (hour_1, 'files', 1),
        ]

    def test_counts_per_bucket_per_group(self):
        self.insert(
            [
                mcp_event(group_uuid=GROUP_1),
                mcp_event(group_uuid=GROUP_1),
                mcp_event(group_uuid=GROUP_2),
            ]
        )

        res = self.chart(group_by='groups')

        assert self.buckets(res) == [
            (int(BASE_TIME.timestamp()), str(GROUP_1), 2),
            (int(BASE_TIME.timestamp()), str(GROUP_2), 1),
        ]

    def test_counts_per_bucket_per_key(self):
        self.insert(
            [
                mcp_event(api_key_uuid=KEY_1),
                mcp_event(api_key_uuid=KEY_2),
                mcp_event(api_key_uuid=KEY_2),
            ]
        )

        res = self.chart(group_by='keys')

        assert self.buckets(res) == [
            (int(BASE_TIME.timestamp()), str(KEY_1), 1),
            (int(BASE_TIME.timestamp()), str(KEY_2), 2),
        ]

    def test_an_unresolved_alias_is_its_own_series(self):
        self.insert(
            [
                mcp_event(mcp_alias=''),
                mcp_event(mcp_alias='files'),
            ]
        )

        res = self.chart()

        assert self.buckets(res) == [
            (int(BASE_TIME.timestamp()), '', 1),
            (int(BASE_TIME.timestamp()), 'files', 1),
        ]

    def test_other_event_types_are_not_counted(self):
        self.insert(
            [
                mcp_event(),
                mcp_event(event_type='MODEL_INVOCATION'),
                mcp_event(event_type='REQUEST'),
                mcp_event(event_type='GUARDRAIL'),
            ]
        )

        res = self.chart()

        assert self.buckets(res) == [(int(BASE_TIME.timestamp()), 'files', 1)]

    def test_another_project_is_not_counted(self):
        self.insert(
            [
                mcp_event(),
                mcp_event(project_uuid=PROJECT_B, mcp_alias='search'),
            ]
        )

        res = self.chart()

        assert self.buckets(res) == [(int(BASE_TIME.timestamp()), 'files', 1)]

    def test_no_method_filter_narrows_the_count(self):
        """Membership comes from the event type alone, not from the method."""
        self.insert(
            [
                mcp_event(mcp_method='tools/call'),
                mcp_event(mcp_method='resources/read'),
                mcp_event(mcp_method='prompts/get'),
                mcp_event(mcp_method=''),
            ]
        )

        res = self.chart()

        assert self.buckets(res) == [(int(BASE_TIME.timestamp()), 'files', 4)]

    def test_daily_buckets(self):
        day_2 = BASE_TIME + datetime.timedelta(days=1)
        self.insert(
            [
                mcp_event(timestamp=BASE_TIME),
                mcp_event(timestamp=BASE_TIME + datetime.timedelta(hours=5)),
                mcp_event(timestamp=day_2),
            ]
        )

        res = self.chart(granularity='days')

        start_of_day_1 = BASE_TIME.replace(hour=0)
        assert self.buckets(res) == [
            (int(start_of_day_1.timestamp()), 'files', 2),
            (
                int((start_of_day_1 + datetime.timedelta(days=1)).timestamp()),
                'files',
                1,
            ),
        ]

    def test_weekly_buckets_start_on_monday(self):
        # 2025-01-08 is a Wednesday, so its week starts on 2025-01-06.
        next_week = BASE_TIME + datetime.timedelta(days=7)
        self.insert(
            [
                mcp_event(timestamp=BASE_TIME),
                mcp_event(timestamp=next_week),
            ]
        )

        res = self.chart(granularity='weeks')

        monday = datetime.datetime(2025, 1, 6, tzinfo=datetime.timezone.utc)
        assert self.buckets(res) == [
            (int(monday.timestamp()), 'files', 1),
            (int((monday + datetime.timedelta(days=7)).timestamp()), 'files', 1),
        ]

    def test_monthly_buckets(self):
        self.insert(
            [
                mcp_event(timestamp=BASE_TIME),
                mcp_event(timestamp=BASE_TIME + datetime.timedelta(days=31)),
            ]
        )

        res = self.chart(granularity='months')

        january = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
        february = datetime.datetime(2025, 2, 1, tzinfo=datetime.timezone.utc)
        assert self.buckets(res) == [
            (int(january.timestamp()), 'files', 1),
            (int(february.timestamp()), 'files', 1),
        ]

    def test_a_timezone_offset_moves_the_day_boundary(self):
        """At UTC+2, 23:00 UTC already belongs to the next local day."""
        late = datetime.datetime(2025, 1, 8, 23, 30, tzinfo=datetime.timezone.utc)
        self.insert([mcp_event(timestamp=late)])

        res = self.chart(granularity='days', timezone_offset_seconds=2 * 3600)

        # The bucket is local 2025-01-09 00:00, which is 2025-01-08 22:00 UTC.
        expected = datetime.datetime(2025, 1, 8, 22, 0, tzinfo=datetime.timezone.utc)
        assert self.buckets(res) == [(int(expected.timestamp()), 'files', 1)]

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

        res = self.chart(_from=BASE_TIME, _to=BASE_TIME + datetime.timedelta(hours=1))

        assert sum(p.value for p in res) == 2

    def test_a_single_route_narrows_the_chart(self):
        self.insert(
            [
                mcp_event(route_name='route-a'),
                mcp_event(route_name='route-b', mcp_alias='search'),
            ]
        )

        res = self.chart(route_names=['route-a'])

        assert self.buckets(res) == [(int(BASE_TIME.timestamp()), 'files', 1)]

    def test_multiple_routes_are_ored(self):
        self.insert(
            [
                mcp_event(route_name='route-a', mcp_alias='files'),
                mcp_event(route_name='route-b', mcp_alias='search'),
                mcp_event(route_name='route-c', mcp_alias='mail'),
            ]
        )

        res = self.chart(route_names=['route-a', 'route-b'])

        assert {p.group_by_value for p in res} == {'files', 'search'}

    def test_tag_values_of_the_same_key_are_ored(self):
        self.insert(
            [
                mcp_event(tags=['env=prod'], mcp_alias='files'),
                mcp_event(tags=['env=staging'], mcp_alias='search'),
                mcp_event(tags=['env=dev'], mcp_alias='mail'),
            ]
        )

        res = self.chart(tags=['env=prod', 'env=staging'])

        assert {p.group_by_value for p in res} == {'files', 'search'}

    def test_tags_of_different_keys_are_anded(self):
        self.insert(
            [
                mcp_event(tags=['env=prod', 'cost_center=retail'], mcp_alias='files'),
                mcp_event(tags=['env=prod'], mcp_alias='search'),
                mcp_event(tags=['cost_center=retail'], mcp_alias='mail'),
            ]
        )

        res = self.chart(tags=['env=prod', 'cost_center=retail'])

        assert self.buckets(res) == [(int(BASE_TIME.timestamp()), 'files', 1)]

    def test_all_filters_compose(self):
        in_window = BASE_TIME + datetime.timedelta(minutes=30)
        self.insert(
            [
                # The only row that survives every filter.
                mcp_event(
                    route_name='agents',
                    timestamp=in_window,
                    tags=['env=prod'],
                    mcp_alias='files',
                ),
                # Right route and tag, outside the window.
                mcp_event(
                    route_name='agents',
                    timestamp=BASE_TIME - datetime.timedelta(days=1),
                    tags=['env=prod'],
                    mcp_alias='search',
                ),
                # Right window and tag, wrong route.
                mcp_event(
                    route_name='chat',
                    timestamp=in_window,
                    tags=['env=prod'],
                    mcp_alias='mail',
                ),
                # Right route and window, wrong tag.
                mcp_event(
                    route_name='agents',
                    timestamp=in_window,
                    tags=['env=staging'],
                    mcp_alias='calendar',
                ),
                # Everything right, wrong project.
                mcp_event(
                    project_uuid=PROJECT_B,
                    route_name='agents',
                    timestamp=in_window,
                    tags=['env=prod'],
                    mcp_alias='docs',
                ),
            ]
        )

        res = self.chart(
            route_names=['agents'],
            _from=BASE_TIME,
            _to=BASE_TIME + datetime.timedelta(hours=1),
            tags=['env=prod'],
        )

        assert self.buckets(res) == [(int(BASE_TIME.timestamp()), 'files', 1)]

    def test_the_total_equals_the_key_table_total(self):
        """The chart sits above the key table (AG-955) and must agree with it."""
        self.insert(
            [
                mcp_event(api_key_uuid=KEY_1, mcp_alias='files'),
                mcp_event(api_key_uuid=KEY_1, mcp_alias=''),
                mcp_event(
                    api_key_uuid=KEY_2,
                    mcp_alias='search',
                    timestamp=BASE_TIME + datetime.timedelta(hours=3),
                ),
            ]
        )

        chart_total = sum(p.value for p in self.chart())
        table = self.event_dao.get_mcp_key_usage_paginated(
            project_uuid=PROJECT_A,
            route_names=None,
            _from=None,
            _to=None,
            params=Params(page=1, size=50),
            tags=None,
        )

        assert chart_total == sum(row.counter for row in table.items)
        assert chart_total == 3


class EventDAOMcpServerChartByEntityTest(DatabaseIntegrationClickhouse):
    """One entity's buckets, as the drill-down stream reads them."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.event_dao = EventDAO(cls.db)

    def chart(
        self,
        entity_column: str = 'MCP_ALIAS',
        entity_value: str = 'files',
        granularity: str = 'hours',
        route_names: list[str] | None = None,
        _from: datetime.datetime | None = None,
        _to: datetime.datetime | None = None,
        tags: list[str] | None = None,
        timezone_offset_seconds: int = 0,
        project_uuid: uuid.UUID = PROJECT_A,
        series_column: str | None = None,
    ):
        return self.event_dao.get_mcp_server_chart_data_by_entity(
            project_uuid=project_uuid,
            entity_column=entity_column,
            entity_value=entity_value,
            route_names=route_names,
            _from=_from,
            _to=_to,
            granularity=granularity,
            timezone_offset_seconds=timezone_offset_seconds,
            tags=tags,
            series_column=series_column,
        )

    def buckets(self, points) -> list[tuple[int, str, int]]:
        return [(p.timestamp, p.group_by_value, p.value) for p in points]

    def test_a_server_alias_is_one_series(self):
        self.insert(
            [
                mcp_event(mcp_alias='files'),
                mcp_event(mcp_alias='files'),
                mcp_event(mcp_alias='search'),
            ]
        )

        res = self.chart(entity_column='MCP_ALIAS', entity_value='files')

        assert self.buckets(res) == [(int(BASE_TIME.timestamp()), 'files', 2)]

    def test_a_group_is_one_series(self):
        self.insert(
            [
                mcp_event(group_uuid=GROUP_1),
                mcp_event(group_uuid=GROUP_1),
                mcp_event(group_uuid=GROUP_2),
            ]
        )

        res = self.chart(entity_column='GROUP_UUID', entity_value=str(GROUP_1))

        assert self.buckets(res) == [(int(BASE_TIME.timestamp()), str(GROUP_1), 2)]

    def test_a_key_is_one_series(self):
        self.insert(
            [
                mcp_event(api_key_uuid=KEY_1),
                mcp_event(api_key_uuid=KEY_2),
                mcp_event(api_key_uuid=KEY_2),
            ]
        )

        res = self.chart(entity_column='API_KEY_UUID', entity_value=str(KEY_2))

        assert self.buckets(res) == [(int(BASE_TIME.timestamp()), str(KEY_2), 2)]

    def test_an_unknown_alias_returns_no_points(self):
        self.insert([mcp_event(mcp_alias='files')])

        res = self.chart(entity_column='MCP_ALIAS', entity_value='nope')

        assert res == []

    def test_an_unknown_group_returns_no_points(self):
        self.insert([mcp_event(group_uuid=GROUP_1)])

        res = self.chart(entity_column='GROUP_UUID', entity_value=str(uuid.UUID(int=9)))

        assert res == []

    def test_an_unknown_key_returns_no_points(self):
        self.insert([mcp_event(api_key_uuid=KEY_1)])

        res = self.chart(
            entity_column='API_KEY_UUID', entity_value=str(uuid.UUID(int=9))
        )

        assert res == []

    def test_an_empty_window_returns_no_points(self):
        self.insert([mcp_event(timestamp=BASE_TIME)])

        res = self.chart(
            _from=BASE_TIME + datetime.timedelta(days=1),
            _to=BASE_TIME + datetime.timedelta(days=2),
        )

        assert res == []

    def test_counts_per_bucket(self):
        self.insert(
            [
                mcp_event(timestamp=BASE_TIME),
                mcp_event(timestamp=BASE_TIME + datetime.timedelta(minutes=30)),
                mcp_event(timestamp=BASE_TIME + datetime.timedelta(hours=2)),
            ]
        )

        res = self.chart()

        hour_0 = int(BASE_TIME.timestamp())
        hour_2 = int((BASE_TIME + datetime.timedelta(hours=2)).timestamp())
        # Hour 1 has no row. Filling the gap is the service's job.
        assert self.buckets(res) == [(hour_0, 'files', 2), (hour_2, 'files', 1)]

    def test_other_entities_are_not_counted(self):
        self.insert(
            [
                mcp_event(mcp_alias='files', api_key_uuid=KEY_1, group_uuid=GROUP_1),
                mcp_event(mcp_alias='search', api_key_uuid=KEY_1, group_uuid=GROUP_1),
                mcp_event(mcp_alias='files', api_key_uuid=KEY_2, group_uuid=GROUP_2),
            ]
        )

        by_alias = self.chart(entity_column='MCP_ALIAS', entity_value='files')
        by_key = self.chart(entity_column='API_KEY_UUID', entity_value=str(KEY_1))
        by_group = self.chart(entity_column='GROUP_UUID', entity_value=str(GROUP_2))

        assert [p.value for p in by_alias] == [2]
        assert [p.value for p in by_key] == [2]
        assert [p.value for p in by_group] == [1]

    def test_other_event_types_are_not_counted(self):
        self.insert(
            [
                mcp_event(),
                mcp_event(event_type='MODEL_INVOCATION'),
                mcp_event(event_type='REQUEST'),
                mcp_event(event_type='GUARDRAIL'),
            ]
        )

        res = self.chart()

        assert self.buckets(res) == [(int(BASE_TIME.timestamp()), 'files', 1)]

    def test_another_project_is_not_counted(self):
        self.insert(
            [
                mcp_event(),
                mcp_event(project_uuid=PROJECT_B),
            ]
        )

        res = self.chart()

        assert self.buckets(res) == [(int(BASE_TIME.timestamp()), 'files', 1)]

    def test_no_method_filter_narrows_the_count(self):
        """Membership comes from the event type alone, not from the method."""
        self.insert(
            [
                mcp_event(mcp_method='tools/call'),
                mcp_event(mcp_method='resources/read'),
                mcp_event(mcp_method='prompts/get'),
                mcp_event(mcp_method=''),
            ]
        )

        res = self.chart()

        assert self.buckets(res) == [(int(BASE_TIME.timestamp()), 'files', 4)]

    def test_daily_buckets(self):
        day_2 = BASE_TIME + datetime.timedelta(days=1)
        self.insert(
            [
                mcp_event(timestamp=BASE_TIME),
                mcp_event(timestamp=BASE_TIME + datetime.timedelta(hours=5)),
                mcp_event(timestamp=day_2),
            ]
        )

        res = self.chart(granularity='days')

        start_of_day_1 = BASE_TIME.replace(hour=0)
        assert self.buckets(res) == [
            (int(start_of_day_1.timestamp()), 'files', 2),
            (
                int((start_of_day_1 + datetime.timedelta(days=1)).timestamp()),
                'files',
                1,
            ),
        ]

    def test_weekly_buckets_start_on_monday(self):
        # 2025-01-08 is a Wednesday, so its week starts on 2025-01-06.
        self.insert(
            [
                mcp_event(timestamp=BASE_TIME),
                mcp_event(timestamp=BASE_TIME + datetime.timedelta(days=7)),
            ]
        )

        res = self.chart(granularity='weeks')

        monday = datetime.datetime(2025, 1, 6, tzinfo=datetime.timezone.utc)
        assert self.buckets(res) == [
            (int(monday.timestamp()), 'files', 1),
            (int((monday + datetime.timedelta(days=7)).timestamp()), 'files', 1),
        ]

    def test_monthly_buckets(self):
        self.insert(
            [
                mcp_event(timestamp=BASE_TIME),
                mcp_event(timestamp=BASE_TIME + datetime.timedelta(days=31)),
            ]
        )

        res = self.chart(granularity='months')

        january = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
        february = datetime.datetime(2025, 2, 1, tzinfo=datetime.timezone.utc)
        assert self.buckets(res) == [
            (int(january.timestamp()), 'files', 1),
            (int(february.timestamp()), 'files', 1),
        ]

    def test_a_timezone_offset_moves_the_day_boundary(self):
        """At UTC+2, 23:00 UTC already belongs to the next local day."""
        late = datetime.datetime(2025, 1, 8, 23, 30, tzinfo=datetime.timezone.utc)
        self.insert([mcp_event(timestamp=late)])

        res = self.chart(granularity='days', timezone_offset_seconds=2 * 3600)

        # The bucket is local 2025-01-09 00:00, which is 2025-01-08 22:00 UTC.
        expected = datetime.datetime(2025, 1, 8, 22, 0, tzinfo=datetime.timezone.utc)
        assert self.buckets(res) == [(int(expected.timestamp()), 'files', 1)]

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

        res = self.chart(_from=BASE_TIME, _to=BASE_TIME + datetime.timedelta(hours=1))

        assert sum(p.value for p in res) == 2

    def test_a_single_route_narrows_the_series(self):
        self.insert(
            [
                mcp_event(route_name='route-a'),
                mcp_event(route_name='route-b'),
            ]
        )

        res = self.chart(route_names=['route-a'])

        assert self.buckets(res) == [(int(BASE_TIME.timestamp()), 'files', 1)]

    def test_multiple_routes_are_ored(self):
        self.insert(
            [
                mcp_event(route_name='route-a'),
                mcp_event(route_name='route-b'),
                mcp_event(route_name='route-c'),
            ]
        )

        res = self.chart(route_names=['route-a', 'route-b'])

        assert self.buckets(res) == [(int(BASE_TIME.timestamp()), 'files', 2)]

    def test_tag_values_of_the_same_key_are_ored(self):
        self.insert(
            [
                mcp_event(tags=['env=prod']),
                mcp_event(tags=['env=staging']),
                mcp_event(tags=['env=dev']),
            ]
        )

        res = self.chart(tags=['env=prod', 'env=staging'])

        assert self.buckets(res) == [(int(BASE_TIME.timestamp()), 'files', 2)]

    def test_tags_of_different_keys_are_anded(self):
        self.insert(
            [
                mcp_event(tags=['env=prod', 'cost_center=retail']),
                mcp_event(tags=['env=prod']),
                mcp_event(tags=['cost_center=retail']),
            ]
        )

        res = self.chart(tags=['env=prod', 'cost_center=retail'])

        assert self.buckets(res) == [(int(BASE_TIME.timestamp()), 'files', 1)]

    def test_all_filters_compose(self):
        in_window = BASE_TIME + datetime.timedelta(minutes=30)
        self.insert(
            [
                # The only row that survives every filter.
                mcp_event(
                    api_key_uuid=KEY_1,
                    route_name='agents',
                    timestamp=in_window,
                    tags=['env=prod'],
                ),
                # Right route, tag and window, another key.
                mcp_event(
                    api_key_uuid=KEY_2,
                    route_name='agents',
                    timestamp=in_window,
                    tags=['env=prod'],
                ),
                # Right key, route and tag, outside the window.
                mcp_event(
                    api_key_uuid=KEY_1,
                    route_name='agents',
                    timestamp=BASE_TIME - datetime.timedelta(days=1),
                    tags=['env=prod'],
                ),
                # Right key, window and tag, wrong route.
                mcp_event(
                    api_key_uuid=KEY_1,
                    route_name='chat',
                    timestamp=in_window,
                    tags=['env=prod'],
                ),
                # Right key, route and window, wrong tag.
                mcp_event(
                    api_key_uuid=KEY_1,
                    route_name='agents',
                    timestamp=in_window,
                    tags=['env=staging'],
                ),
                # Everything right, wrong project.
                mcp_event(
                    project_uuid=PROJECT_B,
                    api_key_uuid=KEY_1,
                    route_name='agents',
                    timestamp=in_window,
                    tags=['env=prod'],
                ),
            ]
        )

        res = self.chart(
            entity_column='API_KEY_UUID',
            entity_value=str(KEY_1),
            route_names=['agents'],
            _from=BASE_TIME,
            _to=BASE_TIME + datetime.timedelta(hours=1),
            tags=['env=prod'],
        )

        assert self.buckets(res) == [(int(BASE_TIME.timestamp()), str(KEY_1), 1)]

    def test_the_series_agrees_with_the_grouped_chart(self):
        """Drilling into a bar must show the numbers the bar was drawn from."""
        self.insert(
            [
                mcp_event(mcp_alias='files', api_key_uuid=KEY_1, group_uuid=GROUP_1),
                mcp_event(
                    mcp_alias='files',
                    api_key_uuid=KEY_2,
                    group_uuid=GROUP_1,
                    timestamp=BASE_TIME + datetime.timedelta(hours=1),
                ),
                mcp_event(mcp_alias='search', api_key_uuid=KEY_2, group_uuid=GROUP_2),
                mcp_event(
                    mcp_alias='search',
                    api_key_uuid=KEY_1,
                    group_uuid=GROUP_2,
                    timestamp=BASE_TIME + datetime.timedelta(hours=3),
                ),
            ]
        )
        window = {
            '_from': BASE_TIME,
            '_to': BASE_TIME + datetime.timedelta(hours=4),
        }

        for group_by, entity_column, value in (
            ('services', 'MCP_ALIAS', 'files'),
            ('services', 'MCP_ALIAS', 'search'),
            ('groups', 'GROUP_UUID', str(GROUP_1)),
            ('groups', 'GROUP_UUID', str(GROUP_2)),
            ('keys', 'API_KEY_UUID', str(KEY_1)),
            ('keys', 'API_KEY_UUID', str(KEY_2)),
        ):
            grouped = self.event_dao.get_mcp_server_chart_data(
                project_uuid=PROJECT_A,
                route_names=None,
                granularity='hours',
                group_by=group_by,
                timezone_offset_seconds=0,
                tags=None,
                **window,
            )
            expected = [
                (p.timestamp, p.group_by_value, p.value)
                for p in grouped
                if p.group_by_value == value
            ]

            drilled = self.chart(
                entity_column=entity_column, entity_value=value, **window
            )

            assert self.buckets(drilled) == expected, value
            assert sum(p.value for p in drilled) > 0, value

    def test_a_server_alias_splits_into_one_series_per_target(self):
        """Drilling into a server shows its tools, prompts and resources."""
        self.insert(
            [
                mcp_event(mcp_alias='files', mcp_target='read_file'),
                mcp_event(mcp_alias='files', mcp_target='read_file'),
                mcp_event(mcp_alias='files', mcp_target='write_file'),
                mcp_event(
                    mcp_alias='files',
                    mcp_method='prompts/get',
                    mcp_target='summarize',
                ),
                # Another server's tool, even with the same name.
                mcp_event(mcp_alias='search', mcp_target='read_file'),
            ]
        )

        res = self.chart(
            entity_column='MCP_ALIAS',
            entity_value='files',
            series_column='MCP_TARGET',
        )

        t = int(BASE_TIME.timestamp())
        assert self.buckets(res) == [
            (t, 'read_file', 2),
            (t, 'summarize', 1),
            (t, 'write_file', 1),
        ]

    def test_an_invocation_without_a_target_is_its_own_series(self):
        """Rows written before the target existed still count, under ''."""
        self.insert(
            [
                mcp_event(mcp_alias='files', mcp_target=''),
                mcp_event(mcp_alias='files', mcp_target='read_file'),
            ]
        )

        res = self.chart(
            entity_column='MCP_ALIAS',
            entity_value='files',
            series_column='MCP_TARGET',
        )

        t = int(BASE_TIME.timestamp())
        assert self.buckets(res) == [(t, '', 1), (t, 'read_file', 1)]

    def test_target_series_sum_to_the_server_bar(self):
        """Every tool series added up must be the alias bar in the grouped chart."""
        self.insert(
            [
                mcp_event(mcp_alias='files', mcp_target='read_file'),
                mcp_event(mcp_alias='files', mcp_target='write_file'),
                mcp_event(
                    mcp_alias='files',
                    mcp_target='read_file',
                    timestamp=BASE_TIME + datetime.timedelta(hours=1),
                ),
                mcp_event(mcp_alias='search', mcp_target='query'),
            ]
        )

        grouped = self.event_dao.get_mcp_server_chart_data(
            project_uuid=PROJECT_A,
            route_names=None,
            _from=None,
            _to=None,
            granularity='hours',
            group_by='services',
            timezone_offset_seconds=0,
            tags=None,
        )
        drilled = self.chart(
            entity_column='MCP_ALIAS',
            entity_value='files',
            series_column='MCP_TARGET',
        )

        per_bucket_bar = {
            p.timestamp: p.value for p in grouped if p.group_by_value == 'files'
        }
        per_bucket_tools: dict[int, int] = {}
        for p in drilled:
            per_bucket_tools[p.timestamp] = (
                per_bucket_tools.get(p.timestamp, 0) + p.value
            )

        assert per_bucket_tools == per_bucket_bar
        assert sum(per_bucket_bar.values()) == 3
