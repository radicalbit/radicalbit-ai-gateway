import unittest
from unittest.mock import AsyncMock, MagicMock
import uuid

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from starlette.testclient import TestClient

from tests.common import db_mock

from radicalbit_ai_gateway.models.config_slot import Slot
from radicalbit_ai_gateway.models.config_status import ConfigStatus
from radicalbit_ai_gateway.models.project_dto import ProjectFilter
from radicalbit_ai_gateway.routes.project_route import ProjectRoute
from radicalbit_ai_gateway.services.config_generator_service import (
    ConfigGeneratorService,
)
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.utils.exceptions import (
    AuthRegistryError,
    ProjectAlreadyExistsError,
    ProjectConfigValidationError,
    ProjectNotFoundError,
    auth_registry_exception_handler,
)

_VALID = db_mock.VALID_CONFIG_YAML


class TestProjectRoute(unittest.TestCase):
    def setUp(self):
        self.prefix = '/public/api/v1'
        self.project_service = MagicMock(spec_set=ProjectService)
        self.group_service = MagicMock(spec_set=GroupService)
        self.config_generator_service = MagicMock(spec_set=ConfigGeneratorService)
        self.register = AsyncMock()
        self.deregister = AsyncMock()
        router = ProjectRoute.get_project_router(
            self.project_service,
            self.group_service,
            register_project_routes=self.register,
            deregister_project_routes=self.deregister,
            config_generator_service=self.config_generator_service,
        )
        app = FastAPI(title='AI Gateway', debug=True)
        app.add_exception_handler(AuthRegistryError, auth_registry_exception_handler)
        app.include_router(router, prefix=self.prefix)
        self.client = TestClient(app)

    # --- create / list / get ---

    def test_create_project(self):
        project_in = db_mock.get_sample_project_in()
        out = db_mock.get_sample_project_out()
        self.project_service.create_project = MagicMock(return_value=out)
        res = self.client.post(
            f'{self.prefix}/projects', json=jsonable_encoder(project_in)
        )
        assert res.status_code == 201
        assert res.json() == jsonable_encoder(out)
        self.project_service.create_project.assert_called_once_with(project_in)

    def test_create_project_already_exists(self):
        self.project_service.create_project = MagicMock(
            side_effect=ProjectAlreadyExistsError('error')
        )
        res = self.client.post(
            f'{self.prefix}/projects',
            json=jsonable_encoder(db_mock.get_sample_project_in()),
        )
        assert res.status_code == 400

    def test_get_all_with_filter(self):
        out = db_mock.get_sample_project_out()
        self.project_service.get_all_filtered = MagicMock(return_value=[out])
        res = self.client.get(f'{self.prefix}/projects', params={'filter': 'prod'})
        assert res.status_code == 200
        self.project_service.get_all_filtered.assert_called_once_with(
            ProjectFilter.PROD
        )

    def test_get_by_uuid(self):
        pid = uuid.uuid4()
        out = db_mock.get_sample_project_out(uuid=pid)
        self.project_service.get_by_uuid = MagicMock(return_value=out)
        res = self.client.get(f'{self.prefix}/projects/{pid}')
        assert res.status_code == 200
        self.project_service.get_by_uuid.assert_called_once_with(pid)

    def test_get_by_uuid_not_found(self):
        pid = uuid.uuid4()
        self.project_service.get_by_uuid = MagicMock(
            side_effect=ProjectNotFoundError('nope')
        )
        res = self.client.get(f'{self.prefix}/projects/{pid}')
        assert res.status_code == 404

    # --- config mutations ---

    def test_update_config(self):
        pid, cid = uuid.uuid4(), uuid.uuid4()
        out = db_mock.get_sample_project_out(uuid=pid)
        self.project_service.update_config = MagicMock(return_value=out)
        res = self.client.patch(
            f'{self.prefix}/projects/{pid}/configs/{cid}',
            json={'configFile': _VALID},
        )
        assert res.status_code == 200
        args = self.project_service.update_config.call_args.args
        assert args[0] == pid and args[1] == cid
        assert args[2].config_file == _VALID

    def test_update_config_validation_error(self):
        pid, cid = uuid.uuid4(), uuid.uuid4()
        self.project_service.update_config = MagicMock(
            side_effect=ProjectConfigValidationError('served read-only')
        )
        res = self.client.patch(
            f'{self.prefix}/projects/{pid}/configs/{cid}',
            json={'configFile': _VALID},
        )
        assert res.status_code == 400

    # --- export ---

    def test_export_config_returns_zip(self):
        pid, cid = uuid.uuid4(), uuid.uuid4()
        self.project_service.export_config = MagicMock(
            return_value=(b'zip-bytes', 'proj_slot_A_draft.zip')
        )
        res = self.client.get(f'{self.prefix}/projects/{pid}/configs/{cid}/export')
        assert res.status_code == 200
        assert res.headers['content-type'] == 'application/zip'
        assert (
            res.headers['content-disposition']
            == 'attachment; filename="proj_slot_A_draft.zip"'
        )
        assert res.content == b'zip-bytes'
        self.project_service.export_config.assert_called_once_with(pid, cid)

    def test_export_config_not_found(self):
        pid, cid = uuid.uuid4(), uuid.uuid4()
        self.project_service.export_config = MagicMock(
            side_effect=ProjectNotFoundError('nope')
        )
        res = self.client.get(f'{self.prefix}/projects/{pid}/configs/{cid}/export')
        assert res.status_code == 404

    def test_export_config_empty_returns_400(self):
        pid, cid = uuid.uuid4(), uuid.uuid4()
        self.project_service.export_config = MagicMock(
            side_effect=ProjectConfigValidationError('empty')
        )
        res = self.client.get(f'{self.prefix}/projects/{pid}/configs/{cid}/export')
        assert res.status_code == 400

    def test_approve_config(self):
        pid, cid = uuid.uuid4(), uuid.uuid4()
        self.project_service.approve_config = MagicMock(
            return_value=db_mock.get_sample_project_out(uuid=pid)
        )
        res = self.client.patch(f'{self.prefix}/projects/{pid}/configs/{cid}/approve')
        assert res.status_code == 200
        self.project_service.approve_config.assert_called_once_with(pid, cid)

    def test_cancel_approval(self):
        pid, cid = uuid.uuid4(), uuid.uuid4()
        self.project_service.cancel_approval = MagicMock(
            return_value=db_mock.get_sample_project_out(uuid=pid)
        )
        res = self.client.patch(
            f'{self.prefix}/projects/{pid}/configs/{cid}/cancel-approval'
        )
        assert res.status_code == 200
        self.project_service.cancel_approval.assert_called_once_with(pid, cid)

    def test_serve_config_registers_served_routes(self):
        pid, cid = uuid.uuid4(), uuid.uuid4()
        served = db_mock.get_sample_config_slot_out(
            uuid=cid, slot=Slot.A, config_file=_VALID, config_status=ConfigStatus.SERVED
        )
        other = db_mock.get_sample_config_slot_out(uuid=uuid.uuid4(), slot=Slot.B)
        out = db_mock.get_sample_project_out(
            uuid=pid, served_config_uuid=cid, configs=[served, other]
        )
        self.project_service.serve_config = MagicMock(return_value=out)
        self.group_service.cleanup_orphaned_associations = MagicMock(return_value=0)
        res = self.client.patch(f'{self.prefix}/projects/{pid}/configs/{cid}/serve')
        assert res.status_code == 200
        self.project_service.serve_config.assert_called_once_with(pid, cid)
        self.deregister.assert_awaited_once_with(pid)
        self.register.assert_awaited_once_with(pid, out.name, _VALID)

    def test_serve_config_cleans_up_orphaned_associations(self):
        pid, cid = uuid.uuid4(), uuid.uuid4()
        served = db_mock.get_sample_config_slot_out(
            uuid=cid, slot=Slot.A, config_file=_VALID, config_status=ConfigStatus.SERVED
        )
        other = db_mock.get_sample_config_slot_out(uuid=uuid.uuid4(), slot=Slot.B)
        out = db_mock.get_sample_project_out(
            uuid=pid, served_config_uuid=cid, configs=[served, other]
        )
        self.project_service.serve_config = MagicMock(return_value=out)
        self.group_service.cleanup_orphaned_associations = MagicMock(return_value=2)
        res = self.client.patch(f'{self.prefix}/projects/{pid}/configs/{cid}/serve')
        assert res.status_code == 200
        self.group_service.cleanup_orphaned_associations.assert_called_once_with(
            pid, out.name
        )

    def test_unserve_config_deregisters(self):
        pid, cid = uuid.uuid4(), uuid.uuid4()
        self.project_service.unserve_config = MagicMock(
            return_value=db_mock.get_sample_project_out(uuid=pid)
        )
        res = self.client.patch(f'{self.prefix}/projects/{pid}/configs/{cid}/unserve')
        assert res.status_code == 200
        self.project_service.unserve_config.assert_called_once_with(pid, cid)
        self.deregister.assert_awaited_once_with(pid)

    def test_generate_config(self):
        pid, cid = uuid.uuid4(), uuid.uuid4()
        self.project_service.get_config = MagicMock(
            return_value=db_mock.get_sample_config_slot_out(uuid=cid, config_file='# x')
        )
        self.config_generator_service.generate_config = AsyncMock(
            return_value='# generated'
        )
        res = self.client.post(
            f'{self.prefix}/projects/{pid}/configs/{cid}/generate-config',
            json={'description': 'make it'},
        )
        assert res.status_code == 200
        assert res.json()['configFile'] == '# generated'
        self.project_service.get_config.assert_called_once_with(pid, cid)

    def test_generate_config_rejected_when_served(self):
        pid, cid = uuid.uuid4(), uuid.uuid4()
        self.project_service.get_config = MagicMock(
            return_value=db_mock.get_sample_config_slot_out(
                uuid=cid, config_file='# x', config_status=ConfigStatus.SERVED
            )
        )
        self.config_generator_service.generate_config = AsyncMock(
            return_value='# generated'
        )
        res = self.client.post(
            f'{self.prefix}/projects/{pid}/configs/{cid}/generate-config',
            json={'description': 'make it'},
        )
        assert res.status_code == 400
        self.config_generator_service.generate_config.assert_not_awaited()

    def test_delete_project_deregisters_when_served(self):
        pid = uuid.uuid4()
        out = db_mock.get_sample_project_out(uuid=pid, served_config_uuid=uuid.uuid4())
        self.project_service.delete_project = MagicMock(return_value=out)
        res = self.client.delete(f'{self.prefix}/projects/{pid}')
        assert res.status_code == 200
        self.project_service.delete_project.assert_called_once_with(pid)
        self.deregister.assert_awaited_once_with(pid)

    def test_delete_project_no_deregister_when_dev(self):
        pid = uuid.uuid4()
        out = db_mock.get_sample_project_out(uuid=pid, served_config_uuid=None)
        self.project_service.delete_project = MagicMock(return_value=out)
        res = self.client.delete(f'{self.prefix}/projects/{pid}')
        assert res.status_code == 200
        self.deregister.assert_not_awaited()
