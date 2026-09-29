import unittest
from unittest.mock import MagicMock
import uuid

from fastapi import FastAPI, Request
from starlette.testclient import TestClient

from radicalbit_ai_gateway.models.secret_dto import ProjectRef, SecretOut, SecretStatus
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
                {'key': 'ALPHA', 'usedIn': [], 'status': None},
                {'key': 'BRAVO', 'usedIn': [], 'status': None},
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
        assert res.json()['items'] == [
            {'key': 'OPENAI_API_KEY', 'usedIn': [], 'status': None}
        ]

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
                'status': None,
            }
        ]

    def test_get_secrets_marks_an_unavailable_key(self):
        project_uuid = uuid.uuid4()
        self.secret_service.get_secrets = MagicMock(
            return_value=[
                SecretOut(
                    key='DEAD_TOKEN',
                    used_in=[ProjectRef(uuid=project_uuid, name='project-c')],
                    status=SecretStatus.UNAVAILABLE,
                ),
                SecretOut(key='OPENAI_API_KEY'),
            ]
        )

        res = self.client.get(f'{self.prefix}/secrets')

        assert res.status_code == 200
        assert res.json()['items'] == [
            {
                'key': 'DEAD_TOKEN',
                'usedIn': [{'uuid': str(project_uuid), 'name': 'project-c'}],
                'status': 'unavailable',
            },
            {'key': 'OPENAI_API_KEY', 'usedIn': [], 'status': None},
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
        assert body['items'] == [{'key': 'CHARLIE', 'usedIn': [], 'status': None}]
        assert body['total'] == 3
        assert body['page'] == 2
        assert body['size'] == 2
        assert body['pages'] == 2

    def test_get_secrets_keeps_order_across_page_turns(self):
        dead = [
            SecretOut(key=k, status=SecretStatus.UNAVAILABLE)
            for k in ['BRAVO_DEAD', 'ZULU_DEAD']
        ]
        self.secret_service.get_secrets = MagicMock(
            return_value=[*dead, SecretOut(key='ALPHA'), SecretOut(key='MIKE')]
        )

        pages = [
            self.client.get(
                f'{self.prefix}/secrets', params={'_page': page, '_limit': 3}
            ).json()['items']
            for page in (1, 2)
        ]

        assert [(row['key'], row['status']) for row in pages[0]] == [
            ('BRAVO_DEAD', 'unavailable'),
            ('ZULU_DEAD', 'unavailable'),
            ('ALPHA', None),
        ]
        assert [(row['key'], row['status']) for row in pages[1]] == [('MIKE', None)]

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
        assert res.json()['items'] == [
            {'key': 'FROM_OVERRIDE', 'usedIn': [], 'status': None}
        ]
        assert captured['is_request'] is True
        assert captured['search'] is None
        service.get_secrets.assert_not_called()
