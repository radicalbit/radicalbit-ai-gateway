import unittest
from unittest.mock import MagicMock
import uuid

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from starlette.testclient import TestClient

from tests.common import db_mock

from radicalbit_ai_gateway.models.auth_dto import GroupFullOut, KeyFullOut
from radicalbit_ai_gateway.routes.key_route import KeyRoute
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.utils.exceptions import (
    AuthRegistryError,
    ErrorOut,
    KeyInternalError,
    KeyNotFoundError,
    auth_registry_exception_handler,
)


class TestKeyRoute(unittest.TestCase):
    def setUp(self):
        self.prefix = '/public/api/v1'
        self.key_service = MagicMock(spec_set=KeyService)
        router = KeyRoute.get_key_router(self.key_service)
        app = FastAPI(title='AI Gateway', debug=True)
        app.add_exception_handler(AuthRegistryError, auth_registry_exception_handler)
        app.include_router(router, prefix=self.prefix)

        self.client = TestClient(app)

    def test_create_key(self):
        key_in = db_mock.get_sample_key_in()
        key = db_mock.get_sample_key()
        key_out = KeyFullOut.from_key_obscured(key)
        self.key_service.create_key = MagicMock(return_value=key_out)
        res = self.client.post(f'{self.prefix}/keys', json=jsonable_encoder(key_in))
        assert res.status_code == 201
        assert res.json() == jsonable_encoder(key_out)
        self.key_service.create_key.assert_called_once_with(key_in)

    def test_exception_handler_key_internal_error(self):
        key_in = db_mock.get_sample_key_in()
        self.key_service.create_key = MagicMock(side_effect=KeyInternalError('error'))
        res = self.client.post(
            f'{self.prefix}/keys',
            json=jsonable_encoder(key_in),
        )
        assert res.status_code == 500
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='key_internal_error', param=None
            ).error
        )
        self.key_service.create_key.assert_called_once_with(key_in)

    def test_get_all(self):
        api_keys = [
            KeyFullOut.from_key_obscured(
                db_mock.get_sample_key(uuid=uuid.uuid4(), name='one')
            ),
            KeyFullOut.from_key_obscured(
                db_mock.get_sample_key(uuid=uuid.uuid4(), name='two')
            ),
            KeyFullOut.from_key_obscured(
                db_mock.get_sample_key(uuid=uuid.uuid4(), name='three')
            ),
        ]
        self.key_service.get_all = MagicMock(return_value=api_keys)
        res = self.client.get(f'{self.prefix}/keys')
        assert res.status_code == 200
        assert jsonable_encoder(api_keys) == res.json()
        self.key_service.get_all.assert_called_once()

    def test_delete_key(self):
        key = db_mock.get_sample_key()
        key_out = KeyFullOut.from_key_obscured(key)
        self.key_service.delete_key = MagicMock(return_value=key_out)
        res = self.client.delete(f'{self.prefix}/keys/{db_mock.RANDOM_UUID}')
        assert res.status_code == 200
        assert res.json() == jsonable_encoder(key_out)
        self.key_service.delete_key.assert_called_once_with(db_mock.RANDOM_UUID, False)

    def test_delete_key_ko(self):
        self.key_service.delete_key = MagicMock(side_effect=KeyInternalError('error'))
        res = self.client.delete(f'{self.prefix}/keys/{db_mock.RANDOM_UUID}')
        assert res.status_code == 500
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='key_internal_error', param=None
            ).error
        )
        self.key_service.delete_key.assert_called_once_with(db_mock.RANDOM_UUID, False)

    def test_delete_missing_key(self):
        self.key_service.delete_key = MagicMock(side_effect=KeyNotFoundError('error'))
        res = self.client.delete(f'{self.prefix}/keys/{db_mock.RANDOM_UUID}')
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='key_not_found', param=None
            ).error
        )
        self.key_service.delete_key.assert_called_once_with(db_mock.RANDOM_UUID, False)

    def test_get_key_by_uuid(self):
        key = db_mock.get_sample_key()
        key_out = KeyFullOut.from_key_obscured(key)
        self.key_service.get_key_by_uuid = MagicMock(return_value=key_out)
        res = self.client.get(f'{self.prefix}/keys/{key.uuid}')
        assert res.status_code == 200
        assert jsonable_encoder(key_out) == res.json()
        self.key_service.get_key_by_uuid.assert_called_once_with(key.uuid, False)

    def test_get_missing_key_by_uuid(self):
        key = db_mock.get_sample_key()
        self.key_service.get_key_by_uuid = MagicMock(
            side_effect=KeyNotFoundError('error')
        )
        res = self.client.get(f'{self.prefix}/keys/{key.uuid}')
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='key_not_found', param=None
            ).error
        )
        self.key_service.get_key_by_uuid.assert_called_once_with(key.uuid, False)

    def test_update_key_name(self):
        key_in = db_mock.get_sample_key_in()
        key = db_mock.get_sample_key()
        key_out = KeyFullOut.from_key_obscured(key)
        self.key_service.update_key_name = MagicMock(return_value=key_out)
        res = self.client.patch(
            f'{self.prefix}/keys/{key.uuid}', json=jsonable_encoder(key_in)
        )
        assert res.status_code == 200
        assert jsonable_encoder(key_out) == res.json()
        self.key_service.update_key_name.assert_called_once_with(key.uuid, key_in)

    def test_update_key_name_ko(self):
        key_in = db_mock.get_sample_key_in()
        key = db_mock.get_sample_key()
        self.key_service.update_key_name = MagicMock(
            side_effect=KeyInternalError('error')
        )
        res = self.client.patch(
            f'{self.prefix}/keys/{key.uuid}', json=jsonable_encoder(key_in)
        )
        assert res.status_code == 500
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='key_internal_error', param=None
            ).error
        )
        self.key_service.update_key_name.assert_called_once_with(key.uuid, key_in)

    def test_update_missing_key(self):
        key_in = db_mock.get_sample_key_in()
        key = db_mock.get_sample_key()
        self.key_service.update_key_name = MagicMock(
            side_effect=KeyNotFoundError('error')
        )
        res = self.client.patch(
            f'{self.prefix}/keys/{key.uuid}', json=jsonable_encoder(key_in)
        )
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='key_not_found', param=None
            ).error
        )
        self.key_service.update_key_name.assert_called_once_with(key.uuid, key_in)

    def test_add_group_to_key_success(self):
        key = db_mock.get_sample_key()
        key_group_in = db_mock.get_sample_key_group_in()
        key_out = db_mock.get_sample_key_full_out()
        self.key_service.add_group_to_key = MagicMock(return_value=key_out)
        res = self.client.patch(
            f'{self.prefix}/keys/{key.uuid}/group?include_groups=True',
            json=jsonable_encoder(key_group_in),
        )
        assert res.status_code == 200
        assert res.json() == jsonable_encoder(key_out)

    def test_add_group_to_key_success_no_group(self):
        key = db_mock.get_sample_key()
        key_group_in = db_mock.get_sample_key_group_in()
        key_out = db_mock.get_sample_key_full_out()
        del key_out.group
        self.key_service.add_group_to_key = MagicMock(return_value=key_out)
        res = self.client.patch(
            f'{self.prefix}/keys/{key.uuid}/group',
            json=jsonable_encoder(key_group_in),
        )
        assert res.status_code == 200
        assert res.json() == jsonable_encoder(key_out)

    def test_get_associable_groups(self):
        key = db_mock.get_sample_key()
        groups_out = [
            GroupFullOut.from_group(
                db_mock.get_sample_group(uuid=uuid.uuid4(), name='g1')
            ),
            GroupFullOut.from_group(
                db_mock.get_sample_group(uuid=uuid.uuid4(), name='g2')
            ),
        ]
        self.key_service.get_associable_groups = MagicMock(return_value=groups_out)
        res = self.client.get(f'{self.prefix}/keys/{key.uuid}/associable-groups')
        assert res.status_code == 200
        assert jsonable_encoder(groups_out) == res.json()
        self.key_service.get_associable_groups.assert_called_once_with(
            key.uuid, False, False
        )

    def test_get_associable_groups_with_includes(self):
        key = db_mock.get_sample_key()
        group_route = db_mock.get_sample_group_route()
        groups_out = [
            GroupFullOut.from_group(
                db_mock.get_sample_group(uuid=uuid.uuid4(), group_routes=[group_route]),
                include_routes=True,
                include_keys=True,
            )
        ]
        self.key_service.get_associable_groups = MagicMock(return_value=groups_out)
        res = self.client.get(
            f'{self.prefix}/keys/{key.uuid}/associable-groups?include_routes=true&include_keys=true'
        )
        assert res.status_code == 200
        assert jsonable_encoder(groups_out) == res.json()
        self.key_service.get_associable_groups.assert_called_once_with(
            key.uuid, True, True
        )

    def test_get_associable_groups_empty(self):
        key = db_mock.get_sample_key()
        self.key_service.get_associable_groups = MagicMock(return_value=[])
        res = self.client.get(f'{self.prefix}/keys/{key.uuid}/associable-groups')
        assert res.status_code == 200
        assert res.json() == []
        self.key_service.get_associable_groups.assert_called_once_with(
            key.uuid, False, False
        )

    def test_get_associable_groups_key_not_found(self):
        key = db_mock.get_sample_key()
        self.key_service.get_associable_groups = MagicMock(
            side_effect=KeyNotFoundError('error')
        )
        res = self.client.get(f'{self.prefix}/keys/{key.uuid}/associable-groups')
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='key_not_found', param=None
            ).error
        )
        self.key_service.get_associable_groups.assert_called_once_with(
            key.uuid, False, False
        )
