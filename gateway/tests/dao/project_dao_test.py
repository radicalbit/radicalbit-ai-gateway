import datetime
import uuid

from sqlalchemy import update

from tests.common import db_mock
from tests.common.db_integration import DatabaseIntegration

from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO
from radicalbit_ai_gateway.db.tables.project_table import Project
from radicalbit_ai_gateway.models.config_status import ConfigStatus
from radicalbit_ai_gateway.models.project_dto import ProjectFilter


class ProjectDAOTest(DatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project_dao = ProjectDAO(cls.db)

    def _insert_served_project(self, name: str) -> Project:
        """Insert a project plus a SERVED config and wire served_config_uuid."""
        project = db_mock.get_sample_project(uuid=uuid.uuid4(), name=name)
        self.project_dao.insert(project)
        config = db_mock.get_sample_project_config(
            project_uuid=project.uuid,
            config_file='served-yaml',
            config_status=ConfigStatus.SERVED,
        )
        self.insert(config)
        with self.db.begin_session() as session:
            session.execute(
                update(Project)
                .where(Project.uuid == project.uuid)
                .values(served_config_uuid=config.uuid)
            )
        return self.project_dao.get_by_uuid(project.uuid)

    def test_insert(self):
        project = db_mock.get_sample_project()
        inserted = self.project_dao.insert(project)
        assert inserted.uuid == project.uuid
        assert inserted.name == project.name

    def test_get_by_uuid(self):
        project = db_mock.get_sample_project()
        self.project_dao.insert(project)
        result = self.project_dao.get_by_uuid(project.uuid)
        assert result is not None
        assert result.uuid == project.uuid

    def test_get_by_uuid_not_found(self):
        assert self.project_dao.get_by_uuid(uuid.uuid4()) is None

    def test_get_all(self):
        for n in ('one', 'two', 'three'):
            self.project_dao.insert(
                db_mock.get_sample_project(uuid=uuid.uuid4(), name=n)
            )
        assert len(self.project_dao.get_all()) == 3

    def test_get_all_empty(self):
        assert list(self.project_dao.get_all()) == []

    def test_get_all_with_config_only_returns_served(self):
        self._insert_served_project('active')
        self.project_dao.insert(
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='inactive')
        )
        result = self.project_dao.get_all_with_config()
        assert len(result) == 1
        assert result[0].name == 'active'

    def test_get_all_with_config_empty(self):
        self.project_dao.insert(
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='no-config')
        )
        assert list(self.project_dao.get_all_with_config()) == []

    def test_get_all_filtered_no_filter_returns_all(self):
        self._insert_served_project('a')
        self.project_dao.insert(db_mock.get_sample_project(uuid=uuid.uuid4(), name='b'))
        assert len(self.project_dao.get_all_filtered(None)) == 2

    def test_get_all_filtered_active_returns_only_served(self):
        self._insert_served_project('served')
        self.project_dao.insert(
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='not-served')
        )
        result = self.project_dao.get_all_filtered(ProjectFilter.ACTIVE)
        assert len(result) == 1 and result[0].name == 'served'

    def test_get_all_filtered_prod_returns_only_served(self):
        self._insert_served_project('with-config')
        self.project_dao.insert(
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='no-config')
        )
        result = self.project_dao.get_all_filtered(ProjectFilter.PROD)
        assert len(result) == 1 and result[0].name == 'with-config'

    def test_get_all_filtered_dev_returns_only_without_served(self):
        self._insert_served_project('with-config')
        self.project_dao.insert(
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='no-config')
        )
        result = self.project_dao.get_all_filtered(ProjectFilter.DEV)
        assert len(result) == 1 and result[0].name == 'no-config'

    def test_get_all_filtered_with_usage_returns_ever_served(self):
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        now = datetime.datetime.now(tz=UTC)
        self.project_dao.insert(
            db_mock.get_sample_project(
                uuid=uuid.uuid4(), name='was-served', first_served_at=now
            )
        )
        self.project_dao.insert(
            db_mock.get_sample_project(
                uuid=uuid.uuid4(), name='never-served', first_served_at=None
            )
        )
        result = self.project_dao.get_all_filtered(ProjectFilter.WITH_USAGE)
        assert len(result) == 1 and result[0].name == 'was-served'

    def test_soft_delete(self):
        project = db_mock.get_sample_project()
        self.project_dao.insert(project)
        assert self.project_dao.soft_delete(project.uuid) == 1

    def test_soft_delete_not_found(self):
        assert self.project_dao.soft_delete(uuid.uuid4()) == 0

    def test_get_by_uuid_excludes_deleted(self):
        project = db_mock.get_sample_project()
        self.project_dao.insert(project)
        self.project_dao.soft_delete(project.uuid)
        assert self.project_dao.get_by_uuid(project.uuid) is None

    def test_get_all_excludes_deleted(self):
        projects = [
            db_mock.get_sample_project(uuid=uuid.uuid4(), name=n)
            for n in ('one', 'two', 'three')
        ]
        for p in projects:
            self.project_dao.insert(p)
        self.project_dao.soft_delete(projects[0].uuid)
        result = self.project_dao.get_all()
        assert len(result) == 2 and 'one' not in {p.name for p in result}

    def test_get_all_filtered_excludes_deleted(self):
        self.project_dao.insert(
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='live')
        )
        deleted = db_mock.get_sample_project(uuid=uuid.uuid4(), name='deleted')
        self.project_dao.insert(deleted)
        self.project_dao.soft_delete(deleted.uuid)
        result = self.project_dao.get_all_filtered(None)
        assert len(result) == 1 and result[0].name == 'live'

    def test_get_all_with_config_excludes_deleted(self):
        served = self._insert_served_project('served')
        self.project_dao.soft_delete(served.uuid)
        assert list(self.project_dao.get_all_with_config()) == []
