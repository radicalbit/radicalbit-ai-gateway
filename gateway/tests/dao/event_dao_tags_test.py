"""Tag filtering on the `event` table, exercised against a real ClickHouse.

Mirrors the storage/query pinning of `tests/dao/request_event_tags_test.py` but
exercises `EventDAO._add_tags_filter`'s Google-style facet semantics: OR
between multiple values of the same tag key, AND between different keys.
"""

import datetime
import uuid

from sqlalchemy import func, select

from tests.common import db_mock
from tests.common.db_integration_ch import DatabaseIntegrationClickhouse

from radicalbit_ai_gateway.db.dao.event_dao import EventDAO
from radicalbit_ai_gateway.db.tables.event_table import Event

PROJECT_A = uuid.UUID('11111111-1111-1111-1111-111111111111')
TIMESTAMP = datetime.datetime(2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc)


class EventDAOTagsTest(DatabaseIntegrationClickhouse):
    T = Event.__table__

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.event_dao = EventDAO(cls.db)

    def _seed(self):
        self.insert(
            [
                db_mock.get_sample_event(
                    event_type='MODEL_INVOCATION',
                    project_uuid=PROJECT_A,
                    timestamp=TIMESTAMP,
                    tags=['env=prod', 'cost_center=retail'],
                ),
                db_mock.get_sample_event(
                    event_type='MODEL_INVOCATION',
                    project_uuid=PROJECT_A,
                    timestamp=TIMESTAMP,
                    tags=['env=staging', 'cost_center=retail'],
                ),
                db_mock.get_sample_event(
                    event_type='MODEL_INVOCATION',
                    project_uuid=PROJECT_A,
                    timestamp=TIMESTAMP,
                    tags=['env=prod'],
                ),
                db_mock.get_sample_event(
                    event_type='MODEL_INVOCATION',
                    project_uuid=PROJECT_A,
                    timestamp=TIMESTAMP,
                    tags=[],
                ),
            ]
        )

    def _count_with_tags(self, tags: list[str] | None) -> int:
        conditions = [
            self.T.c['EVENT_TYPE'] == 'MODEL_INVOCATION',
            self.T.c['PROJECT_UUID'] == str(PROJECT_A),
        ]
        self.event_dao._add_tags_filter(conditions, tags)
        stmt = select(func.count()).select_from(Event).where(*conditions)
        with self.db.begin_session() as session:
            return session.execute(stmt).scalar()

    def test_no_tags_matches_everything(self):
        self._seed()
        assert self._count_with_tags(None) == 4

    def test_filter_by_a_single_tag(self):
        self._seed()
        assert self._count_with_tags(['env=prod']) == 2

    def test_values_of_the_same_key_are_ored(self):
        self._seed()
        assert self._count_with_tags(['env=prod', 'env=staging']) == 3

    def test_different_keys_are_anded(self):
        self._seed()
        assert self._count_with_tags(['env=prod', 'cost_center=retail']) == 1

    def test_no_match_returns_zero(self):
        self._seed()
        assert self._count_with_tags(['env=unknown']) == 0

    def test_end_to_end_via_get_all_routes_summary_costs(self):
        """The tags param reaches the real query through a public DAO method."""
        self.insert(
            [
                db_mock.get_sample_event(
                    event_type='INPUT_TOKEN_PROCESSED',
                    route_name='route-a',
                    project_uuid=PROJECT_A,
                    timestamp=TIMESTAMP,
                    cost=1.0,
                    tags=['env=prod'],
                ),
                db_mock.get_sample_event(
                    event_type='INPUT_TOKEN_PROCESSED',
                    route_name='route-a',
                    project_uuid=PROJECT_A,
                    timestamp=TIMESTAMP,
                    cost=2.0,
                    tags=['env=staging'],
                ),
            ]
        )
        results = self.event_dao.get_all_routes_summary_costs(
            PROJECT_A, _from=None, _to=None, _with_saved_tokens=False, tags=['env=prod']
        )
        assert len(results) == 1
        assert results[0].route_name == 'route-a'
        assert float(results[0].input_cost) == 1.0
