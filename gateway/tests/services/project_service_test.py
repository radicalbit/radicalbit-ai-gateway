import unittest
from unittest.mock import MagicMock
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from tests.common import db_mock

from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO
from radicalbit_ai_gateway.models.config_status import ConfigStatus
from radicalbit_ai_gateway.models.project_dto import ProjectFilter, ProjectOut
from radicalbit_ai_gateway.models.project_status import ProjectStatus
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.utils.exceptions import (
    ProjectAlreadyExistsError,
    ProjectConfigValidationError,
    ProjectInternalError,
    ProjectNotFoundError,
)


class ProjectServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project_dao: ProjectDAO = MagicMock(spec_set=ProjectDAO)
        cls.project_service = ProjectService(project_dao=cls.project_dao)
        cls.mocks = [cls.project_dao]

    def setUp(self):
        for mock in self.mocks:
            mock.reset_mock()

    def test_create_project_ok(self):
        project = db_mock.get_sample_project()
        self.project_dao.insert = MagicMock(return_value=project)
        project_in = db_mock.get_sample_project_in()
        result = self.project_service.create_project(project_in)
        self.project_dao.insert.assert_called_once()
        assert result == ProjectOut.from_project(project)

    def test_create_project_already_exists(self):
        self.project_dao.insert = MagicMock(
            side_effect=IntegrityError(None, None, BaseException('uq_project_NAME'))
        )
        project_in = db_mock.get_sample_project_in()
        with pytest.raises(ProjectAlreadyExistsError):
            self.project_service.create_project(project_in)

    def test_create_project_internal_error(self):
        self.project_dao.insert = MagicMock(
            side_effect=IntegrityError(
                None, None, BaseException('some_other_constraint')
            )
        )
        project_in = db_mock.get_sample_project_in()
        with pytest.raises(ProjectInternalError):
            self.project_service.create_project(project_in)

    def test_get_by_uuid_ok(self):
        project = db_mock.get_sample_project()
        self.project_dao.get_by_uuid = MagicMock(return_value=project)
        result = self.project_service.get_by_uuid(project.uuid)
        self.project_dao.get_by_uuid.assert_called_once_with(project.uuid)
        assert result == ProjectOut.from_project(project)

    def test_get_by_uuid_not_found(self):
        self.project_dao.get_by_uuid = MagicMock(return_value=None)
        with pytest.raises(ProjectNotFoundError):
            self.project_service.get_by_uuid(uuid.uuid4())

    def test_get_all(self):
        projects = [
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='one'),
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='two'),
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='three'),
        ]
        self.project_dao.get_all = MagicMock(return_value=projects)
        result = self.project_service.get_all()
        assert len(result) == 3
        assert result == [ProjectOut.from_project(p) for p in projects]

    def test_get_all_empty(self):
        self.project_dao.get_all = MagicMock(return_value=[])
        result = self.project_service.get_all()
        assert result == []

    def test_load_config_ok(self):
        config_in = db_mock.get_sample_project_config_file_in()
        project = db_mock.get_sample_project(
            draft_config_file=config_in.config_file,
            config_status=ConfigStatus.DRAFT,
        )
        self.project_dao.get_by_uuid = MagicMock(return_value=project)
        self.project_dao.update_draft_config_file = MagicMock(return_value=1)
        result = self.project_service.load_config(project.uuid, config_in)
        self.project_dao.update_draft_config_file.assert_called_once()
        assert result.draft_config_file == config_in.config_file
        assert result.config_status == ConfigStatus.DRAFT

    def test_load_config_project_not_found(self):
        config_in = db_mock.get_sample_project_config_file_in()
        self.project_dao.get_by_uuid = MagicMock(return_value=None)
        with pytest.raises(ProjectNotFoundError):
            self.project_service.load_config(uuid.uuid4(), config_in)

    def test_load_config_invalid_yaml(self):
        config_in = db_mock.get_sample_project_config_file_in(
            config_file='{{invalid yaml'
        )
        with pytest.raises(ProjectConfigValidationError):
            self.project_service.load_config(uuid.uuid4(), config_in)

    def test_load_config_invalid_gateway_config(self):
        config_in = db_mock.get_sample_project_config_file_in(
            config_file='some_key: some_value\n'
        )
        with pytest.raises(ProjectConfigValidationError):
            self.project_service.load_config(uuid.uuid4(), config_in)

    def test_load_config_rejects_literal_secrets(self):
        yaml_with_literal_key = """\
chat_models:
  - model_id: mock-chat
    model: mock/gateway
    credentials:
      api_key: sk-super-secret-key
    params:
      latency_ms: 150
      response_text: "mock response"
routes:
  test-route:
    chat_models:
      - mock-chat
"""
        config_in = db_mock.get_sample_project_config_file_in(
            config_file=yaml_with_literal_key
        )
        with pytest.raises(ProjectConfigValidationError, match='literal secrets'):
            self.project_service.load_config(uuid.uuid4(), config_in)

    def test_load_config_accepts_secret_refs(self):
        yaml_with_secret_ref = """\
chat_models:
  - model_id: mock-chat
    model: mock/gateway
    credentials:
      api_key: !secret OPENAI_API_KEY
    params:
      latency_ms: 150
      response_text: "mock response"
routes:
  test-route:
    chat_models:
      - mock-chat
"""
        config_in = db_mock.get_sample_project_config_file_in(
            config_file=yaml_with_secret_ref
        )
        project = db_mock.get_sample_project()
        self.project_dao.get_by_uuid = MagicMock(return_value=project)
        self.project_dao.update_draft_config_file = MagicMock(return_value=1)
        self.project_service.load_config(project.uuid, config_in)
        saved_content = self.project_dao.update_draft_config_file.call_args[0][1]
        assert '!secret OPENAI_API_KEY' in saved_content

    # --- cancel_approval ---

    def test_cancel_approval_ok(self):
        config_in = db_mock.get_sample_project_config_file_in()
        project = db_mock.get_sample_project(
            draft_config_file=config_in.config_file,
            config_status=ConfigStatus.READY_TO_SERVE,
        )
        cancelled_project = db_mock.get_sample_project(
            draft_config_file=config_in.config_file,
            config_status=ConfigStatus.DRAFT,
        )
        self.project_dao.get_by_uuid = MagicMock(
            side_effect=[project, cancelled_project]
        )
        self.project_dao.set_config_status = MagicMock(return_value=1)
        result = self.project_service.cancel_approval(project.uuid)
        self.project_dao.set_config_status.assert_called_once_with(
            project.uuid, ConfigStatus.DRAFT
        )
        assert result.config_status == ConfigStatus.DRAFT

    def test_cancel_approval_project_not_found(self):
        self.project_dao.get_by_uuid = MagicMock(return_value=None)
        with pytest.raises(ProjectNotFoundError):
            self.project_service.cancel_approval(uuid.uuid4())

    def test_cancel_approval_wrong_status_draft(self):
        project = db_mock.get_sample_project(
            config_status=ConfigStatus.DRAFT,
        )
        self.project_dao.get_by_uuid = MagicMock(return_value=project)
        with pytest.raises(ProjectConfigValidationError):
            self.project_service.cancel_approval(project.uuid)

    def test_cancel_approval_wrong_status_served(self):
        config_in = db_mock.get_sample_project_config_file_in()
        project = db_mock.get_sample_project(
            config_file=config_in.config_file,
            config_status=ConfigStatus.SERVED,
        )
        self.project_dao.get_by_uuid = MagicMock(return_value=project)
        with pytest.raises(ProjectConfigValidationError):
            self.project_service.cancel_approval(project.uuid)

    # --- approve_config ---

    def test_approve_config_ok(self):
        config_in = db_mock.get_sample_project_config_file_in()
        project = db_mock.get_sample_project(
            draft_config_file=config_in.config_file,
            config_status=ConfigStatus.DRAFT,
        )
        approved_project = db_mock.get_sample_project(
            draft_config_file=config_in.config_file,
            config_status=ConfigStatus.READY_TO_SERVE,
        )
        self.project_dao.get_by_uuid = MagicMock(
            side_effect=[project, approved_project]
        )
        self.project_dao.set_config_status = MagicMock(return_value=1)
        result = self.project_service.approve_config(project.uuid)
        self.project_dao.set_config_status.assert_called_once_with(
            project.uuid, ConfigStatus.READY_TO_SERVE
        )
        assert result.config_status == ConfigStatus.READY_TO_SERVE

    def test_approve_config_project_not_found(self):
        self.project_dao.get_by_uuid = MagicMock(return_value=None)
        with pytest.raises(ProjectNotFoundError):
            self.project_service.approve_config(uuid.uuid4())

    def test_approve_config_no_draft(self):
        project = db_mock.get_sample_project(
            config_status=ConfigStatus.READY_TO_SERVE, draft_config_file=None
        )
        self.project_dao.get_by_uuid = MagicMock(return_value=project)
        with pytest.raises(ProjectConfigValidationError):
            self.project_service.approve_config(project.uuid)

    def test_approve_config_wrong_status(self):
        config_in = db_mock.get_sample_project_config_file_in()
        project = db_mock.get_sample_project(
            draft_config_file=config_in.config_file,
            config_status=ConfigStatus.READY_TO_SERVE,
        )
        self.project_dao.get_by_uuid = MagicMock(return_value=project)
        with pytest.raises(ProjectConfigValidationError):
            self.project_service.approve_config(project.uuid)

    def test_approve_config_invalid_yaml(self):
        project = db_mock.get_sample_project(
            draft_config_file='{{invalid yaml',
            config_status=ConfigStatus.DRAFT,
        )
        self.project_dao.get_by_uuid = MagicMock(return_value=project)
        with pytest.raises(ProjectConfigValidationError):
            self.project_service.approve_config(project.uuid)

    def test_approve_config_invalid_gateway_config(self):
        project = db_mock.get_sample_project(
            draft_config_file='some_key: some_value\n',
            config_status=ConfigStatus.DRAFT,
        )
        self.project_dao.get_by_uuid = MagicMock(return_value=project)
        with pytest.raises(ProjectConfigValidationError):
            self.project_service.approve_config(project.uuid)

    def test_approve_config_rejects_literal_secrets(self):
        yaml_with_literal_key = """\
chat_models:
  - model_id: mock-chat
    model: mock/gateway
    credentials:
      api_key: sk-super-secret-key
    params:
      latency_ms: 150
      response_text: "mock response"
routes:
  test-route:
    chat_models:
      - mock-chat
"""
        project = db_mock.get_sample_project(
            draft_config_file=yaml_with_literal_key,
            config_status=ConfigStatus.DRAFT,
        )
        self.project_dao.get_by_uuid = MagicMock(return_value=project)
        with pytest.raises(ProjectConfigValidationError, match='literal secrets'):
            self.project_service.approve_config(project.uuid)

    # --- serve_config ---

    def test_serve_config_ok(self):
        config_in = db_mock.get_sample_project_config_file_in()
        project = db_mock.get_sample_project(
            draft_config_file=config_in.config_file,
            config_status=ConfigStatus.READY_TO_SERVE,
        )
        updated_project = db_mock.get_sample_project(
            draft_config_file=None,
            config_file=config_in.config_file,
            config_status=ConfigStatus.SERVED,
        )
        self.project_dao.get_by_uuid = MagicMock(side_effect=[project, updated_project])
        self.project_dao.promote_draft_to_config = MagicMock(return_value=1)
        result = self.project_service.serve_config(project.uuid)
        self.project_dao.promote_draft_to_config.assert_called_once_with(
            project.uuid, config_in.config_file
        )
        assert result.config_file == config_in.config_file
        assert result.draft_config_file is None
        assert result.config_status == ConfigStatus.SERVED
        assert result.project_status == ProjectStatus.PROD

    def test_serve_config_project_not_found(self):
        self.project_dao.get_by_uuid = MagicMock(return_value=None)
        with pytest.raises(ProjectNotFoundError):
            self.project_service.serve_config(uuid.uuid4())

    def test_serve_config_requires_approved_status(self):
        config_in = db_mock.get_sample_project_config_file_in()
        project = db_mock.get_sample_project(
            draft_config_file=config_in.config_file,
            config_status=ConfigStatus.DRAFT,
        )
        self.project_dao.get_by_uuid = MagicMock(return_value=project)
        with pytest.raises(ProjectConfigValidationError):
            self.project_service.serve_config(project.uuid)

    def test_serve_config_promote_returns_zero(self):
        config_in = db_mock.get_sample_project_config_file_in()
        project = db_mock.get_sample_project(
            draft_config_file=config_in.config_file,
            config_status=ConfigStatus.READY_TO_SERVE,
        )
        self.project_dao.get_by_uuid = MagicMock(return_value=project)
        self.project_dao.promote_draft_to_config = MagicMock(return_value=0)
        with pytest.raises(ProjectInternalError):
            self.project_service.serve_config(project.uuid)

    # --- unserve_config ---

    def test_unserve_config_ok_restores_draft(self):
        config_in = db_mock.get_sample_project_config_file_in()
        project = db_mock.get_sample_project(
            config_file=config_in.config_file,
            draft_config_file=None,
            config_status=ConfigStatus.SERVED,
        )
        unserved_project = db_mock.get_sample_project(
            config_file=None,
            draft_config_file=config_in.config_file,
            config_status=ConfigStatus.DRAFT,
        )
        self.project_dao.get_by_uuid = MagicMock(
            side_effect=[project, unserved_project]
        )
        self.project_dao.unserve_config = MagicMock(return_value=1)
        result = self.project_service.unserve_config(project.uuid)
        self.project_dao.unserve_config.assert_called_once_with(project.uuid, True)
        assert result.config_file is None
        assert result.draft_config_file == config_in.config_file
        assert result.config_status == ConfigStatus.DRAFT
        assert result.project_status == ProjectStatus.DEV

    def test_unserve_config_ok_keeps_existing_draft(self):
        config_in = db_mock.get_sample_project_config_file_in()
        project = db_mock.get_sample_project(
            config_file=config_in.config_file,
            draft_config_file='existing-draft',
            config_status=ConfigStatus.DRAFT,
        )
        unserved_project = db_mock.get_sample_project(
            config_file=None,
            draft_config_file='existing-draft',
            config_status=ConfigStatus.DRAFT,
        )
        self.project_dao.get_by_uuid = MagicMock(
            side_effect=[project, unserved_project]
        )
        self.project_dao.unserve_config = MagicMock(return_value=1)
        result = self.project_service.unserve_config(project.uuid)
        self.project_dao.unserve_config.assert_called_once_with(project.uuid, False)
        assert result.draft_config_file == 'existing-draft'

    def test_unserve_config_project_not_found(self):
        self.project_dao.get_by_uuid = MagicMock(return_value=None)
        with pytest.raises(ProjectNotFoundError):
            self.project_service.unserve_config(uuid.uuid4())

    def test_unserve_config_not_served(self):
        project = db_mock.get_sample_project(
            config_file=None,
            config_status=ConfigStatus.DRAFT,
        )
        self.project_dao.get_by_uuid = MagicMock(return_value=project)
        with pytest.raises(ProjectConfigValidationError):
            self.project_service.unserve_config(project.uuid)

    # --- project_status and config_status in responses ---

    def test_new_project_has_draft_status_and_dev(self):
        project = db_mock.get_sample_project(config_status=ConfigStatus.DRAFT)
        self.project_dao.insert = MagicMock(return_value=project)
        result = self.project_service.create_project(db_mock.get_sample_project_in())
        assert result.config_status == ConfigStatus.DRAFT
        assert result.project_status == ProjectStatus.DEV

    def test_served_project_has_prod_status(self):
        config_in = db_mock.get_sample_project_config_file_in()
        project = db_mock.get_sample_project(
            config_file=config_in.config_file,
            config_status=ConfigStatus.SERVED,
        )
        self.project_dao.get_by_uuid = MagicMock(return_value=project)
        result = self.project_service.get_by_uuid(project.uuid)
        assert result.project_status == ProjectStatus.PROD
        assert result.config_status == ConfigStatus.SERVED

    # --- get_all_active ---

    def test_get_all_active_returns_only_active_projects(self):
        active = db_mock.get_sample_project(
            config_file='some-yaml',
            config_status=ConfigStatus.SERVED,
        )
        self.project_dao.get_all_with_config = MagicMock(return_value=[active])
        result = self.project_service.get_all_active()
        self.project_dao.get_all_with_config.assert_called_once()
        assert len(result) == 1
        assert result[0].config_file == 'some-yaml'
        assert result[0].name == active.name

    def test_get_all_active_empty(self):
        self.project_dao.get_all_with_config = MagicMock(return_value=[])
        result = self.project_service.get_all_active()
        assert result == []

    # --- delete_project ---

    def test_delete_project_ok_dev_state(self):
        project = db_mock.get_sample_project(
            config_file=None, config_status=ConfigStatus.DRAFT
        )
        self.project_dao.get_by_uuid = MagicMock(return_value=project)
        self.project_dao.soft_delete = MagicMock(return_value=1)
        result = self.project_service.delete_project(project.uuid)
        self.project_dao.soft_delete.assert_called_once_with(project.uuid)
        self.project_dao.unserve_config.assert_not_called()
        assert result == ProjectOut.from_project(project)

    def test_delete_project_ok_prod_state_restores_draft(self):
        config_in = db_mock.get_sample_project_config_file_in()
        project = db_mock.get_sample_project(
            config_file=config_in.config_file,
            draft_config_file=None,
            config_status=ConfigStatus.SERVED,
        )
        self.project_dao.get_by_uuid = MagicMock(return_value=project)
        self.project_dao.unserve_config = MagicMock(return_value=1)
        self.project_dao.soft_delete = MagicMock(return_value=1)
        result = self.project_service.delete_project(project.uuid)
        self.project_dao.unserve_config.assert_called_once_with(project.uuid, True)
        self.project_dao.soft_delete.assert_called_once_with(project.uuid)
        assert result.config_file == config_in.config_file

    def test_delete_project_ok_prod_state_keeps_existing_draft(self):
        config_in = db_mock.get_sample_project_config_file_in()
        project = db_mock.get_sample_project(
            config_file=config_in.config_file,
            draft_config_file='existing-draft',
            config_status=ConfigStatus.SERVED,
        )
        self.project_dao.get_by_uuid = MagicMock(return_value=project)
        self.project_dao.unserve_config = MagicMock(return_value=1)
        self.project_dao.soft_delete = MagicMock(return_value=1)
        self.project_service.delete_project(project.uuid)
        self.project_dao.unserve_config.assert_called_once_with(project.uuid, False)

    def test_delete_project_not_found(self):
        self.project_dao.get_by_uuid = MagicMock(return_value=None)
        with pytest.raises(ProjectNotFoundError):
            self.project_service.delete_project(uuid.uuid4())

    def test_delete_project_returns_pre_deletion_state(self):
        # DTO must reflect state before deletion so route can call deregister_project_routes.
        config_in = db_mock.get_sample_project_config_file_in()
        project = db_mock.get_sample_project(
            config_file=config_in.config_file,
            config_status=ConfigStatus.SERVED,
        )
        self.project_dao.get_by_uuid = MagicMock(return_value=project)
        self.project_dao.unserve_config = MagicMock(return_value=1)
        self.project_dao.soft_delete = MagicMock(return_value=1)
        result = self.project_service.delete_project(project.uuid)
        assert result.config_file == config_in.config_file
        assert result.project_status == ProjectStatus.PROD

    # --- get_all_filtered ---

    def test_get_all_filtered_delegates_to_dao(self):
        projects = [
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='one'),
        ]
        self.project_dao.get_all_filtered = MagicMock(return_value=projects)
        result = self.project_service.get_all_filtered(ProjectFilter.ACTIVE)
        self.project_dao.get_all_filtered.assert_called_once_with(ProjectFilter.ACTIVE)
        assert len(result) == 1
        assert result == [ProjectOut.from_project(p) for p in projects]

    def test_get_all_filtered_no_filter(self):
        projects = [
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='a'),
            db_mock.get_sample_project(uuid=uuid.uuid4(), name='b'),
        ]
        self.project_dao.get_all_filtered = MagicMock(return_value=projects)
        result = self.project_service.get_all_filtered(None)
        self.project_dao.get_all_filtered.assert_called_once_with(None)
        assert len(result) == 2

    def test_get_all_filtered_dev_delegates_to_dao(self):
        projects = [
            db_mock.get_sample_project(
                uuid=uuid.uuid4(), name='no-config', config_file=None
            ),
        ]
        self.project_dao.get_all_filtered = MagicMock(return_value=projects)
        result = self.project_service.get_all_filtered(ProjectFilter.DEV)
        self.project_dao.get_all_filtered.assert_called_once_with(ProjectFilter.DEV)
        assert len(result) == 1
        assert result == [ProjectOut.from_project(p) for p in projects]

    def test_get_all_filtered_prod_delegates_to_dao(self):
        projects = [
            db_mock.get_sample_project(
                uuid=uuid.uuid4(), name='with-config', config_file='yaml'
            ),
        ]
        self.project_dao.get_all_filtered = MagicMock(return_value=projects)
        result = self.project_service.get_all_filtered(ProjectFilter.PROD)
        self.project_dao.get_all_filtered.assert_called_once_with(ProjectFilter.PROD)
        assert len(result) == 1
        assert result == [ProjectOut.from_project(p) for p in projects]
