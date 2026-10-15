import asyncio
import datetime
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from freezegun import freeze_time
from starlette.testclient import TestClient

from tests.common import db_mock

from radicalbit_ai_gateway.db.dao.group_dao import GroupDAO
from radicalbit_ai_gateway.db.dao.group_limit_dao import GroupLimitDAO
from radicalbit_ai_gateway.db.dao.key_dao import KeyDAO
from radicalbit_ai_gateway.db.dao.key_limit_dao import KeyLimitDAO
from radicalbit_ai_gateway.models.auth_dto import GroupFullOut, KeyCreateIn, KeyFullOut
from radicalbit_ai_gateway.models.credential_limiting import CredentialLimitOut
from radicalbit_ai_gateway.routes.key_route import KeyRoute
from radicalbit_ai_gateway.server import validation_exception_handler
from radicalbit_ai_gateway.services.api_key_security import ApiKeySecurity
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.utils.exceptions import (
    AuthRegistryError,
    CredentialLimitNotFoundError,
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
        key_in = db_mock.get_sample_key_create_in()
        key = db_mock.get_sample_key()
        key_out = KeyFullOut.from_key_obscured(key)
        self.key_service.create_key = MagicMock(return_value=key_out)
        res = self.client.post(f'{self.prefix}/keys', json=jsonable_encoder(key_in))
        assert res.status_code == 201
        assert res.json() == jsonable_encoder(key_out)
        self.key_service.create_key.assert_called_once_with(key_in)

    def test_exception_handler_key_internal_error(self):
        key_in = db_mock.get_sample_key_create_in()
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
        self.key_service.get_key_by_uuid.assert_called_once_with(key.uuid, False, False)

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
        self.key_service.get_key_by_uuid.assert_called_once_with(key.uuid, False, False)

    def test_update_key_name(self):
        key_in = db_mock.get_sample_key_update_in()
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
        key_in = db_mock.get_sample_key_update_in()
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
        key_in = db_mock.get_sample_key_update_in()
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

    def test_add_limits_to_key_success(self):
        key = db_mock.get_sample_key()
        limits_in = db_mock.get_sample_credential_limits_in()
        key_out = db_mock.get_sample_key_full_out()
        self.key_service.add_limits_to_key = MagicMock(return_value=key_out)
        res = self.client.post(
            f'{self.prefix}/keys/{key.uuid}/limits',
            json=jsonable_encoder(limits_in),
        )
        assert res.status_code == 201
        assert res.json() == jsonable_encoder(key_out)
        self.key_service.add_limits_to_key.assert_called_once_with(
            key.uuid, limits_in, False
        )

    def test_add_limits_to_key_not_found(self):
        key = db_mock.get_sample_key()
        limits_in = db_mock.get_sample_credential_limits_in()
        self.key_service.add_limits_to_key = MagicMock(
            side_effect=KeyNotFoundError('error')
        )
        res = self.client.post(
            f'{self.prefix}/keys/{key.uuid}/limits',
            json=jsonable_encoder(limits_in),
        )
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='key_not_found', param=None
            ).error
        )

    def test_get_limits_for_key_success(self):
        key = db_mock.get_sample_key()
        limit_out = CredentialLimitOut.from_key_limit(
            db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        )
        self.key_service.get_limits_for_key = MagicMock(return_value=[limit_out])
        res = self.client.get(f'{self.prefix}/keys/{key.uuid}/limits')
        assert res.status_code == 200
        assert res.json() == jsonable_encoder([limit_out])
        self.key_service.get_limits_for_key.assert_called_once_with(key.uuid)

    def test_get_limits_for_key_not_found(self):
        key = db_mock.get_sample_key()
        self.key_service.get_limits_for_key = MagicMock(
            side_effect=KeyNotFoundError('error')
        )
        res = self.client.get(f'{self.prefix}/keys/{key.uuid}/limits')
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='key_not_found', param=None
            ).error
        )

    def test_delete_limit_from_key_success(self):
        key = db_mock.get_sample_key()
        limit_out = CredentialLimitOut.from_key_limit(
            db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        )
        self.key_service.delete_limit_from_key = AsyncMock(return_value=limit_out)
        res = self.client.delete(
            f'{self.prefix}/keys/{key.uuid}/limits/{limit_out.uuid}'
        )
        assert res.status_code == 200
        assert res.json() == jsonable_encoder(limit_out)
        self.key_service.delete_limit_from_key.assert_awaited_once_with(
            key.uuid, limit_out.uuid
        )

    def test_delete_limit_from_key_not_found(self):
        key = db_mock.get_sample_key()
        self.key_service.delete_limit_from_key = AsyncMock(
            side_effect=CredentialLimitNotFoundError('error')
        )
        res = self.client.delete(f'{self.prefix}/keys/{key.uuid}/limits/{uuid.uuid4()}')
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error',
                'auth_registry_error',
                code='credential_limit_not_found',
                param=None,
            ).error
        )

    def test_delete_limit_from_key_key_not_found(self):
        self.key_service.delete_limit_from_key = AsyncMock(
            side_effect=KeyNotFoundError('error')
        )
        res = self.client.delete(
            f'{self.prefix}/keys/{uuid.uuid4()}/limits/{uuid.uuid4()}'
        )
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='key_not_found', param=None
            ).error
        )


