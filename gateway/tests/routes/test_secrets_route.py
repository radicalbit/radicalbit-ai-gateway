import unittest
from unittest.mock import MagicMock
import uuid

from fastapi import FastAPI, Request
from starlette.testclient import TestClient

from radicalbit_ai_gateway.models.secret_dto import ProjectRef, SecretOut
from radicalbit_ai_gateway.routes.secrets_route import SecretsRoute, SecretsRouteConfig
from radicalbit_ai_gateway.services.secret_service import SecretService


class TestSecretsRoute(unittest.TestCase):
    def setUp(self):
        self.prefix = '/public/api/v1'
        self.secret_service = MagicMock(spec_set=SecretService)
        router = SecretsRoute.get_secrets_router(self.secret_service)
        app = FastAPI(title='AI Gateway', debug=True)
        app.include_router(router, prefix=self.prefix)
        self.client = TestClient(app)

    def test_get_secrets_returns_paginated_envelope(self):
        self.secret_service.get_secrets = MagicMock(
            return_value=[SecretOut(key='ALPHA'), SecretOut(key='BRAVO')]
        )

        res = self.client.get(f'{self.prefix}/secrets')

        assert res.status_code == 200
        assert res.json() == {
            'items': [
                {'key': 'ALPHA', 'usedIn': []},
                {'key': 'BRAVO', 'usedIn': []},
            ],
            'total': 2,
            'page': 1,
            'size': 50,
            'pages': 1,
        }
        self.secret_service.get_secrets.assert_called_once_with()

    def test_get_secrets_never_returns_a_value(self):
        self.secret_service.get_secrets = MagicMock(
            return_value=[SecretOut(key='OPENAI_API_KEY')]
        )

        res = self.client.get(f'{self.prefix}/secrets')

        assert res.status_code == 200
        assert res.json()['items'] == [{'key': 'OPENAI_API_KEY', 'usedIn': []}]

    def test_get_secrets_includes_used_in_projects(self):
        project_uuid = uuid.uuid4()
        self.secret_service.get_secrets = MagicMock(
            return_value=[
                SecretOut(
                    key='OPENAI_API_KEY',
                    used_in=[ProjectRef(uuid=project_uuid, name='project-a')],
                )
            ]
        )

        res = self.client.get(f'{self.prefix}/secrets')

        assert res.status_code == 200
        assert res.json()['items'] == [
            {
                'key': 'OPENAI_API_KEY',
                'usedIn': [{'uuid': str(project_uuid), 'name': 'project-a'}],
            }
        ]

    def test_get_secrets_applies_page_and_limit(self):
        self.secret_service.get_secrets = MagicMock(
            return_value=[SecretOut(key=k) for k in ['ALPHA', 'BRAVO', 'CHARLIE']]
        )

        res = self.client.get(
            f'{self.prefix}/secrets', params={'_page': 2, '_limit': 2}
        )

        assert res.status_code == 200
        body = res.json()
        assert body['items'] == [{'key': 'CHARLIE', 'usedIn': []}]
        assert body['total'] == 3
        assert body['page'] == 2
        assert body['size'] == 2
        assert body['pages'] == 2

    def test_get_secrets_page_below_bound(self):
        res = self.client.get(f'{self.prefix}/secrets', params={'_page': 0})
        assert res.status_code == 422

    def test_get_secrets_limit_below_bound(self):
        res = self.client.get(f'{self.prefix}/secrets', params={'_limit': 0})
        assert res.status_code == 422

    def test_get_secrets_limit_above_bound(self):
        res = self.client.get(f'{self.prefix}/secrets', params={'_limit': 101})
        assert res.status_code == 422

    def test_get_secrets_uses_override_fn(self):
        # When a SecretsRouteConfig with a custom get_secrets_fn is provided
        # (as the EE plugin does), the route delegates to it, passing the
        # request so the rows can be filtered by the caller's memberships.
        captured = {}

        def custom_fn(request: Request, search):
            captured['is_request'] = isinstance(request, Request)
            captured['search'] = search
            return [SecretOut(key='FROM_OVERRIDE')]

        service = MagicMock(spec_set=SecretService)
        router = SecretsRoute.get_secrets_router(
            service, config=SecretsRouteConfig(get_secrets_fn=custom_fn)
        )
        app = FastAPI(debug=True)
        app.include_router(router, prefix=self.prefix)
        client = TestClient(app)

        res = client.get(f'{self.prefix}/secrets')

        assert res.status_code == 200
        assert res.json()['items'] == [{'key': 'FROM_OVERRIDE', 'usedIn': []}]
        assert captured['is_request'] is True
        assert captured['search'] is None
        service.get_secrets.assert_not_called()
