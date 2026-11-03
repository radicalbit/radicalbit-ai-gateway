import datetime
import unittest
from unittest.mock import MagicMock
import uuid
from uuid import UUID

from fastapi import FastAPI
from starlette.testclient import TestClient

from radicalbit_ai_gateway.models.request_dto import RequestDetailDTO, RequestEventDTO
from radicalbit_ai_gateway.models.request_event_type import RequestStatus
from radicalbit_ai_gateway.routes.requests_route import RequestsRoute
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.services.requests_service import RequestsService
from radicalbit_ai_gateway.utils.exceptions import (
    AuthRegistryError,
    GatewayError,
    GatewayNotFoundError,
    ProjectNotFoundError,
    auth_registry_exception_handler,
    gateway_exception_handler,
)

PROJECT_UUID = UUID('11111111-1111-1111-1111-111111111111')
PREFIX = '/public/api/v1'


class TestRequestDetailRoute(unittest.TestCase):
    def setUp(self):
        self.requests_service = MagicMock(spec_set=RequestsService)
        self.project_service = MagicMock(spec_set=ProjectService)
        app = FastAPI()
        app.add_exception_handler(GatewayError, gateway_exception_handler)
        app.add_exception_handler(AuthRegistryError, auth_registry_exception_handler)
        app.include_router(
            RequestsRoute.get_requests_router(
                requests_service=self.requests_service,
                project_service=self.project_service,
            ),
            prefix=PREFIX,
        )
        self.client = TestClient(app)
        self.request_uuid = uuid.uuid4()
        self.url = f'{PREFIX}/projects/{PROJECT_UUID}/requests/{self.request_uuid}'

    def test_returns_the_request_detail_in_camel_case(self):
        self.requests_service.get_request.return_value = RequestDetailDTO(
            request_uuid=self.request_uuid,
            route_name='route-a',
            request_status=RequestStatus.HANDLED_ERROR,
            http_status_code=429,
            error_type='RateLimitExceededError',
            error_code='rate_limit_exceeded',
            duration_ms=3.5,
            created_at=1773144000,
            events=[
                RequestEventDTO(
                    event_type='RATE_LIMIT',
                    timestamp=datetime.datetime(2026, 3, 10, tzinfo=datetime.UTC),
                    value=1,
                    cost=0,
                    blocking=True,
                )
            ],
        )

        response = self.client.get(self.url)

        assert response.status_code == 200
        self.project_service.validate_exists.assert_called_once_with(PROJECT_UUID)
        self.requests_service.get_request.assert_called_once_with(
            project_uuid=PROJECT_UUID, request_uuid=self.request_uuid
        )
        body = response.json()
        assert body['requestUuid'] == str(self.request_uuid)
        assert body['traceId'] is None
        assert body['errorCode'] == 'rate_limit_exceeded'
        [event] = body['events']
        assert event['eventType'] == 'RATE_LIMIT'
        assert event['blocking'] is True

    def test_an_unknown_request_is_404(self):
        self.requests_service.get_request.side_effect = GatewayNotFoundError(
            f"Request '{self.request_uuid}' not found"
        )

        response = self.client.get(self.url)

        assert response.status_code == 404
        assert 'not found' in response.json()['error']['message']

    def test_an_unknown_project_is_404(self):
        self.project_service.validate_exists.side_effect = ProjectNotFoundError(
            'Project not found'
        )

        response = self.client.get(self.url)

        assert response.status_code == 404
        self.requests_service.get_request.assert_not_called()

    def test_a_malformed_request_uuid_is_422(self):
        response = self.client.get(f'{PREFIX}/projects/{PROJECT_UUID}/requests/nope')

        assert response.status_code == 422