class TestKeyRouteExpiry(unittest.TestCase):
    """Expiry date on create, and expiresOn/state on every read."""

    def setUp(self):
        self.prefix = '/public/api/v1'
        self.key_service = MagicMock(spec_set=KeyService)
        router = KeyRoute.get_key_router(self.key_service)
        app = FastAPI(title='AI Gateway', debug=True)
        app.add_exception_handler(AuthRegistryError, auth_registry_exception_handler)
        app.add_exception_handler(RequestValidationError, validation_exception_handler)
        app.include_router(router, prefix=self.prefix)
        self.client = TestClient(app)

    def _created(self, expires_on=None):
        key_out = KeyFullOut.from_key_obscured(
            db_mock.get_sample_key(expires_on=expires_on)
        )
        self.key_service.create_key = MagicMock(return_value=key_out)
        return key_out

    @freeze_time('2026-11-01 12:00:00')
    def test_create_without_expires_on(self):
        self._created()
        res = self.client.post(f'{self.prefix}/keys', json={'name': 'no-expiry'})
        assert res.status_code == 201
        assert res.json()['expiresOn'] is None
        assert res.json()['state'] == 'active'
        self.key_service.create_key.assert_called_once_with(
            KeyCreateIn(name='no-expiry', expires_on=None)
        )

    @freeze_time('2026-11-01 12:00:00')
    def test_create_with_expires_on(self):
        self._created(expires_on=datetime.date(2026, 11, 10))
        res = self.client.post(
            f'{self.prefix}/keys', json={'name': 'expiry', 'expiresOn': '2026-11-10'}
        )
        assert res.status_code == 201
        assert res.json()['expiresOn'] == '2026-11-10'
        assert res.json()['state'] == 'active'
        self.key_service.create_key.assert_called_once_with(
            KeyCreateIn(name='expiry', expires_on=datetime.date(2026, 11, 10))
        )

    @freeze_time('2026-11-01 23:59:59')
    def test_create_with_today_is_accepted(self):
        self._created(expires_on=datetime.date(2026, 11, 1))
        res = self.client.post(
            f'{self.prefix}/keys', json={'name': 'today', 'expiresOn': '2026-11-01'}
        )
        assert res.status_code == 201
        assert res.json()['state'] == 'expiring'

    @freeze_time('2026-11-02 00:00:00')
    def test_create_with_a_past_date_is_rejected(self):
        res = self.client.post(
            f'{self.prefix}/keys', json={'name': 'past', 'expiresOn': '2026-11-01'}
        )
        assert res.status_code == 422
        assert res.json()['detail'][0]['loc'] == ['body', 'expiresOn']
        self.key_service.create_key.assert_not_called()

    @freeze_time('2026-11-11 00:00:00')
    def test_reads_carry_expires_on_and_state(self):
        expired = KeyFullOut.from_key_obscured(
            db_mock.get_sample_key(expires_on=datetime.date(2026, 11, 10))
        )
        self.key_service.get_key_by_uuid = MagicMock(return_value=expired)
        self.key_service.get_all = MagicMock(return_value=[expired])

        one = self.client.get(f'{self.prefix}/keys/{expired.uuid}').json()
        assert one['expiresOn'] == '2026-11-10'
        assert one['state'] == 'expired'

        listed = self.client.get(f'{self.prefix}/keys').json()
        assert listed[0]['expiresOn'] == '2026-11-10'
        assert listed[0]['state'] == 'expired'

    def test_update_cannot_change_the_expiry_date(self):
        key = db_mock.get_sample_key()
        self.key_service.update_key_name = MagicMock()
        res = self.client.patch(
            f'{self.prefix}/keys/{key.uuid}',
            json={'name': 'renamed', 'expiresOn': '2099-01-01'},
        )
        assert res.status_code == 422
        self.key_service.update_key_name.assert_not_called()


EXPIRES_ON = datetime.date(2026, 11, 10)
EXPIRED_AT = '2026-11-11 00:00:00'
EXPIRING_AT = '2026-11-10 23:59:59'
LIMITS_BODY = {'limits': [{'category': 'budget', 'windowSize': '1 day', 'value': 10}]}


