import unittest
from unittest.mock import MagicMock
from uuid import UUID

from fastapi import FastAPI
from starlette.testclient import TestClient

from radicalbit_ai_gateway.models.tag_dto import TagKeysDTO, TagKeyValuesDTO
from radicalbit_ai_gateway.routes.tag_route import TagRoute
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.services.request_event_service import RequestEventService
from radicalbit_ai_gateway.utils.exceptions import (
    ProjectNotFoundError,
    auth_registry_exception_handler,
)

PROJECT_UUID = UUID('22222222-2222-2222-2222-222222222222')
PROJECT_NAME = 'test-project'


class TestTagRoute(unittest.TestCase):
    def setUp(self):
        self.prefix = '/public/api/v1'
        self.request_event_service: RequestEventService = MagicMock(
            spec_set=RequestEventService
        )
        self.project_service: ProjectService = MagicMock(spec_set=ProjectService)

        project_mock = MagicMock()
        project_mock.name = PROJECT_NAME
        self.project_service.get_by_uuid = MagicMock(return_value=project_mock)

        router = TagRoute.get_tag_router(
            request_event_service=self.request_event_service,
            project_service=self.project_service,
        )
        app = FastAPI(title='AI Gateway', debug=True)
        app.add_exception_handler(ProjectNotFoundError, auth_registry_exception_handler)
        app.include_router(router, prefix=self.prefix)
        self.client = TestClient(app)
        self.project_path = f'{self.prefix}/projects/{PROJECT_UUID}'

    def test_get_tag_keys(self):
        expected = TagKeysDTO(tag_keys=['app', 'cost_center', 'env'])
        self.request_event_service.get_tag_keys = MagicMock(return_value=expected)
        response = self.client.get(f'{self.project_path}/tags/keys')
        assert response.status_code == 200
        assert response.json() == {'tagKeys': ['app', 'cost_center', 'env']}
        self.request_event_service.get_tag_keys.assert_called_once_with(PROJECT_UUID)

    def test_get_tag_keys_empty(self):
        expected = TagKeysDTO(tag_keys=[])
        self.request_event_service.get_tag_keys = MagicMock(return_value=expected)
        response = self.client.get(f'{self.project_path}/tags/keys')
        assert response.status_code == 200
        assert response.json() == {'tagKeys': []}

    def test_get_tag_keys_project_not_found(self):
        self.request_event_service.get_tag_keys = MagicMock()
        self.project_service.get_by_uuid = MagicMock(
            side_effect=ProjectNotFoundError('nope')
        )
        response = self.client.get(f'{self.project_path}/tags/keys')
        assert response.status_code == 404
        assert response.json()['error']['code'] == 'project_not_found'
        self.request_event_service.get_tag_keys.assert_not_called()

    def test_get_tag_key_values(self):
        expected = TagKeyValuesDTO(tag_values=['prod', 'staging'])
        self.request_event_service.get_tag_key_values = MagicMock(return_value=expected)
        response = self.client.get(f'{self.project_path}/tags/keys/env/values')
        assert response.status_code == 200
        assert response.json() == {'tagValues': ['prod', 'staging']}
        self.request_event_service.get_tag_key_values.assert_called_once_with(
            PROJECT_UUID, 'env'
        )

    def test_get_tag_key_values_empty(self):
        expected = TagKeyValuesDTO(tag_values=[])
        self.request_event_service.get_tag_key_values = MagicMock(return_value=expected)
        response = self.client.get(f'{self.project_path}/tags/keys/unknown/values')
        assert response.status_code == 200
        assert response.json() == {'tagValues': []}

    def test_get_tag_key_values_project_not_found(self):
        self.request_event_service.get_tag_key_values = MagicMock()
        self.project_service.get_by_uuid = MagicMock(
            side_effect=ProjectNotFoundError('nope')
        )
        response = self.client.get(f'{self.project_path}/tags/keys/env/values')
        assert response.status_code == 404
        assert response.json()['error']['code'] == 'project_not_found'
        self.request_event_service.get_tag_key_values.assert_not_called()
