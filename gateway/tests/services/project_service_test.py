import io
from unittest.mock import MagicMock
import uuid
import zipfile

import pytest
from sqlalchemy.exc import IntegrityError

from tests.common import db_mock
from tests.common.db_integration import DatabaseIntegration

from radicalbit_ai_gateway.db.dao.project_config_dao import ProjectConfigDAO
from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO
from radicalbit_ai_gateway.models.config_slot import Slot
from radicalbit_ai_gateway.models.config_status import ConfigStatus
from radicalbit_ai_gateway.models.project_dto import (
    ConfigListFilter,
    ProjectConfigFileIn,
    ProjectFilter,
    ProjectIn,
)
from radicalbit_ai_gateway.models.project_status import ProjectStatus
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.utils.exceptions import (
    ProjectAlreadyExistsError,
    ProjectConfigValidationError,
    ProjectNotFoundError,
)

_VALID = db_mock.VALID_CONFIG_YAML


class ProjectServiceTest(DatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.svc = ProjectService(ProjectDAO(cls.db), ProjectConfigDAO(cls.db))

    def _create(self, name='proj'):
        out = self.svc.create_project(ProjectIn(name=name))
        return out, out.configs[0].uuid, out.configs[1].uuid

    # --- create ---

    def test_create_project_seeds_two_draft_slots(self):
        out, a, b = self._create()
        assert len(out.configs) == 2
        assert [c.slot for c in out.configs] == ['A', 'B']
        assert all(c.config_status == ConfigStatus.DRAFT for c in out.configs)
        assert out.project_status == ProjectStatus.DEV
        assert out.served_config_uuid is None

    def test_create_project_leaves_updated_at_null(self):
        out, _, _ = self._create()
        assert all(c.created_at is not None for c in out.configs)
        assert all(c.updated_at is None for c in out.configs)

    def test_update_config_sets_updated_at(self):
        out, a, _ = self._create()
        res = self.svc.update_config(
            out.uuid, a, ProjectConfigFileIn(config_file=_VALID)
        )
        assert next(c for c in res.configs if c.uuid == a).updated_at is not None

    def test_create_project_already_exists(self):
        # IntegrityError -> ProjectAlreadyExistsError mapping is a unit concern,
        # tested with a mocked DAO to stay independent of create_all metadata.
        svc = ProjectService(MagicMock(), MagicMock())
        svc.project_dao.insert_with_configs = MagicMock(
            side_effect=IntegrityError(None, None, BaseException('uq_project_NAME'))
        )
        with pytest.raises(ProjectAlreadyExistsError):
            svc.create_project(ProjectIn(name='dup'))

    def test_get_by_uuid_not_found(self):
        with pytest.raises(ProjectNotFoundError):
            self.svc.get_by_uuid(uuid.uuid4())

    # --- update ---

    def test_update_config_ok(self):
        out, a, _ = self._create()
        res = self.svc.update_config(
            out.uuid, a, ProjectConfigFileIn(config_file=_VALID)
        )
        ca = next(c for c in res.configs if c.uuid == a)
        assert ca.config_file == _VALID
        assert ca.config_status == ConfigStatus.DRAFT

    def test_update_config_invalid_yaml(self):
        out, a, _ = self._create()
        with pytest.raises(ProjectConfigValidationError):
            self.svc.update_config(
                out.uuid, a, ProjectConfigFileIn(config_file='::not yaml::')
            )

    def test_update_config_served_is_read_only(self):
        out, a, _ = self._create()
        self.svc.update_config(out.uuid, a, ProjectConfigFileIn(config_file=_VALID))
        self.svc.approve_config(out.uuid, a)
        self.svc.serve_config(out.uuid, a)
        with pytest.raises(ProjectConfigValidationError):
            self.svc.update_config(out.uuid, a, ProjectConfigFileIn(config_file=_VALID))

    def test_update_config_wrong_project(self):
        out, a, _ = self._create()
        with pytest.raises(ProjectNotFoundError):
            self.svc.update_config(
                uuid.uuid4(), a, ProjectConfigFileIn(config_file=_VALID)
            )

    # --- approve / cancel ---

    def test_approve_then_cancel(self):
        out, a, _ = self._create()
        self.svc.update_config(out.uuid, a, ProjectConfigFileIn(config_file=_VALID))
        res = self.svc.approve_config(out.uuid, a)
        assert next(c for c in res.configs if c.uuid == a).config_status == (
            ConfigStatus.READY_TO_SERVE
        )
        res = self.svc.cancel_approval(out.uuid, a)
        assert next(c for c in res.configs if c.uuid == a).config_status == (
            ConfigStatus.DRAFT
        )

    def test_cancel_when_not_ready_raises(self):
        out, a, _ = self._create()
        with pytest.raises(ProjectConfigValidationError):
            self.svc.cancel_approval(out.uuid, a)

    # --- serve / swap / unserve ---

    def test_serve_requires_approval(self):
        out, a, _ = self._create()
        self.svc.update_config(out.uuid, a, ProjectConfigFileIn(config_file=_VALID))
        with pytest.raises(ProjectConfigValidationError):
            self.svc.serve_config(out.uuid, a)

    def test_serve_ok(self):
        out, a, _ = self._create()
        self.svc.update_config(out.uuid, a, ProjectConfigFileIn(config_file=_VALID))
        self.svc.approve_config(out.uuid, a)
        res = self.svc.serve_config(out.uuid, a)
        assert res.project_status == ProjectStatus.PROD
        assert res.served_config_uuid == a
        assert next(c for c in res.configs if c.uuid == a).config_status == (
            ConfigStatus.SERVED
        )

    def test_serve_swaps_displaced_to_draft(self):
        out, a, b = self._create()
        for c in (a, b):
            self.svc.update_config(out.uuid, c, ProjectConfigFileIn(config_file=_VALID))
            self.svc.approve_config(out.uuid, c)
        self.svc.serve_config(out.uuid, a)
        res = self.svc.serve_config(out.uuid, b)
        st = {c.uuid: c.config_status for c in res.configs}
        assert st[b] == ConfigStatus.SERVED
        assert st[a] == ConfigStatus.DRAFT
        assert res.served_config_uuid == b

    def test_unserve_ok(self):
        out, a, _ = self._create()
        self.svc.update_config(out.uuid, a, ProjectConfigFileIn(config_file=_VALID))
        self.svc.approve_config(out.uuid, a)
        self.svc.serve_config(out.uuid, a)
        res = self.svc.unserve_config(out.uuid, a)
        assert res.project_status == ProjectStatus.DEV
        assert res.served_config_uuid is None

    def test_unserve_when_not_served_raises(self):
        out, a, _ = self._create()
        with pytest.raises(ProjectConfigValidationError):
            self.svc.unserve_config(out.uuid, a)

    # --- delete ---

    def test_delete_project(self):
        out, _, _ = self._create()
        deleted = self.svc.delete_project(out.uuid)
        assert deleted.uuid == out.uuid
        with pytest.raises(ProjectNotFoundError):
            self.svc.get_by_uuid(out.uuid)

    def test_recreate_with_deleted_project_name_succeeds(self):
        out, _, _ = self._create(name='reuse-me')
        self.svc.delete_project(out.uuid)
        again = self.svc.create_project(ProjectIn(name='reuse-me'))
        assert again.uuid != out.uuid
        assert again.name == 'reuse-me'

    def test_duplicate_active_name_still_rejected(self):
        self._create(name='dup-active')
        with pytest.raises(ProjectAlreadyExistsError):
            self.svc.create_project(ProjectIn(name='dup-active'))

    # --- get_config ---

    def test_get_config(self):
        out, a, _ = self._create()
        slot = self.svc.get_config(out.uuid, a)
        assert slot.uuid == a and slot.slot == 'A'

    def test_get_config_wrong_project(self):
        out, a, _ = self._create()
        with pytest.raises(ProjectNotFoundError):
            self.svc.get_config(uuid.uuid4(), a)

    # --- export ---

    def test_export_config_returns_zip(self):
        out, a, _ = self._create()
        content, filename = self.svc.export_config(out.uuid, a)
        assert filename == 'proj_config.zip'
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
            assert names == ['proj_config_A_draft.yaml']
            assert archive.read(names[0]).decode() == out.configs[0].config_file

    def test_export_config_served_label(self):
        out, a, _ = self._create()
        self.svc.update_config(out.uuid, a, ProjectConfigFileIn(config_file=_VALID))
        self.svc.approve_config(out.uuid, a)
        self.svc.serve_config(out.uuid, a)
        content, filename = self.svc.export_config(out.uuid, a)
        assert filename == 'proj_config.zip'
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            assert archive.namelist() == ['proj_config_A_served.yaml']

    def test_export_all_configs_returns_zip_with_both_slots(self):
        out, a, b = self._create()
        content, filename = self.svc.export_all_configs(out.uuid)
        assert filename == 'proj_config.zip'
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            assert archive.namelist() == [
                'proj_config_A_draft.yaml',
                'proj_config_B_draft.yaml',
            ]

    def test_export_all_configs_skips_empty_slots(self):
        project = self.insert(
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='partial')
        )
        self.insert(
            db_mock.get_sample_project_config(
                project_uuid=project.uuid, slot=Slot.A, config_file=_VALID
            )
        )
        self.insert(
            db_mock.get_sample_project_config(
                project_uuid=project.uuid, slot=Slot.B, config_file=None
            )
        )
        content, _ = self.svc.export_all_configs(project.uuid)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            assert archive.namelist() == ['partial_config_A_draft.yaml']

    def test_export_all_configs_empty_raises(self):
        project = self.insert(
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='all-empty')
        )
        self.insert(
            db_mock.get_sample_project_config(
                project_uuid=project.uuid, slot=Slot.A, config_file=None
            )
        )
        with pytest.raises(ProjectConfigValidationError):
            self.svc.export_all_configs(project.uuid)

    def test_export_all_configs_not_found(self):
        with pytest.raises(ProjectNotFoundError):
            self.svc.export_all_configs(uuid.uuid4())

    def test_export_config_empty_raises(self):
        project = self.insert(
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='export-empty')
        )
        config = self.insert(
            db_mock.get_sample_project_config(
                project_uuid=project.uuid, slot=Slot.A, config_file=None
            )
        )
        with pytest.raises(ProjectConfigValidationError):
            self.svc.export_config(project.uuid, config.uuid)

    def test_export_config_not_found(self):
        with pytest.raises(ProjectNotFoundError):
            self.svc.export_config(uuid.uuid4(), uuid.uuid4())

    # --- import ---

    def test_import_config_writes_draft(self):
        out, a, _ = self._create()
        res = self.svc.import_config(out.uuid, a, _VALID.encode())
        ca = next(c for c in res.configs if c.uuid == a)
        assert ca.config_file == _VALID
        assert ca.config_status == ConfigStatus.DRAFT
        assert ca.updated_at is not None

    def test_import_config_into_served_raises(self):
        out, a, _ = self._create()
        self.svc.update_config(out.uuid, a, ProjectConfigFileIn(config_file=_VALID))
        self.svc.approve_config(out.uuid, a)
        self.svc.serve_config(out.uuid, a)
        with pytest.raises(ProjectConfigValidationError):
            self.svc.import_config(out.uuid, a, _VALID.encode())

    def test_import_config_invalid_yaml_raises(self):
        out, a, _ = self._create()
        with pytest.raises(ProjectConfigValidationError):
            self.svc.import_config(out.uuid, a, b'::not yaml::')

    def test_import_config_non_utf8_raises(self):
        out, a, _ = self._create()
        with pytest.raises(ProjectConfigValidationError):
            self.svc.import_config(out.uuid, a, b'\xff\xfe')

    def test_import_config_not_found(self):
        with pytest.raises(ProjectNotFoundError):
            self.svc.import_config(uuid.uuid4(), uuid.uuid4(), _VALID.encode())

    # --- listing / filters ---

    def test_get_all_and_filters(self):
        served, a, _ = self._create(name='served')
        self.svc.update_config(served.uuid, a, ProjectConfigFileIn(config_file=_VALID))
        self.svc.approve_config(served.uuid, a)
        self.svc.serve_config(served.uuid, a)
        self._create(name='dev')

        assert len(self.svc.get_all()) == 2
        prod = self.svc.get_all_filtered(ProjectFilter.PROD)
        assert [p.uuid for p in prod] == [served.uuid]
        dev = self.svc.get_all_filtered(ProjectFilter.DEV)
        assert served.uuid not in [p.uuid for p in dev]
        active = self.svc.get_all_active()
        assert [p.uuid for p in active] == [served.uuid]

    def test_get_configs_filters_by_status(self):
        # served-only: slot A served, slot B left as the untouched seed.
        served, a, _ = self._create(name='served')
        self.svc.update_config(served.uuid, a, ProjectConfigFileIn(config_file=_VALID))
        self.svc.approve_config(served.uuid, a)
        self.svc.serve_config(served.uuid, a)

        # draft-only: slot A saved (still DRAFT), never approved/served.
        draft_proj, da, _ = self._create(name='draft')
        self.svc.update_config(
            draft_proj.uuid, da, ProjectConfigFileIn(config_file=_VALID)
        )

        # untouched: both slots are EMPTY (seeded DRAFT with a NULL updated_at).
        self._create(name='untouched')

        assert len(self.svc.get_configs(None)) == 3
        assert len(self.svc.get_configs(ConfigListFilter.ALL)) == 3

        published = self.svc.get_configs(ConfigListFilter.PUBLISHED)
        assert [p.uuid for p in published] == [served.uuid]

        # "Draft" only matches the genuine draft, not the EMPTY seeded ones.
        draft = self.svc.get_configs(ConfigListFilter.DRAFT)
        assert [p.uuid for p in draft] == [draft_proj.uuid]

        assert self.svc.get_configs(ConfigListFilter.REQUEST_TO_PUBLISH) == []
