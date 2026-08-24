"""The TAGS storage format, exercised against a real ClickHouse.

Tags are stored as canonical ``key=value`` entries in a flat ``Array(String)``.
These tests pin the two queries that format exists to serve: filtering events by
one or more tags, and listing the tags available in a project.
"""

import datetime
import uuid

from sqlalchemy import distinct, func, select

from tests.common import db_mock
from tests.common.db_integration_ch import DatabaseIntegrationClickhouse

from radicalbit_ai_gateway.db.tables.request_event_table import RequestEvent

PROJECT_A = uuid.UUID('11111111-1111-1111-1111-111111111111')
PROJECT_B = uuid.UUID('22222222-2222-2222-2222-222222222222')
TIMESTAMP = datetime.datetime(2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc)


class RequestEventTagsTest(DatabaseIntegrationClickhouse):
    T = RequestEvent.__table__

    def _seed(self):
        self.insert(
            [
                db_mock.get_sample_request_event(
                    timestamp=TIMESTAMP,
                    project_uuid=PROJECT_A,
                    tags=['app=leonardo-clm', 'cost_center=retail', 'env=prod'],
                ),
                db_mock.get_sample_request_event(
                    timestamp=TIMESTAMP,
                    project_uuid=PROJECT_A,
                    tags=['cost_center=retail', 'env=staging'],
                ),
                db_mock.get_sample_request_event(
                    timestamp=TIMESTAMP,
                    project_uuid=PROJECT_A,
                    tags=['env=prod'],
                ),
                db_mock.get_sample_request_event(
                    timestamp=TIMESTAMP,
                    project_uuid=PROJECT_A,
                    tags=[],
                ),
                db_mock.get_sample_request_event(
                    timestamp=TIMESTAMP,
                    project_uuid=PROJECT_B,
                    tags=['env=prod', 'team=platform'],
                ),
            ]
        )

    def _count_where(self, condition):
        stmt = (
            select(func.count())
            .select_from(RequestEvent)
            .where(self.T.c['PROJECT_UUID'] == str(PROJECT_A), condition)
        )
        with self.db.begin_session() as session:
            return session.execute(stmt).scalar()

    def test_tags_round_trip(self):
        self._seed()
        stmt = (
            select(self.T.c['TAGS'])
            .select_from(RequestEvent)
            .where(func.has(self.T.c['TAGS'], 'app=leonardo-clm'))
        )
        with self.db.begin_session() as session:
            rows = session.execute(stmt).fetchall()
        assert len(rows) == 1
        assert list(rows[0][0]) == [
            'app=leonardo-clm',
            'cost_center=retail',
            'env=prod',
        ]

    def test_filter_by_a_single_tag(self):
        self._seed()
        assert self._count_where(func.has(self.T.c['TAGS'], 'env=prod')) == 2

    def test_filter_by_multiple_tags_is_an_intersection(self):
        self._seed()
        condition = func.hasAll(self.T.c['TAGS'], ['cost_center=retail', 'env=prod'])
        assert self._count_where(condition) == 1

    def test_filter_by_any_of_several_tags(self):
        self._seed()
        condition = func.hasAny(self.T.c['TAGS'], ['env=staging', 'app=leonardo-clm'])
        assert self._count_where(condition) == 2

    def test_a_tag_matches_only_on_the_full_key_and_value(self):
        """'env=prod' must not match 'env=production'."""
        self.insert(
            [
                db_mock.get_sample_request_event(
                    timestamp=TIMESTAMP,
                    project_uuid=PROJECT_A,
                    tags=['env=production'],
                )
            ]
        )
        assert self._count_where(func.has(self.T.c['TAGS'], 'env=prod')) == 0

    def test_untagged_rows_never_match_a_filter(self):
        self._seed()
        condition = func.hasAny(
            self.T.c['TAGS'], ['env=prod', 'env=staging', 'app=leonardo-clm']
        )
        assert self._count_where(condition) == 3

    def test_list_all_tags_available_in_a_project(self):
        self._seed()
        tag = func.arrayJoin(self.T.c['TAGS'])
        stmt = (
            select(distinct(tag))
            .select_from(RequestEvent)
            .where(self.T.c['PROJECT_UUID'] == str(PROJECT_A))
        )
        with self.db.begin_session() as session:
            tags = sorted(row[0] for row in session.execute(stmt).fetchall())

        assert tags == [
            'app=leonardo-clm',
            'cost_center=retail',
            'env=prod',
            'env=staging',
        ]

    def test_listing_tags_is_scoped_to_one_project(self):
        self._seed()
        tag = func.arrayJoin(self.T.c['TAGS'])
        stmt = (
            select(distinct(tag))
            .select_from(RequestEvent)
            .where(self.T.c['PROJECT_UUID'] == str(PROJECT_B))
        )
        with self.db.begin_session() as session:
            tags = sorted(row[0] for row in session.execute(stmt).fetchall())
        assert tags == ['env=prod', 'team=platform']
