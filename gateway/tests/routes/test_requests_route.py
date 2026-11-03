import datetime
import unittest
from unittest.mock import MagicMock
import uuid
from uuid import UUID

from fastapi import FastAPI
from fastapi_pagination import Page, Params
from starlette.testclient import TestClient

from radicalbit_ai_gateway.models.request_dto import RequestDTO
from radicalbit_ai_gateway.models.request_event_type import RequestStatus, RequestType
from radicalbit_ai_gateway.routes.requests_route import RequestsRoute
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.services.requests_service import RequestsService
from radicalbit_ai_gateway.utils.exceptions import (
    AuthRegistryError,
    GatewayError,
    ProjectNotFoundError,
    auth_registry_exception_handler,
    gateway_exception_handler,
)

PROJECT_UUID = UUID('11111111-1111-1111-1111-111111111111')


def _empty_page(page: int = 1, size: int = 50) -> Page:
    return Page.create(items=[], params=Params(page=page, size=size), total=0)


class TestRequestsRoute(unittest.TestCase):
    def setUp(self):
        prefix = '/public/api/v1'
        self.requests_service = MagicMock(spec_set=RequestsService)
        self.project_service = MagicMock(spec_set=ProjectService)
        router = RequestsRoute.get_requests_router(
            requests_service=self.requests_service,
            project_service=self.project_service,
        )
        app = FastAPI()
        app.add_exception_handler(GatewayError, gateway_exception_handler)
        app.add_exception_handler(AuthRegistryError, auth_registry_exception_handler)
        app.include_router(router, prefix=prefix)
        self.client = TestClient(app)
        self.url = f'{prefix}/projects/{PROJECT_UUID}/requests'

    def test_returns_the_page_in_camel_case_with_a_null_trace_id(self):
        request_uuid = uuid.uuid4()
        self.requests_service.get_requests.return_value = Page.create(
            items=[
                RequestDTO(
                    request_uuid=request_uuid,
                    route_name='route-a',
                    request_type=RequestType.CHAT_COMPLETIONS,
                    request_status=RequestStatus.HANDLED_ERROR,
                    http_status_code=422,
                    error_type='RequestValidationError',
                    duration_ms=3.5,
                    created_at=1773144000,
                    total_tokens=12,
                    cost=0.25,
                )
            ],
            params=Params(page=1, size=50),
            total=1,
        )

        response = self.client.get(self.url)

        assert response.status_code == 200
        body = response.json()
        assert body['total'] == 1
        [item] = body['items']
        assert item['requestUuid'] == str(request_uuid)
        assert item['traceId'] is None
        assert item['requestStatus'] == 'handled_error'
        assert item['httpStatusCode'] == 422
        assert item['errorType'] == 'RequestValidationError'
        assert item['durationMs'] == 3.5
        assert item['createdAt'] == 1773144000
        assert item['totalTokens'] == 12
        assert item['cost'] == 0.25

    def test_defaults(self):
        self.requests_service.get_requests.return_value = _empty_page()

        response = self.client.get(self.url)

        assert response.status_code == 200
        self.project_service.validate_exists.assert_called_once_with(PROJECT_UUID)
        kwargs = self.requests_service.get_requests.call_args.kwargs
        assert kwargs['project_uuid'] == PROJECT_UUID
        assert kwargs['route_names'] is None
        assert kwargs['group_uuids'] is None
        assert kwargs['key_uuids'] is None
        assert kwargs['_from'] is None
        assert kwargs['_to'] is None
        assert kwargs['tags'] is None
        assert kwargs['request_types'] is None
        assert kwargs['params'] == Params(page=1, size=50)

    def test_parses_filters_and_pagination(self):
        self.requests_service.get_requests.return_value = _empty_page(3, 10)
        _from = datetime.datetime(2026, 3, 10, 10, tzinfo=datetime.timezone.utc)
        _to = _from + datetime.timedelta(hours=2)
        group, key = uuid.uuid4(), uuid.uuid4()

        response = self.client.get(
            self.url,
            params={
                '_from': int(_from.timestamp()),
                '_to': int(_to.timestamp()),
                '_page': 3,
                '_limit': 10,
                'routes': ['route-a', 'route-b'],
                'groups': [str(group)],
                'keys': [str(key)],
                'requestType': ['mcp', 'embeddings'],
                'tags': ['env=prod', 'team=a'],
            },
        )

        assert response.status_code == 200
        kwargs = self.requests_service.get_requests.call_args.kwargs
        assert kwargs['_from'] == _from
        assert kwargs['_to'] == _to
        assert kwargs['params'] == Params(page=3, size=10)
        assert kwargs['route_names'] == ['route-a', 'route-b']
        assert kwargs['group_uuids'] == [group]
        assert kwargs['key_uuids'] == [key]
        assert kwargs['request_types'] == [RequestType.MCP, RequestType.EMBEDDINGS]
        assert kwargs['tags'] == ['env=prod', 'team=a']

    def test_rejects_bad_query_parameters(self):
        for params in (
            {'requestType': ['llm']},
            {'_limit': 101},
            {'_page': 0},
            {'groups': ['not-a-uuid']},
        ):
            response = self.client.get(self.url, params=params)
            assert response.status_code == 422, params
        self.requests_service.get_requests.assert_not_called()

    def test_unknown_project_is_404(self):
        self.project_service.validate_exists.side_effect = ProjectNotFoundError(
            'Project not found'
        )

        response = self.client.get(self.url)

        assert response.status_code == 404
        self.requests_service.get_requests.assert_not_called()
