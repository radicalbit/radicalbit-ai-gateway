"""The TAGS storage format, exercised against a real ClickHouse.

Tags are stored as canonical ``key=value`` entries in a flat ``Array(String)``.
These tests pin the two queries that format exists to serve: filtering events by
one or more tags, and listing the tags available in a project.

The tests only read, so the data set is seeded once for the class.
"""

import datetime
import uuid

from sqlalchemy import distinct, func, select

from tests.common import db_mock
from tests.common.db_integration_ch import DatabaseIntegrationClickhouse

from radicalbit_ai_gateway.db.dao.request_event_dao import RequestEventDAO
from radicalbit_ai_gateway.db.tables.request_event_table import RequestEvent

PROJECT_A = uuid.UUID('11111111-1111-1111-1111-111111111111')
PROJECT_B = uuid.UUID('22222222-2222-2222-2222-222222222222')
# Near-miss tags only: 'env=production' and 'environment=prod' must not be
# mistaken for 'env=prod' or for a value of key 'env'.
PROJECT_C = uuid.UUID('33333333-3333-3333-3333-333333333333')
PROJECT_EMPTY = uuid.UUID('44444444-4444-4444-4444-444444444444')
TIMESTAMP = datetime.datetime(2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc)

SEED = [
    (PROJECT_A, ['app=my-app', 'cost_center=retail', 'env=prod']),
    (PROJECT_A, ['cost_center=retail', 'env=staging']),
    (PROJECT_A, ['env=prod']),
    (PROJECT_A, []),
    (PROJECT_B, ['env=prod', 'team=platform']),
    (PROJECT_C, ['env=production']),
    (PROJECT_C, ['environment=prod']),
]


class RequestEventTagsTest(DatabaseIntegrationClickhouse):
    T = RequestEvent.__table__

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        DatabaseIntegrationClickhouse.clean(cls)
        DatabaseIntegrationClickhouse.insert(
            cls,
            [
                db_mock.get_sample_request_event(
                    timestamp=TIMESTAMP, project_uuid=project, tags=tags
                )
                for project, tags in SEED
            ],
        )

    def tearDown(self) -> None:
        pass  # read-only tests share the class seed

    @classmethod
    def tearDownClass(cls):
        DatabaseIntegrationClickhouse.clean(cls)
        super().tearDownClass()

    @property
    def dao(self) -> RequestEventDAO:
        return RequestEventDAO(self.db)

    def _count_where(self, project, condition):
        stmt = (
            select(func.count())
            .select_from(RequestEvent)
            .where(self.T.c['PROJECT_UUID'] == str(project), condition)
        )
        with self.db.begin_session() as session:
            return session.execute(stmt).scalar()

    def _raw_distinct_tags(self, project):
        stmt = (
            select(distinct(func.arrayJoin(self.T.c['TAGS'])))
            .select_from(RequestEvent)
            .where(self.T.c['PROJECT_UUID'] == str(project))
        )
        with self.db.begin_session() as session:
            return sorted(row[0] for row in session.execute(stmt).fetchall())

    def test_raw_tag_queries(self):
        tags = self.T.c['TAGS']
        stmt = (
            select(tags).select_from(RequestEvent).where(func.has(tags, 'app=my-app'))
        )
        with self.db.begin_session() as session:
            rows = session.execute(stmt).fetchall()
        assert [list(row[0]) for row in rows] == [
            ['app=my-app', 'cost_center=retail', 'env=prod']
        ]

        assert {
            'single': self._count_where(PROJECT_A, func.has(tags, 'env=prod')),
            # hasAll is an intersection.
            'all_of': self._count_where(
                PROJECT_A, func.hasAll(tags, ['cost_center=retail', 'env=prod'])
            ),
            'any_of': self._count_where(
                PROJECT_A, func.hasAny(tags, ['env=staging', 'app=my-app'])
            ),
            # The untagged row never matches, even the widest filter.
            'any_of_every_tag': self._count_where(
                PROJECT_A,
                func.hasAny(tags, ['env=prod', 'env=staging', 'app=my-app']),
            ),
            # 'env=prod' matches only the full key and value.
            'near_miss': self._count_where(PROJECT_C, func.has(tags, 'env=prod')),
        } == {
            'single': 2,
            'all_of': 1,
            'any_of': 2,
            'any_of_every_tag': 3,
            'near_miss': 0,
        }

        assert {p: self._raw_distinct_tags(p) for p in (PROJECT_A, PROJECT_B)} == {
            PROJECT_A: ['app=my-app', 'cost_center=retail', 'env=prod', 'env=staging'],
            PROJECT_B: ['env=prod', 'team=platform'],
        }

    def test_dao_distinct_tags_and_values(self):
        assert {
            p: self.dao.get_distinct_tags(p)
            for p in (PROJECT_A, PROJECT_B, PROJECT_EMPTY)
        } == {
            PROJECT_A: ['app=my-app', 'cost_center=retail', 'env=prod', 'env=staging'],
            PROJECT_B: ['env=prod', 'team=platform'],
            PROJECT_EMPTY: [],
        }
        assert {
            (p, key): self.dao.get_distinct_tag_values(p, key)
            for p, key in (
                (PROJECT_A, 'env'),
                (PROJECT_B, 'env'),
                (PROJECT_A, 'unknown'),
                # 'environment=prod' is not a value of key 'env'.
                (PROJECT_C, 'env'),
            )
        } == {
            (PROJECT_A, 'env'): ['prod', 'staging'],
            (PROJECT_B, 'env'): ['prod'],
            (PROJECT_A, 'unknown'): [],
            (PROJECT_C, 'env'): ['production'],
        }

    def test_dao_filters_by_tags_with_or_within_key_and_and_across_keys(self):
        """The `tags` param reaches the real query through a public DAO method."""

        def total(tags):
            return self.dao.get_request_stats_global(
                PROJECT_A, _from=None, _to=None, tags=tags
            ).total_requests

        assert {
            'or_within_key': total(['env=prod', 'env=staging']),
            'and_across_keys': total(['env=prod', 'cost_center=retail']),
            'no_match': total(['env=unknown']),
        } == {'or_within_key': 3, 'and_across_keys': 1, 'no_match': 0}
