import datetime
import uuid

from tests.common import db_mock
from tests.common.db_integration import DatabaseIntegration

from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO
from radicalbit_ai_gateway.models.project_dto import ProjectFilter


class ProjectDAOTest(DatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project_dao = ProjectDAO(cls.db)

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
        assert result.name == project.name

    def test_get_by_uuid_not_found(self):
        result = self.project_dao.get_by_uuid(uuid.uuid4())
        assert result is None

    def test_get_all(self):
        projects = [
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='one'),
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='two'),
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='three'),
        ]
        for p in projects:
            self.project_dao.insert(p)
        result = self.project_dao.get_all()
        assert len(result) == 3

    def test_get_all_empty(self):
        result = self.project_dao.get_all()
        assert list(result) == []

    def test_get_all_with_config_only_returns_projects_with_config(self):
        self.project_dao.insert(
            db_mock.get_sample_project(
                uuid=uuid.uuid4(), name='active', config_file='some-yaml'
            )
        )
        self.project_dao.insert(
            db_mock.get_sample_project(
                uuid=uuid.uuid4(), name='inactive', config_file=None
            )
        )
        result = self.project_dao.get_all_with_config()
        assert len(result) == 1
        assert result[0].config_file == 'some-yaml'
        assert result[0].name == 'active'

    def test_get_all_with_config_empty(self):
        self.project_dao.insert(
            db_mock.get_sample_project(
                uuid=uuid.uuid4(), name='no-config', config_file=None
            )
        )
        result = self.project_dao.get_all_with_config()
        assert list(result) == []

    def test_update_draft_config_file(self):
        project = db_mock.get_sample_project()
        self.project_dao.insert(project)
        rows = self.project_dao.update_draft_config_file(project.uuid, 'draft-yaml')
        assert rows == 1
        updated = self.project_dao.get_by_uuid(project.uuid)
        assert updated.draft_config_file == 'draft-yaml'
        assert updated.config_file is None

    def test_update_draft_config_file_not_found(self):
        rows = self.project_dao.update_draft_config_file(uuid.uuid4(), 'draft-yaml')
        assert rows == 0

    def test_promote_draft_to_config(self):
        project = db_mock.get_sample_project(draft_config_file='draft-yaml')
        self.project_dao.insert(project)
        rows = self.project_dao.promote_draft_to_config(project.uuid, 'draft-yaml')
        assert rows == 1
        updated = self.project_dao.get_by_uuid(project.uuid)
        assert updated.config_file == 'draft-yaml'
        assert updated.draft_config_file is None

    def test_promote_draft_to_config_not_found(self):
        rows = self.project_dao.promote_draft_to_config(uuid.uuid4(), 'some-yaml')
        assert rows == 0

    def test_promote_draft_to_config_sets_first_served_at(self):
        project = db_mock.get_sample_project(draft_config_file='draft-yaml')
        self.project_dao.insert(project)
        assert project.first_served_at is None
        self.project_dao.promote_draft_to_config(project.uuid, 'draft-yaml')
        updated = self.project_dao.get_by_uuid(project.uuid)
        assert updated.first_served_at is not None

    def test_promote_draft_to_config_preserves_first_served_at_on_re_serve(self):
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        original_time = datetime.datetime(2025, 1, 1, tzinfo=UTC)
        project = db_mock.get_sample_project(
            draft_config_file='draft-yaml',
            first_served_at=original_time,
        )
        self.project_dao.insert(project)
        self.project_dao.promote_draft_to_config(project.uuid, 'draft-yaml')
        updated = self.project_dao.get_by_uuid(project.uuid)
        assert updated.first_served_at == original_time

    def test_get_all_filtered_no_filter_returns_all(self):
        self.project_dao.insert(
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='a', config_file='yaml')
        )
        self.project_dao.insert(
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='b', config_file=None)
        )
        result = self.project_dao.get_all_filtered(None)
        assert len(result) == 2

    def test_get_all_filtered_active_returns_only_served(self):
        self.project_dao.insert(
            db_mock.get_sample_project(
                uuid=uuid.uuid4(), name='served', config_file='yaml'
            )
        )
        self.project_dao.insert(
            db_mock.get_sample_project(
                uuid=uuid.uuid4(), name='not-served', config_file=None
            )
        )
        result = self.project_dao.get_all_filtered(ProjectFilter.ACTIVE)
        assert len(result) == 1
        assert result[0].name == 'served'

    def test_get_all_filtered_with_usage_returns_ever_served(self):
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        now = datetime.datetime.now(tz=UTC)
        self.project_dao.insert(
            db_mock.get_sample_project(
                uuid=uuid.uuid4(),
                name='was-served',
                config_file=None,
                first_served_at=now,
            )
        )
        self.project_dao.insert(
            db_mock.get_sample_project(
                uuid=uuid.uuid4(),
                name='never-served',
                config_file=None,
                first_served_at=None,
            )
        )
        result = self.project_dao.get_all_filtered(ProjectFilter.WITH_USAGE)
        assert len(result) == 1
        assert result[0].name == 'was-served'

    def test_get_all_filtered_dev_returns_only_without_config_file(self):
        self.project_dao.insert(
            db_mock.get_sample_project(
                uuid=uuid.uuid4(), name='no-config', config_file=None
            )
        )
        self.project_dao.insert(
            db_mock.get_sample_project(
                uuid=uuid.uuid4(), name='with-config', config_file='yaml'
            )
        )
        result = self.project_dao.get_all_filtered(ProjectFilter.DEV)
        assert len(result) == 1
        assert result[0].name == 'no-config'

    def test_get_all_filtered_prod_returns_only_with_config_file(self):
        self.project_dao.insert(
            db_mock.get_sample_project(
                uuid=uuid.uuid4(), name='no-config', config_file=None
            )
        )
        self.project_dao.insert(
            db_mock.get_sample_project(
                uuid=uuid.uuid4(), name='with-config', config_file='yaml'
            )
        )
        result = self.project_dao.get_all_filtered(ProjectFilter.PROD)
        assert len(result) == 1
        assert result[0].name == 'with-config'

    # --- soft_delete ---

    def test_soft_delete(self):
        project = db_mock.get_sample_project()
        self.project_dao.insert(project)
        rows = self.project_dao.soft_delete(project.uuid)
        assert rows == 1

    def test_soft_delete_not_found(self):
        rows = self.project_dao.soft_delete(uuid.uuid4())
        assert rows == 0

    def test_get_by_uuid_excludes_deleted(self):
        project = db_mock.get_sample_project()
        self.project_dao.insert(project)
        self.project_dao.soft_delete(project.uuid)
        result = self.project_dao.get_by_uuid(project.uuid)
        assert result is None

    def test_get_all_excludes_deleted(self):
        projects = [
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='one'),
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='two'),
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='three'),
        ]
        for p in projects:
            self.project_dao.insert(p)
        self.project_dao.soft_delete(projects[0].uuid)
        result = self.project_dao.get_all()
        assert len(result) == 2
        assert 'one' not in {p.name for p in result}

    def test_get_all_filtered_excludes_deleted(self):
        self.project_dao.insert(
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='live')
        )
        deleted = db_mock.get_sample_project(uuid=uuid.uuid4(), name='deleted')
        self.project_dao.insert(deleted)
        self.project_dao.soft_delete(deleted.uuid)
        result = self.project_dao.get_all_filtered(None)
        assert len(result) == 1
        assert result[0].name == 'live'

    def test_get_all_with_config_excludes_deleted(self):
        served = db_mock.get_sample_project(
            uuid=uuid.uuid4(), name='served', config_file='some-yaml'
        )
        self.project_dao.insert(served)
        self.project_dao.soft_delete(served.uuid)
        result = self.project_dao.get_all_with_config()
        assert list(result) == []

    def test_unserve_config_noop_on_deleted_project(self):
        project = db_mock.get_sample_project(
            uuid=uuid.uuid4(), name='served', config_file='some-yaml'
        )
        self.project_dao.insert(project)
        self.project_dao.soft_delete(project.uuid)
        rows = self.project_dao.unserve_config(project.uuid, restore_draft=False)
        assert rows == 0
