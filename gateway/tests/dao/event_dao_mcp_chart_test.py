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


def ts(moment: datetime.datetime) -> int:
    return int(moment.timestamp())


def buckets(points) -> list[tuple[int, str, int]]:
    return [(p.timestamp, p.group_by_value, p.value) for p in points]


H0 = ts(BASE_TIME)
H1 = ts(BASE_TIME + datetime.timedelta(hours=1))
H3 = ts(BASE_TIME + datetime.timedelta(hours=3))


class EventDAOMcpServerChartTest(DatabaseIntegrationClickhouse):
    """The grouped chart and the drill-down stream into one entity.

    Every case asserts on the buckets an operator would see, and every
    drill-down is checked against the bar of the grouped chart it opens from.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.event_dao = EventDAO(cls.db)

    def grouped(
        self,
        group_by: str = 'services',
        granularity: str = 'hours',
        route_names: list[str] | None = None,
        _from: datetime.datetime | None = None,
        _to: datetime.datetime | None = None,
        tags: list[str] | None = None,
        timezone_offset_seconds: int = 0,
    ) -> list[tuple[int, str, int]]:
        return buckets(
            self.event_dao.get_mcp_server_chart_data(
                project_uuid=PROJECT_A,
                route_names=route_names,
                _from=_from,
                _to=_to,
                granularity=granularity,
                group_by=group_by,
                timezone_offset_seconds=timezone_offset_seconds,
                tags=tags,
            )
        )

    def drilled(
        self,
        entity_column: str = 'MCP_ALIAS',
        entity_value: str = 'files',
        granularity: str = 'hours',
        route_names: list[str] | None = None,
        _from: datetime.datetime | None = None,
        _to: datetime.datetime | None = None,
        tags: list[str] | None = None,
        timezone_offset_seconds: int = 0,
        series_column: str | None = None,
    ) -> list[tuple[int, str, int]]:
        return buckets(
            self.event_dao.get_mcp_server_chart_data_by_entity(
                project_uuid=PROJECT_A,
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
        )

    def test_each_filter_narrows_the_buckets_of_both_charts(self):
        """Routes and values of one tag key are ORed, different tag keys are
        ANDed, the window is inclusive, and the method never narrows: only
        the event type and the project decide what counts. The chart total
        always matches the key table under the same filters.
        """
        before = BASE_TIME - datetime.timedelta(minutes=1)
        end = BASE_TIME + datetime.timedelta(hours=1)
        after = end + datetime.timedelta(minutes=1)
        self.insert(
            [
                mcp_event(tags=['env=prod', 'cost_center=retail']),
                mcp_event(
                    route_name='route-b',
                    timestamp=BASE_TIME + datetime.timedelta(minutes=30),
                    tags=['env=staging'],
                    mcp_method='resources/read',
                ),
                mcp_event(
                    mcp_alias='search',
                    timestamp=end,
                    tags=['env=prod'],
                    mcp_method='prompts/get',
                ),
                mcp_event(
                    route_name='route-c',
                    timestamp=before,
                    tags=['env=dev'],
                    mcp_method='',
                ),
                mcp_event(
                    mcp_alias='mail',
                    route_name='route-c',
                    timestamp=after,
                    tags=['cost_center=retail'],
                ),
                # An unresolved alias is a series of its own.
                mcp_event(mcp_alias=''),
                *(
                    mcp_event(event_type=event_type)
                    for event_type in ('MODEL_INVOCATION', 'REQUEST', 'GUARDRAIL')
                ),
                mcp_event(project_uuid=PROJECT_B),
            ]
        )
        h_before = ts(BASE_TIME - datetime.timedelta(hours=1))

        for filters, expected in (
            (
                {},
                [
                    (h_before, 'files', 1),
                    (H0, '', 1),
                    (H0, 'files', 2),
                    (H1, 'mail', 1),
                    (H1, 'search', 1),
                ],
            ),
            (
                {'_from': BASE_TIME, '_to': end},
                [(H0, '', 1), (H0, 'files', 2), (H1, 'search', 1)],
            ),
            (
                {
                    '_from': BASE_TIME + datetime.timedelta(days=1),
                    '_to': BASE_TIME + datetime.timedelta(days=2),
                },
                [],
            ),
            (
                {'route_names': ['route-a']},
                [(H0, '', 1), (H0, 'files', 1), (H1, 'search', 1)],
            ),
            (
                {'route_names': ['route-b', 'route-c']},
                [(h_before, 'files', 1), (H0, 'files', 1), (H1, 'mail', 1)],
            ),
            (
                {'tags': ['env=prod', 'env=staging']},
                [(H0, 'files', 2), (H1, 'search', 1)],
            ),
            ({'tags': ['env=prod', 'cost_center=retail']}, [(H0, 'files', 1)]),
        ):
            with self.subTest(**filters):
                table = self.event_dao.get_mcp_key_usage_paginated(
                    project_uuid=PROJECT_A,
                    params=Params(page=1, size=50),
                    **{'route_names': None, '_from': None, '_to': None, 'tags': None}
                    | filters,
                )

                assert self.grouped(**filters) == expected
                assert self.drilled(**filters) == [
                    b for b in expected if b[1] == 'files'
                ]
                assert sum(row.counter for row in table.items) == sum(
                    b[2] for b in expected
                )

    def test_every_granularity_buckets_both_charts_on_local_time(self):
        """Weeks start on Monday. At UTC+2, 23:30 UTC already belongs to the
        next local day, whose bucket starts at 22:00 UTC.
        """
        day = datetime.timedelta(days=1)
        self.insert(
            [
                mcp_event(timestamp=moment)
                for moment in (
                    BASE_TIME,  # Wednesday 2025-01-08 10:00
                    BASE_TIME + datetime.timedelta(hours=5),
                    BASE_TIME.replace(hour=23, minute=30),
                    BASE_TIME + day,
                    BASE_TIME + 7 * day,
                    BASE_TIME + 31 * day,
                )
            ]
        )

        def utc(month, day_, hour=0):
            return ts(datetime.datetime(2025, month, day_, hour, tzinfo=datetime.UTC))

        for granularity, offset, expected in (
            (
                'days',
                0,
                [(utc(1, 8), 3), (utc(1, 9), 1), (utc(1, 15), 1), (utc(2, 8), 1)],
            ),
            (
                'days',
                2 * 3600,
                [
                    (utc(1, 7, 22), 2),
                    (utc(1, 8, 22), 2),
                    (utc(1, 14, 22), 1),
                    (utc(2, 7, 22), 1),
                ],
            ),
            ('weeks', 0, [(utc(1, 6), 4), (utc(1, 13), 1), (utc(2, 3), 1)]),
            ('months', 0, [(utc(1, 1), 5), (utc(2, 1), 1)]),
        ):
            with self.subTest(granularity=granularity, offset=offset):
                query = {
                    'granularity': granularity,
                    'timezone_offset_seconds': offset,
                }
                points = [(bucket, 'files', count) for bucket, count in expected]

                assert self.grouped(**query) == points
                assert self.drilled(**query) == points

    def test_a_group_or_key_drills_into_its_own_bar(self):
        """Drilling into a bar shows the numbers the bar was drawn from, and
        an entity with no rows is an empty stream.
        """
        self.insert(
            [
                mcp_event(api_key_uuid=KEY_1, group_uuid=GROUP_1),
                mcp_event(api_key_uuid=KEY_1, group_uuid=GROUP_1),
                mcp_event(
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
        g1, g2, k1, k2 = str(GROUP_1), str(GROUP_2), str(KEY_1), str(KEY_2)
        unknown = str(uuid.UUID(int=9))

        for group_by, column, expected, values in (
            (
                'services',
                'MCP_ALIAS',
                [
                    (H0, 'files', 2),
                    (H0, 'search', 1),
                    (H1, 'files', 1),
                    (H3, 'search', 1),
                ],
                ['files', 'search', 'nope'],
            ),
            (
                'groups',
                'GROUP_UUID',
                [(H0, g1, 2), (H0, g2, 1), (H1, g1, 1), (H3, g2, 1)],
                [g1, g2, unknown],
            ),
            (
                'keys',
                'API_KEY_UUID',
                [(H0, k1, 2), (H0, k2, 1), (H1, k2, 1), (H3, k1, 1)],
                [k1, k2, unknown],
            ),
        ):
            with self.subTest(group_by=group_by):
                assert self.grouped(group_by=group_by) == expected
                for value in values:
                    assert self.drilled(entity_column=column, entity_value=value) == [
                        b for b in expected if b[1] == value
                    ], value

    def test_all_filters_compose(self):
        in_window = BASE_TIME + datetime.timedelta(minutes=30)
        self.insert(
            [
                # The only rows that survive every filter: one per key.
                mcp_event(
                    api_key_uuid=KEY_1,
                    route_name='agents',
                    timestamp=in_window,
                    tags=['env=prod'],
                ),
                mcp_event(
                    api_key_uuid=KEY_2,
                    route_name='agents',
                    timestamp=in_window,
                    tags=['env=prod'],
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
        filters = {
            'route_names': ['agents'],
            '_from': BASE_TIME,
            '_to': BASE_TIME + datetime.timedelta(hours=1),
            'tags': ['env=prod'],
        }

        assert self.grouped(**filters) == [(H0, 'files', 2)]
        assert self.drilled(
            entity_column='API_KEY_UUID', entity_value=str(KEY_1), **filters
        ) == [(H0, str(KEY_1), 1)]

    def test_a_server_alias_splits_into_one_series_per_target(self):
        """Drilling into a server shows its tools, prompts and resources, and
        the target series add up to the server bar. Rows written before the
        target existed still count, under ''.
        """
        self.insert(
            [
                mcp_event(mcp_target='read_file'),
                mcp_event(mcp_target='read_file'),
                mcp_event(mcp_target='write_file'),
                mcp_event(mcp_method='prompts/get', mcp_target='summarize'),
                mcp_event(mcp_target=''),
                mcp_event(
                    mcp_target='read_file',
                    timestamp=BASE_TIME + datetime.timedelta(hours=1),
                ),
                # Another server's tool, even with the same name.
                mcp_event(mcp_alias='search', mcp_target='read_file'),
            ]
        )

        drilled = self.drilled(series_column='MCP_TARGET')

        assert drilled == [
            (H0, '', 1),
            (H0, 'read_file', 2),
            (H0, 'summarize', 1),
            (H0, 'write_file', 1),
            (H1, 'read_file', 1),
        ]
        assert self.grouped() == [(H0, 'files', 5), (H0, 'search', 1), (H1, 'files', 1)]
