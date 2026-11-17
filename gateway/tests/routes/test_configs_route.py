import unittest
from unittest.mock import MagicMock

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from starlette.testclient import TestClient

from tests.common import db_mock

from radicalbit_ai_gateway.models.project_dto import ConfigListFilter
from radicalbit_ai_gateway.routes.configs_route import ConfigsRoute, ConfigsRouteConfig
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.utils.exceptions import (
    AuthRegistryError,
    auth_registry_exception_handler,
)


class TestConfigsRoute(unittest.TestCase):
    def setUp(self):
        self.prefix = '/public/api/v1'
        self.project_service = MagicMock(spec_set=ProjectService)
        router = ConfigsRoute.get_configs_router(self.project_service)
        app = FastAPI(title='AI Gateway', debug=True)
        app.include_router(router, prefix=self.prefix)
        self.client = TestClient(app)

    def test_get_configs_no_filter(self):
        out = db_mock.get_sample_project_out()
        self.project_service.get_configs = MagicMock(return_value=[out])
        res = self.client.get(f'{self.prefix}/configs/projects')
        assert res.status_code == 200
        assert res.json() == jsonable_encoder([out])
        self.project_service.get_configs.assert_called_once_with(None)

    def test_get_configs_with_status(self):
        out = db_mock.get_sample_project_out()
        self.project_service.get_configs = MagicMock(return_value=[out])
        res = self.client.get(
            f'{self.prefix}/configs/projects', params={'status': 'published'}
        )
        assert res.status_code == 200
        self.project_service.get_configs.assert_called_once_with(
            ConfigListFilter.PUBLISHED
        )

    def test_get_configs_invalid_status(self):
        res = self.client.get(
            f'{self.prefix}/configs/projects', params={'status': 'nope'}
        )
        assert res.status_code == 422

    def test_get_configs_uses_override_fn(self):
        # When a ConfigsRouteConfig with a custom get_configs_fn is provided
        # (as the EE plugin does), the route delegates to it, passing the
        # request and the parsed status filter.
        out = db_mock.get_sample_project_out()
        captured = {}

        def custom_fn(request: Request, status):
            captured['is_request'] = isinstance(request, Request)
            captured['status'] = status
            return [out]

        router = ConfigsRoute.get_configs_router(
            MagicMock(spec_set=ProjectService),
            config=ConfigsRouteConfig(get_configs_fn=custom_fn),
        )
        app = FastAPI(debug=True)
        app.include_router(router, prefix=self.prefix)
        client = TestClient(app)

        res = client.get(f'{self.prefix}/configs/projects', params={'status': 'draft'})
        assert res.status_code == 200
        assert res.json() == jsonable_encoder([out])
        assert captured['is_request'] is True
        assert captured['status'] == ConfigListFilter.DRAFT


class TestValidateConfigRoute(unittest.TestCase):
    def setUp(self):
        self.prefix = '/public/api/v1'
        self.project_service = MagicMock(spec_set=ProjectService)
        router = ConfigsRoute.get_configs_router(self.project_service)
        app = FastAPI(debug=True)
        app.add_exception_handler(AuthRegistryError, auth_registry_exception_handler)
        app.include_router(router, prefix=self.prefix)
        self.client = TestClient(app)

    def _validate(self, config_file: str):
        return self.client.post(
            f'{self.prefix}/configs/validate', json={'configFile': config_file}
        )

    def test_valid_config(self):
        res = self._validate(db_mock.VALID_CONFIG_YAML)
        assert res.status_code == 200
        assert res.json() == {'valid': True}
        # A dry run: no project, nothing saved
        assert self.project_service.mock_calls == []

    def test_secrets_are_not_checked(self):
        # A literal key would fail a save, not the schema
        config = db_mock.VALID_CONFIG_YAML.replace(
            '    params:\n',
            '    credentials:\n      api_key: sk-literal\n    params:\n',
        )
        assert self._validate(config).status_code == 200

    def test_invalid_config_has_structured_details(self):
        res = self._validate('routes:\n  r:\n    chat_models:\n      - nope\n')
        assert res.status_code == 400
        error = res.json()['error']
        assert error['code'] == 'project_config_validation_error'
        assert error['message'].startswith('Invalid gateway configuration')
        assert error['details']
        assert {'loc', 'msg', 'type'} == set(error['details'][0])
        assert all(isinstance(d['loc'], list) for d in error['details'])
        assert self.project_service.mock_calls == []

    def test_yaml_syntax_error_is_one_detail(self):
        res = self._validate('routes: [unclosed')
        assert res.status_code == 400
        error = res.json()['error']
        assert error['message'].startswith('Invalid YAML')
        assert error['details'] == [
            {'loc': [], 'msg': error['message'], 'type': 'yaml_syntax_error'}
        ]
