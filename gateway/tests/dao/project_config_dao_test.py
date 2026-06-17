import datetime
import uuid

from tests.common import db_mock
from tests.common.db_integration import DatabaseIntegration

from radicalbit_ai_gateway.db.dao.project_config_dao import ProjectConfigDAO
from radicalbit_ai_gateway.db.tables.project_config_table import ProjectConfig
from radicalbit_ai_gateway.db.tables.project_table import Project
from radicalbit_ai_gateway.models.config_slot import Slot
from radicalbit_ai_gateway.models.config_status import ConfigStatus

_UTC = getattr(datetime, 'UTC', datetime.timezone.utc)


class ProjectConfigDAOTest(DatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dao = ProjectConfigDAO(cls.db)

    def _project(self) -> Project:
        project = db_mock.get_sample_project(
            uuid=uuid.uuid4(), name=f'p-{uuid.uuid4()}'
        )
        return self.insert(project)

    def _seed_two(self, project_uuid):
        now = datetime.datetime.now(tz=_UTC)
        a = self.insert(
            ProjectConfig(
                project_uuid=project_uuid,
                slot=Slot.A.value,
                config_file='# a',
                config_status=ConfigStatus.DRAFT.value,
                created_at=now,
                updated_at=None,
            )
        )
        b = self.insert(
            ProjectConfig(
                project_uuid=project_uuid,
                slot=Slot.B.value,
                config_file='# b',
                config_status=ConfigStatus.DRAFT.value,
                created_at=now,
                updated_at=None,
            )
        )
        return a.uuid, b.uuid

    def test_seed_and_list_ordered(self):
        p = self._project()
        self._seed_two(p.uuid)
        configs = self.dao.list_by_project(p.uuid)
        assert [c.slot for c in configs] == ['A', 'B']
        assert self.dao.get_served_by_project(p.uuid) is None

    def test_get_by_uuid(self):
        p = self._project()
        a_id, _ = self._seed_two(p.uuid)
        assert self.dao.get_by_uuid(a_id).uuid == a_id
        assert self.dao.get_by_uuid(uuid.uuid4()) is None

    def test_update_config_file_resets_to_draft(self):
        p = self._project()
        a_id, _ = self._seed_two(p.uuid)
        self.dao.set_status(a_id, ConfigStatus.READY_TO_SERVE)
        assert self.dao.update_config_file(a_id, 'new') == 1
        updated = self.dao.get_by_uuid(a_id)
        assert updated.config_file == 'new'
        assert updated.config_status == ConfigStatus.DRAFT.value

    def test_seeded_configs_have_null_updated_at(self):
        p = self._project()
        a_id, b_id = self._seed_two(p.uuid)
        assert self.dao.get_by_uuid(a_id).updated_at is None
        assert self.dao.get_by_uuid(b_id).updated_at is None

    def test_update_config_file_sets_updated_at(self):
        p = self._project()
        a_id, _ = self._seed_two(p.uuid)
        self.dao.update_config_file(a_id, 'saved')
        assert self.dao.get_by_uuid(a_id).updated_at is not None

    def test_set_status_keeps_updated_at_null(self):
        p = self._project()
        a_id, _ = self._seed_two(p.uuid)
        self.dao.set_status(a_id, ConfigStatus.READY_TO_SERVE)
        assert self.dao.get_by_uuid(a_id).updated_at is None

    def test_serve_keeps_config_updated_at_null(self):
        p = self._project()
        a_id, _ = self._seed_two(p.uuid)
        self.dao.serve(a_id)
        assert self.dao.get_by_uuid(a_id).updated_at is None

    def test_serve_sets_served_ref_and_first_served_at(self):
        p = self._project()
        a_id, _ = self._seed_two(p.uuid)
        served = self.dao.serve(a_id)
        assert served.config_status == ConfigStatus.SERVED.value
        with self.db.begin_session() as s:
            proj = s.get(Project, p.uuid)
            assert str(proj.served_config_uuid) == str(a_id)
            assert proj.first_served_at is not None

    def test_serve_swaps_and_keeps_single_served(self):
        p = self._project()
        a_id, b_id = self._seed_two(p.uuid)
        self.dao.serve(a_id)
        with self.db.begin_session() as s:
            first_served = s.get(Project, p.uuid).first_served_at
        self.dao.serve(b_id)
        by = {c.uuid: c.config_status for c in self.dao.list_by_project(p.uuid)}
        assert by[b_id] == ConfigStatus.SERVED.value
        assert by[a_id] == ConfigStatus.DRAFT.value
        served_rows = [
            c
            for c in self.dao.list_by_project(p.uuid)
            if c.config_status == ConfigStatus.SERVED.value
        ]
        assert len(served_rows) == 1
        with self.db.begin_session() as s:
            proj = s.get(Project, p.uuid)
            assert str(proj.served_config_uuid) == str(b_id)
            assert proj.first_served_at == first_served

    def test_serve_not_found(self):
        assert self.dao.serve(uuid.uuid4()) is None

    def test_unserve_clears_ref(self):
        p = self._project()
        a_id, _ = self._seed_two(p.uuid)
        self.dao.serve(a_id)
        assert self.dao.unserve(a_id) == 1
        assert self.dao.get_served_by_project(p.uuid) is None
        with self.db.begin_session() as s:
            assert s.get(Project, p.uuid).served_config_uuid is None

    def test_unserve_not_found(self):
        assert self.dao.unserve(uuid.uuid4()) == 0

    def test_soft_delete_by_project(self):
        p = self._project()
        self._seed_two(p.uuid)
        assert self.dao.soft_delete_by_project(p.uuid) == 2
        assert list(self.dao.list_by_project(p.uuid)) == []