class TestKeyRouteExpiredIsDeleteOrUnassignOnly(unittest.TestCase):
    """A real KeyService over mocked DAOs, so the guards run behind the routes."""

    def setUp(self):
        self.prefix = '/public/api/v1'
        self.key_uuid = uuid.uuid4()
        self.group = db_mock.get_sample_group(uuid=uuid.uuid4())
        self.limit = db_mock.get_sample_key_limit(
            uuid=uuid.uuid4(), key_uuid=self.key_uuid
        )
        self.key = db_mock.get_sample_key(uuid=self.key_uuid, expires_on=EXPIRES_ON)

        self.key_dao = MagicMock(spec_set=KeyDAO)
        self.key_dao.get_by_uuid = MagicMock(side_effect=lambda _: self.key)
        self.key_dao.update_key_name = MagicMock(return_value=1)
        self.key_dao.assign_group = MagicMock(side_effect=lambda **_: self.key)
        self.key_dao.remove_group = MagicMock(return_value=1)
        self.key_dao.delete_by_uuid = MagicMock(return_value=1)
        group_dao = MagicMock(spec_set=GroupDAO)
        group_dao.get_by_uuid = MagicMock(return_value=self.group)
        group_limit_dao = MagicMock(spec_set=GroupLimitDAO)
        group_limit_dao.get_by_group_uuid = MagicMock(return_value=[])
        self.key_limit_dao = MagicMock(spec_set=KeyLimitDAO)
        self.key_limit_dao.get_by_key_uuid = MagicMock(return_value=[])
        self.key_limit_dao.insert_many = MagicMock(return_value=[])
        self.key_limit_dao.get_by_uuid = MagicMock(return_value=self.limit)
        self.key_limit_dao.delete_by_uuid = MagicMock(return_value=1)
        self.key_limit_dao.delete_group_limits_by_key_uuid = MagicMock(return_value=[])

        self.key_service = KeyService(
            key_dao=self.key_dao,
            api_key_security=MagicMock(spec_set=ApiKeySecurity),
            group_dao=group_dao,
            key_limit_dao=self.key_limit_dao,
            group_limit_dao=group_limit_dao,
        )
        app = FastAPI(title='AI Gateway', debug=True)
        app.add_exception_handler(AuthRegistryError, auth_registry_exception_handler)
        app.include_router(
            KeyRoute.get_key_router(self.key_service), prefix=self.prefix
        )
        self.client = TestClient(app)

        patcher = patch(
            'radicalbit_ai_gateway.services.key_service.clear_limit_counter',
            new=AsyncMock(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _operations(self):
        url = f'{self.prefix}/keys/{self.key_uuid}'
        return {
            'rename': lambda: self.client.patch(url, json={'name': 'renamed'}),
            'group associate': lambda: self.client.patch(
                f'{url}/group', json={'group': str(self.group.uuid)}
            ),
            'limit add': lambda: self.client.post(f'{url}/limits', json=LIMITS_BODY),
            'limit delete': lambda: self.client.delete(
                f'{url}/limits/{self.limit.uuid}'
            ),
        }

    @freeze_time(EXPIRED_AT)
    def test_operations_on_an_expired_key_are_refused(self):
        for name, call in self._operations().items():
            with self.subTest(name):
                res = call()
                assert res.status_code == 405
                assert res.json()['error']['code'] == 'key_operation_method_not_allowed'
                assert 'expired' in res.json()['error']['message']
        self.key_dao.update_key_name.assert_not_called()
        self.key_dao.assign_group.assert_not_called()
        self.key_limit_dao.insert_many.assert_not_called()
        self.key_limit_dao.delete_by_uuid.assert_not_called()

    @freeze_time(EXPIRED_AT)
    def test_group_unassign_on_an_expired_key_succeeds(self):
        self.key.group_uuid = self.group.uuid
        self.key.group = self.group
        # Unassign is cleanup, like delete: allowed on an expired key (ADR 0007).
        # It is reached through the group routes, which delegate to KeyService
        asyncio.run(
            self.key_service.remove_group_from_key(self.key_uuid, self.group.uuid)
        )
        self.key_dao.remove_group.assert_called_once_with(key_uuid=self.key_uuid)

    @freeze_time(EXPIRED_AT)
    def test_delete_on_an_expired_key_succeeds(self):
        res = self.client.delete(f'{self.prefix}/keys/{self.key_uuid}')
        assert res.status_code == 200
        self.key_dao.delete_by_uuid.assert_called_once_with(self.key_uuid)

    @freeze_time(EXPIRING_AT)
    def test_operations_on_an_expiring_key_still_succeed(self):
        for name, call in self._operations().items():
            with self.subTest(name):
                assert call().status_code in (200, 201)

    @freeze_time(EXPIRING_AT)
    def test_group_unassign_on_an_expiring_key_still_succeeds(self):
        self.key.group_uuid = self.group.uuid
        self.key.group = self.group
        asyncio.run(
            self.key_service.remove_group_from_key(self.key_uuid, self.group.uuid)
        )
        self.key_dao.remove_group.assert_called_once_with(key_uuid=self.key_uuid)
