import unittest
from unittest.mock import AsyncMock, MagicMock
import uuid

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from starlette.testclient import TestClient

from tests.common import db_mock

from radicalbit_ai_gateway.models.auth_dto import GroupFullOut, GroupOut
from radicalbit_ai_gateway.models.project_dto import (
    GenerateConfigIn,
    ProjectFilter,
    ProjectOut,
)
from radicalbit_ai_gateway.routes.project_route import ProjectRoute
from radicalbit_ai_gateway.services.config_generator_service import (
    ConfigGeneratorService,
)
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.utils.exceptions import (
    AuthRegistryError,
    ErrorOut,
    ProjectAlreadyExistsError,
    ProjectConfigValidationError,
    ProjectInternalError,
    ProjectNotFoundError,
    auth_registry_exception_handler,
)


class TestProjectRoute(unittest.TestCase):
    def setUp(self):
        self.prefix = '/public/api/v1'
        self.project_service = MagicMock(spec_set=ProjectService)
        self.group_service = MagicMock(spec_set=GroupService)
        self.config_generator_service = MagicMock(spec_set=ConfigGeneratorService)
        router = ProjectRoute.get_project_router(
            self.project_service,
            self.group_service,
            config_generator_service=self.config_generator_service,
        )
        app = FastAPI(title='AI Gateway', debug=True)
        app.add_exception_handler(AuthRegistryError, auth_registry_exception_handler)
        app.include_router(router, prefix=self.prefix)

        self.client = TestClient(app)

    def test_create_project(self):
        project_in = db_mock.get_sample_project_in()
        project = db_mock.get_sample_project()
        project_out = ProjectOut.from_project(project)
        self.project_service.create_project = MagicMock(return_value=project_out)
        res = self.client.post(
            f'{self.prefix}/projects', json=jsonable_encoder(project_in)
        )
        assert res.status_code == 201
        assert res.json() == jsonable_encoder(project_out)
        self.project_service.create_project.assert_called_once_with(project_in)

    def test_create_project_already_exists(self):
        project_in = db_mock.get_sample_project_in()
        self.project_service.create_project = MagicMock(
            side_effect=ProjectAlreadyExistsError('error')
        )
        res = self.client.post(
            f'{self.prefix}/projects', json=jsonable_encoder(project_in)
        )
        assert res.status_code == 400
        assert (
            res.json()['error']
            == ErrorOut(
                'error',
                'auth_registry_error',
                code='project_already_exists_bad_request',
                param=None,
            ).error
        )
        self.project_service.create_project.assert_called_once_with(project_in)

    def test_create_project_internal_error(self):
        project_in = db_mock.get_sample_project_in()
        self.project_service.create_project = MagicMock(
            side_effect=ProjectInternalError('error')
        )
        res = self.client.post(
            f'{self.prefix}/projects', json=jsonable_encoder(project_in)
        )
        assert res.status_code == 500
        assert (
            res.json()['error']
            == ErrorOut(
                'error',
                'auth_registry_error',
                code='project_internal_error',
                param=None,
            ).error
        )
        self.project_service.create_project.assert_called_once_with(project_in)

    def test_get_all(self):
        projects = [
            ProjectOut.from_project(
                db_mock.get_sample_project(uuid=uuid.uuid4(), name='one')
            ),
            ProjectOut.from_project(
                db_mock.get_sample_project(uuid=uuid.uuid4(), name='two')
            ),
            ProjectOut.from_project(
                db_mock.get_sample_project(uuid=uuid.uuid4(), name='three')
            ),
        ]
        self.project_service.get_all_filtered = MagicMock(return_value=projects)
        res = self.client.get(f'{self.prefix}/projects')
        assert res.status_code == 200
        assert jsonable_encoder(projects) == res.json()
        self.project_service.get_all_filtered.assert_called_once_with(None)

    def test_get_all_empty(self):
        self.project_service.get_all_filtered = MagicMock(return_value=[])
        res = self.client.get(f'{self.prefix}/projects')
        assert res.status_code == 200
        assert res.json() == []
        self.project_service.get_all_filtered.assert_called_once_with(None)

    def test_get_all_with_active_filter(self):
        projects = [
            ProjectOut.from_project(
                db_mock.get_sample_project(
                    uuid=uuid.uuid4(), name='served', config_file='some: yaml'
                )
            ),
        ]
        self.project_service.get_all_filtered = MagicMock(return_value=projects)
        res = self.client.get(f'{self.prefix}/projects?filter=active')
        assert res.status_code == 200
        assert jsonable_encoder(projects) == res.json()
        self.project_service.get_all_filtered.assert_called_once_with(
            ProjectFilter.ACTIVE
        )

    def test_get_all_with_usage_filter(self):
        projects = [
            ProjectOut.from_project(
                db_mock.get_sample_project(uuid=uuid.uuid4(), name='ever-served')
            ),
        ]
        self.project_service.get_all_filtered = MagicMock(return_value=projects)
        res = self.client.get(f'{self.prefix}/projects?filter=with_usage')
        assert res.status_code == 200
        assert jsonable_encoder(projects) == res.json()
        self.project_service.get_all_filtered.assert_called_once_with(
            ProjectFilter.WITH_USAGE
        )

    def test_get_all_invalid_filter_returns_422(self):
        res = self.client.get(f'{self.prefix}/projects?filter=invalid')
        assert res.status_code == 422

    def test_get_project_by_uuid(self):
        project = db_mock.get_sample_project()
        project_out = ProjectOut.from_project(project)
        self.project_service.get_by_uuid = MagicMock(return_value=project_out)
        res = self.client.get(f'{self.prefix}/projects/{project.uuid}')
        assert res.status_code == 200
        assert jsonable_encoder(project_out) == res.json()
        self.project_service.get_by_uuid.assert_called_once_with(project.uuid)

    def test_get_project_by_uuid_not_found(self):
        unknown_uuid = uuid.uuid4()
        self.project_service.get_by_uuid = MagicMock(
            side_effect=ProjectNotFoundError('error')
        )
        res = self.client.get(f'{self.prefix}/projects/{unknown_uuid}')
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error',
                'auth_registry_error',
                code='project_not_found',
                param=None,
            ).error
        )
        self.project_service.get_by_uuid.assert_called_once_with(unknown_uuid)

    def test_load_config_ok(self):
        config_in = db_mock.get_sample_project_config_file_in()
        project = db_mock.get_sample_project(draft_config_file=config_in.config_file)
        project_out = ProjectOut.from_project(project)
        self.project_service.load_config = MagicMock(return_value=project_out)
        res = self.client.patch(
            f'{self.prefix}/projects/{project.uuid}/load-config',
            json=jsonable_encoder(config_in),
        )
        assert res.status_code == 200
        assert res.json() == jsonable_encoder(project_out)
        self.project_service.load_config.assert_called_once_with(
            project.uuid, config_in
        )

    def test_load_config_project_not_found(self):
        config_in = db_mock.get_sample_project_config_file_in()
        unknown_uuid = uuid.uuid4()
        self.project_service.load_config = MagicMock(
            side_effect=ProjectNotFoundError('error')
        )
        res = self.client.patch(
            f'{self.prefix}/projects/{unknown_uuid}/load-config',
            json=jsonable_encoder(config_in),
        )
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error',
                'auth_registry_error',
                code='project_not_found',
                param=None,
            ).error
        )

    def test_serve_config_ok(self):
        config_in = db_mock.get_sample_project_config_file_in()
        project = db_mock.get_sample_project(
            draft_config_file=None,
            config_file=config_in.config_file,
        )
        project_out = ProjectOut.from_project(project)
        self.project_service.serve_config = MagicMock(return_value=project_out)
        res = self.client.patch(f'{self.prefix}/projects/{project.uuid}/serve-config')
        assert res.status_code == 200
        assert res.json() == jsonable_encoder(project_out)
        self.project_service.serve_config.assert_called_once_with(project.uuid)

    def test_serve_config_not_found(self):
        unknown_uuid = uuid.uuid4()
        self.project_service.serve_config = MagicMock(
            side_effect=ProjectNotFoundError('error')
        )
        res = self.client.patch(f'{self.prefix}/projects/{unknown_uuid}/serve-config')
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error',
                'auth_registry_error',
                code='project_not_found',
                param=None,
            ).error
        )

    def test_serve_config_no_draft(self):
        project_uuid = uuid.uuid4()
        self.project_service.serve_config = MagicMock(
            side_effect=ProjectConfigValidationError('error')
        )
        res = self.client.patch(f'{self.prefix}/projects/{project_uuid}/serve-config')
        assert res.status_code == 400
        assert (
            res.json()['error']
            == ErrorOut(
                'error',
                'auth_registry_error',
                code='project_config_validation_error',
                param=None,
            ).error
        )

    def test_serve_config_internal_error(self):
        project_uuid = uuid.uuid4()
        self.project_service.serve_config = MagicMock(
            side_effect=ProjectInternalError('error')
        )
        res = self.client.patch(f'{self.prefix}/projects/{project_uuid}/serve-config')
        assert res.status_code == 500
        assert (
            res.json()['error']
            == ErrorOut(
                'error',
                'auth_registry_error',
                code='project_internal_error',
                param=None,
            ).error
        )

    def test_serve_config_calls_register_fn(self):
        config_in = db_mock.get_sample_project_config_file_in()
        project = db_mock.get_sample_project(
            name='my-project',
            draft_config_file=None,
            config_file=config_in.config_file,
        )
        project_out = ProjectOut.from_project(project)
        register_fn = AsyncMock()
        router = ProjectRoute.get_project_router(
            self.project_service,
            self.group_service,
            register_project_routes=register_fn,
            config_generator_service=self.config_generator_service,
        )
        app = FastAPI(title='AI Gateway', debug=True)
        app.add_exception_handler(AuthRegistryError, auth_registry_exception_handler)
        app.include_router(router, prefix=self.prefix)
        client = TestClient(app)

        self.project_service.serve_config = MagicMock(return_value=project_out)
        res = client.patch(f'{self.prefix}/projects/{project.uuid}/serve-config')
        assert res.status_code == 200
        register_fn.assert_called_once_with(
            project.uuid,
            project_out.name,
            project_out.config_file,
        )

    def test_unserve_config_calls_deregister_fn(self):
        project = db_mock.get_sample_project(
            config_file='some: yaml',
        )
        project_out = ProjectOut.from_project(project)
        deregister_fn = AsyncMock()
        router = ProjectRoute.get_project_router(
            self.project_service,
            self.group_service,
            deregister_project_routes=deregister_fn,
        )
        app = FastAPI(title='AI Gateway', debug=True)
        app.add_exception_handler(AuthRegistryError, auth_registry_exception_handler)
        app.include_router(router, prefix=self.prefix)
        client = TestClient(app)

        self.project_service.unserve_config = MagicMock(return_value=project_out)
        res = client.patch(f'{self.prefix}/projects/{project.uuid}/unserve-config')
        assert res.status_code == 200
        deregister_fn.assert_called_once_with(project.uuid)

    def test_load_config_invalid_config(self):
        config_in = db_mock.get_sample_project_config_file_in()
        project_uuid = uuid.uuid4()
        self.project_service.load_config = MagicMock(
            side_effect=ProjectConfigValidationError('error')
        )
        res = self.client.patch(
            f'{self.prefix}/projects/{project_uuid}/load-config',
            json=jsonable_encoder(config_in),
        )
        assert res.status_code == 400
        assert (
            res.json()['error']
            == ErrorOut(
                'error',
                'auth_registry_error',
                code='project_config_validation_error',
                param=None,
            ).error
        )

    # -- /projects/{project_uuid}/routes/{route_name}/groups -----------------

    def test_add_groups_to_project_route_success(self):
        project_uuid = uuid.uuid4()
        route_name = 'route-A'
        project_out = db_mock.get_sample_project_out(
            uuid=project_uuid, name='my-project'
        )
        self.project_service.get_by_uuid = MagicMock(return_value=project_out)
        groups = [db_mock.get_sample_group(), db_mock.get_sample_group()]
        groups_uuid = [uuid.UUID(str(g.uuid)) for g in groups]
        groups_route_in = db_mock.get_sample_route_groups_in(groups=groups_uuid)
        route_groups_out = db_mock.get_sample_route_groups_out(
            route_name=route_name,
            project_name='my-project',
            groups=[GroupOut.from_group(g) for g in groups],
        )
        self.group_service.add_groups_to_project_route = MagicMock(
            return_value=route_groups_out
        )
        res = self.client.patch(
            f'{self.prefix}/projects/{project_uuid}/routes/{route_name}/groups?include_groups=True',
            json=jsonable_encoder(groups_route_in),
        )
        assert res.status_code == 200
        assert res.json() == jsonable_encoder(route_groups_out)
        self.group_service.add_groups_to_project_route.assert_called_once_with(
            project_uuid, 'my-project', route_name, groups_route_in, True
        )

    def test_add_groups_to_project_route_success_no_group(self):
        project_uuid = uuid.uuid4()
        route_name = 'route-A'
        project_out = db_mock.get_sample_project_out(
            uuid=project_uuid, name='my-project'
        )
        self.project_service.get_by_uuid = MagicMock(return_value=project_out)
        groups_uuid = [uuid.uuid4() for _ in range(3)]
        groups_route_in = db_mock.get_sample_route_groups_in(groups=groups_uuid)
        route_groups_out = db_mock.get_sample_route_groups_out(
            route_name=route_name,
            project_name='my-project',
            groups=None,
        )
        self.group_service.add_groups_to_project_route = MagicMock(
            return_value=route_groups_out
        )
        res = self.client.patch(
            f'{self.prefix}/projects/{project_uuid}/routes/{route_name}/groups?include_groups=False',
            json=jsonable_encoder(groups_route_in),
        )
        assert res.status_code == 200
        assert res.json() == jsonable_encoder(route_groups_out)

    def test_get_associable_groups_for_project_route(self):
        project_uuid = uuid.uuid4()
        route_name = 'route-A'
        project_out = db_mock.get_sample_project_out(
            uuid=project_uuid, name='my-project'
        )
        self.project_service.get_by_uuid = MagicMock(return_value=project_out)
        groups_out = [
            GroupFullOut.from_group(
                db_mock.get_sample_group_plain(uuid=uuid.uuid4(), name='g1')
            ),
            GroupFullOut.from_group(
                db_mock.get_sample_group_plain(uuid=uuid.uuid4(), name='g2')
            ),
        ]
        self.group_service.get_associable_groups_for_project_route = MagicMock(
            return_value=groups_out
        )
        res = self.client.get(
            f'{self.prefix}/projects/{project_uuid}/routes/{route_name}/associable-groups'
        )
        assert res.status_code == 200
        assert res.json() == jsonable_encoder(groups_out)
        self.group_service.get_associable_groups_for_project_route.assert_called_once_with(
            'my-project', route_name, False, False
        )

    def test_generate_config_ok(self):
        project_uuid = uuid.uuid4()
        gen_in = GenerateConfigIn(description='Create a simple OpenAI route')
        expected_yaml = 'chat_models:\n  - model_id: gpt4o\n    model: openai/gpt-4o\n'
        project_out = db_mock.get_sample_project_out(uuid=project_uuid)
        self.project_service.get_by_uuid = MagicMock(return_value=project_out)
        self.config_generator_service.generate_config = AsyncMock(
            return_value=expected_yaml
        )
        res = self.client.post(
            f'{self.prefix}/projects/{project_uuid}/generate-config',
            json=jsonable_encoder(gen_in),
        )
        assert res.status_code == 200
        assert res.json()['configFile'] == expected_yaml
        self.config_generator_service.generate_config.assert_called_once_with(
            gen_in.description, None
        )

    def test_generate_config_passes_draft_as_context(self):
        project_uuid = uuid.uuid4()
        draft = 'chat_models:\n  - model_id: existing\n'
        gen_in = GenerateConfigIn(description='Add rate limiting')
        project_out = db_mock.get_sample_project_out(
            uuid=project_uuid, draft_config_file=draft
        )
        self.project_service.get_by_uuid = MagicMock(return_value=project_out)
        self.config_generator_service.generate_config = AsyncMock(return_value=draft)
        self.client.post(
            f'{self.prefix}/projects/{project_uuid}/generate-config',
            json=jsonable_encoder(gen_in),
        )
        self.config_generator_service.generate_config.assert_called_once_with(
            gen_in.description, draft
        )

    def test_generate_config_project_not_found(self):
        project_uuid = uuid.uuid4()
        gen_in = GenerateConfigIn(description='desc')
        self.project_service.get_by_uuid = MagicMock(
            side_effect=ProjectNotFoundError('not found')
        )
        res = self.client.post(
            f'{self.prefix}/projects/{project_uuid}/generate-config',
            json=jsonable_encoder(gen_in),
        )
        assert res.status_code == 404

    def test_generate_config_validation_failure(self):
        project_uuid = uuid.uuid4()
        gen_in = GenerateConfigIn(description='desc')
        self.project_service.get_by_uuid = MagicMock(
            return_value=db_mock.get_sample_project_out(uuid=project_uuid)
        )
        self.config_generator_service.generate_config = AsyncMock(
            side_effect=ProjectConfigValidationError('failed after retries')
        )
        res = self.client.post(
            f'{self.prefix}/projects/{project_uuid}/generate-config',
            json=jsonable_encoder(gen_in),
        )
        assert res.status_code == 400

    def test_generate_config_internal_error(self):
        project_uuid = uuid.uuid4()
        gen_in = GenerateConfigIn(description='desc')
        self.project_service.get_by_uuid = MagicMock(
            return_value=db_mock.get_sample_project_out(uuid=project_uuid)
        )
        self.config_generator_service.generate_config = AsyncMock(
            side_effect=ProjectInternalError('llm down')
        )
        res = self.client.post(
            f'{self.prefix}/projects/{project_uuid}/generate-config',
            json=jsonable_encoder(gen_in),
        )
        assert res.status_code == 500
