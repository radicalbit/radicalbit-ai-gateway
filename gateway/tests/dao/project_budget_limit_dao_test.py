import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from tests.common import db_mock
from tests.common.db_integration import DatabaseIntegration

from radicalbit_ai_gateway.db.dao.project_budget_limit_dao import ProjectBudgetLimitDAO
from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO
from radicalbit_ai_gateway.db.tables.project_table import Project


class ProjectBudgetLimitDAOTest(DatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project_dao = ProjectDAO(cls.db)
        cls.project_budget_limit_dao = ProjectBudgetLimitDAO(cls.db)

    def _insert_project(self, name='rb-project'):
        project = db_mock.get_sample_project(uuid=uuid.uuid4(), name=name)
        return self.project_dao.insert(project)

    def test_insert(self):
        project = self._insert_project()
        limit = db_mock.get_sample_project_budget_limit(project_uuid=project.uuid)
        inserted = self.project_budget_limit_dao.insert(limit)
        assert inserted.uuid == limit.uuid

    def test_get_by_uuid(self):
        project = self._insert_project()
        limit = db_mock.get_sample_project_budget_limit(
            uuid=uuid.uuid4(), project_uuid=project.uuid
        )
        self.project_budget_limit_dao.insert(limit)
        res = self.project_budget_limit_dao.get_by_uuid(limit.uuid)
        assert res.uuid == limit.uuid

    def test_get_by_project_uuid(self):
        project = self._insert_project()
        limits = [
            db_mock.get_sample_project_budget_limit(
                uuid=uuid.uuid4(), project_uuid=project.uuid, window_size='1 day'
            ),
            db_mock.get_sample_project_budget_limit(
                uuid=uuid.uuid4(), project_uuid=project.uuid, window_size='1 month'
            ),
        ]
        _ = [self.project_budget_limit_dao.insert(limit) for limit in limits]
        res = self.project_budget_limit_dao.get_by_project_uuid(project.uuid)
        assert len(res) == 2

    def test_duplicate_window_raises_integrity_error(self):
        project = self._insert_project()
        limit_one = db_mock.get_sample_project_budget_limit(
            uuid=uuid.uuid4(), project_uuid=project.uuid
        )
        limit_two = db_mock.get_sample_project_budget_limit(
            uuid=uuid.uuid4(), project_uuid=project.uuid
        )
        self.project_budget_limit_dao.insert(limit_one)
        pytest.raises(IntegrityError, self.project_budget_limit_dao.insert, limit_two)

    def test_insert_many(self):
        project = self._insert_project()
        limits = [
            db_mock.get_sample_project_budget_limit(
                uuid=uuid.uuid4(), project_uuid=project.uuid, window_size='1 day'
            ),
            db_mock.get_sample_project_budget_limit(
                uuid=uuid.uuid4(), project_uuid=project.uuid, window_size='1 month'
            ),
        ]
        inserted = self.project_budget_limit_dao.insert_many(limits)
        assert len(inserted) == 2
        assert len(self.project_budget_limit_dao.get_by_project_uuid(project.uuid)) == 2

    def test_insert_many_is_atomic_on_conflict(self):
        project = self._insert_project()
        limits = [
            db_mock.get_sample_project_budget_limit(
                uuid=uuid.uuid4(), project_uuid=project.uuid, window_size='1 day'
            ),
            # Duplicates the first one: same window.
            db_mock.get_sample_project_budget_limit(
                uuid=uuid.uuid4(), project_uuid=project.uuid, window_size='1 day'
            ),
        ]
        pytest.raises(IntegrityError, self.project_budget_limit_dao.insert_many, limits)
        # Neither row should have been committed.
        assert self.project_budget_limit_dao.get_by_project_uuid(project.uuid) == []

    def test_cascade_delete_on_project_delete(self):
        project = self._insert_project()
        self.project_budget_limit_dao.insert(
            db_mock.get_sample_project_budget_limit(
                uuid=uuid.uuid4(), project_uuid=project.uuid
            )
        )
        # ProjectDAO only exposes a soft delete; exercise the FK's
        # `ondelete='CASCADE'` directly with a hard delete of the row.
        with self.project_budget_limit_dao.db.begin_session() as session:
            session.execute(delete(Project).where(Project.uuid == project.uuid))
        assert self.project_budget_limit_dao.get_by_project_uuid(project.uuid) == []
