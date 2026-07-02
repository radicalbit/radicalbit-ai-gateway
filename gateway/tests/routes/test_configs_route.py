import unittest
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from starlette.testclient import TestClient

from tests.common import db_mock

from radicalbit_ai_gateway.models.project_dto import ConfigListFilter
from radicalbit_ai_gateway.routes.configs_route import ConfigsRoute
from radicalbit_ai_gateway.services.project_service import ProjectService


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
