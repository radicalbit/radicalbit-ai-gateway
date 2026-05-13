import unittest
from unittest.mock import MagicMock
import uuid

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from starlette.testclient import TestClient

from tests.common import db_mock

from radicalbit_ai_gateway.models.auth_dto import (
    GroupFullOut,
    GroupRouteOut,
    KeyFullOut,
)
from radicalbit_ai_gateway.routes.group_route import GroupRoute
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.utils.exceptions import (
    AuthRegistryError,
    ErrorOut,
    GroupInternalError,
    GroupNotFoundError,
    KeyNotFoundError,
    ProjectNotFoundError,
    RouteNotFoundError,
    auth_registry_exception_handler,
)


class TestGroupRoute(unittest.TestCase):
    def setUp(self):
        self.prefix = '/public/api/v1'
        self.group_service = MagicMock(spec_set=GroupService)
        self.project_service = MagicMock(spec_set=ProjectService)
        router = GroupRoute.get_group_router(self.group_service, self.project_service)
        app = FastAPI(title='AI Gateway', debug=True)
        app.add_exception_handler(AuthRegistryError, auth_registry_exception_handler)
        app.include_router(router, prefix=self.prefix)

        self.client = TestClient(app)

    def test_create_group(self):
        group_in = db_mock.get_sample_group_in()
        group = db_mock.get_sample_group()
        group_out = GroupFullOut.from_group(group)
        self.group_service.create_group = MagicMock(return_value=group_out)
        res = self.client.post(f'{self.prefix}/groups', json=jsonable_encoder(group_in))
        assert res.status_code == 201
        assert res.json() == jsonable_encoder(group_out)
        self.group_service.create_group.assert_called_once_with(group_in)

    def test_exception_handler_group_internal_error(self):
        group_in = db_mock.get_sample_group_in()
        self.group_service.create_group = MagicMock(
            side_effect=GroupInternalError('error')
        )
        res = self.client.post(
            f'{self.prefix}/groups',
            json=jsonable_encoder(group_in),
        )
        assert res.status_code == 500
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='group_internal_error', param=None
            ).error
        )
        self.group_service.create_group.assert_called_once_with(group_in)

    def test_get_all(self):
        groups = [
            GroupFullOut.from_group(
                db_mock.get_sample_group(uuid=uuid.uuid4(), name='one')
            ),
            GroupFullOut.from_group(
                db_mock.get_sample_group(uuid=uuid.uuid4(), name='two')
            ),
            GroupFullOut.from_group(
                db_mock.get_sample_group(uuid=uuid.uuid4(), name='three')
            ),
        ]
        self.group_service.get_all = MagicMock(return_value=groups)
        res = self.client.get(f'{self.prefix}/groups')
        assert res.status_code == 200
        assert jsonable_encoder(groups) == res.json()
        self.group_service.get_all.assert_called_once()

    def test_add_key(self):
        keys_uuid = [uuid.uuid4() for i in range(3)]
        keys = [db_mock.get_sample_key(uuid=i) for i in keys_uuid]
        group = db_mock.get_sample_group(keys=keys)
        key_uuids_in = db_mock.get_sample_keys_uuid_in(keys_uuid)
        group_out = GroupFullOut.from_group(group)
        self.group_service.add_keys = MagicMock(return_value=group_out)
        res = self.client.patch(
            f'{self.prefix}/groups/{group.uuid}/keys',
            json=jsonable_encoder(key_uuids_in),
        )
        assert res.status_code == 201
        assert jsonable_encoder(group_out) == res.json()
        self.group_service.add_keys.assert_called_once_with(
            group.uuid, key_uuids_in, False, False
        )

    def test_add_key_ko(self):
        group = db_mock.get_sample_group()
        keys_uuid = [uuid.uuid4() for i in range(3)]
        key_uuids_in = db_mock.get_sample_keys_uuid_in(keys_uuid)
        self.group_service.add_keys = MagicMock(side_effect=GroupInternalError('error'))
        res = self.client.patch(
            f'{self.prefix}/groups/{group.uuid}/keys',
            json=jsonable_encoder(key_uuids_in),
        )
        assert res.status_code == 500
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='group_internal_error', param=None
            ).error
        )
        self.group_service.add_keys.assert_called_once_with(
            group.uuid, key_uuids_in, False, False
        )

    def test_add_missing_key(self):
        group = db_mock.get_sample_group()
        keys_uuid = [uuid.uuid4() for i in range(3)]
        key_uuids_in = db_mock.get_sample_keys_uuid_in(keys_uuid)
        self.group_service.add_keys = MagicMock(side_effect=KeyNotFoundError('error'))
        res = self.client.patch(
            f'{self.prefix}/groups/{group.uuid}/keys',
            json=jsonable_encoder(key_uuids_in),
        )
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='key_not_found', param=None
            ).error
        )
        self.group_service.add_keys.assert_called_once_with(
            group.uuid, key_uuids_in, False, False
        )

    def test_add_key_missing_group(self):
        group = db_mock.get_sample_group()
        keys_uuid = [uuid.uuid4() for i in range(3)]
        key_uuids_in = db_mock.get_sample_keys_uuid_in(keys_uuid)
        self.group_service.add_keys = MagicMock(side_effect=GroupNotFoundError('error'))
        res = self.client.patch(
            f'{self.prefix}/groups/{group.uuid}/keys',
            json=jsonable_encoder(key_uuids_in),
        )
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='group_not_found', param=None
            ).error
        )
        self.group_service.add_keys.assert_called_once_with(
            group.uuid, key_uuids_in, False, False
        )

    def test_remove_key(self):
        key = db_mock.get_sample_key()
        group = db_mock.get_sample_group(keys=[key])
        group_out = GroupFullOut.from_group(group, False, True)
        self.group_service.remove_key = MagicMock(return_value=group_out)
        res = self.client.delete(
            f'{self.prefix}/groups/{group.uuid}/keys/{key.uuid}',
        )
        assert res.status_code == 200
        assert jsonable_encoder(group_out) == res.json()
        self.group_service.remove_key.assert_called_once_with(group.uuid, key.uuid)

    def test_remove_key_ko(self):
        group = db_mock.get_sample_group()
        key = db_mock.get_sample_key()
        self.group_service.remove_key = MagicMock(
            side_effect=GroupInternalError('error')
        )
        res = self.client.delete(
            f'{self.prefix}/groups/{group.uuid}/keys/{key.uuid}',
        )
        assert res.status_code == 500
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='group_internal_error', param=None
            ).error
        )
        self.group_service.remove_key.assert_called_once_with(group.uuid, key.uuid)

    def test_remove_missing_key(self):
        group = db_mock.get_sample_group()
        key = db_mock.get_sample_key()
        self.group_service.remove_key = MagicMock(side_effect=KeyNotFoundError('error'))
        res = self.client.delete(
            f'{self.prefix}/groups/{group.uuid}/keys/{key.uuid}',
        )
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='key_not_found', param=None
            ).error
        )
        self.group_service.remove_key.assert_called_once_with(group.uuid, key.uuid)

    def test_remove_key_missing_group(self):
        group = db_mock.get_sample_group()
        key = db_mock.get_sample_key()
        self.group_service.remove_key = MagicMock(
            side_effect=GroupNotFoundError('error')
        )
        res = self.client.delete(
            f'{self.prefix}/groups/{group.uuid}/keys/{key.uuid}',
        )
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='group_not_found', param=None
            ).error
        )
        self.group_service.remove_key.assert_called_once_with(group.uuid, key.uuid)

    def test_delete_group(self):
        group = db_mock.get_sample_group_plain()
        group_full_out = GroupFullOut.from_group(group)
        self.group_service.delete_group = MagicMock(return_value=group_full_out)
        res = self.client.delete(f'{self.prefix}/groups/{db_mock.RANDOM_UUID}')
        assert res.status_code == 200
        self.group_service.delete_group.assert_called_once_with(
            db_mock.RANDOM_UUID, False, False
        )
        assert res.json() == jsonable_encoder(group_full_out)

    def test_delete_group_only_routes(self):
        group_uuid = uuid.uuid4()
        group_route = db_mock.get_sample_group_route_plain(group_uuid=group_uuid)
        group = db_mock.get_sample_group(uuid=group_uuid, group_routes=[group_route])
        group_full_out = GroupFullOut.from_group(group, True)
        self.group_service.delete_group = MagicMock(return_value=group_full_out)
        res = self.client.delete(
            f'{self.prefix}/groups/{db_mock.RANDOM_UUID}?include_routes=true'
        )
        assert res.status_code == 200
        self.group_service.delete_group.assert_called_once_with(
            db_mock.RANDOM_UUID, True, False
        )
        assert res.json() == jsonable_encoder(group_full_out)

    def test_delete_group_ko(self):
        self.group_service.delete_group = MagicMock(
            side_effect=GroupInternalError('error')
        )
        res = self.client.delete(f'{self.prefix}/groups/{db_mock.RANDOM_UUID}')
        assert res.status_code == 500
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='group_internal_error', param=None
            ).error
        )
        self.group_service.delete_group.assert_called_once_with(
            db_mock.RANDOM_UUID, False, False
        )

    def test_delete_missing_group(self):
        self.group_service.delete_group = MagicMock(
            side_effect=GroupNotFoundError('error')
        )
        res = self.client.delete(f'{self.prefix}/groups/{db_mock.RANDOM_UUID}')
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='group_not_found', param=None
            ).error
        )
        self.group_service.delete_group.assert_called_once_with(
            db_mock.RANDOM_UUID, False, False
        )

    def test_get_group_by_uuid(self):
        group = db_mock.get_sample_group()
        group_out = GroupFullOut.from_group(group)
        self.group_service.get_group_by_uuid = MagicMock(return_value=group_out)
        res = self.client.get(f'{self.prefix}/groups/{group.uuid}')
        assert res.status_code == 200
        assert jsonable_encoder(group_out) == res.json()
        self.group_service.get_group_by_uuid.assert_called_once_with(
            group.uuid, False, False
        )

    def test_get_group_by_uuid_ko(self):
        group = db_mock.get_sample_group()
        self.group_service.get_group_by_uuid = MagicMock(
            side_effect=GroupInternalError('error')
        )
        res = self.client.get(f'{self.prefix}/groups/{group.uuid}')
        assert res.status_code == 500
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='group_internal_error', param=None
            ).error
        )
        self.group_service.get_group_by_uuid.assert_called_once_with(
            group.uuid, False, False
        )

    def test_get_missing_group_by_uuid(self):
        group = db_mock.get_sample_group()
        self.group_service.get_group_by_uuid = MagicMock(
            side_effect=GroupNotFoundError('error')
        )
        res = self.client.get(f'{self.prefix}/groups/{group.uuid}')
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='group_not_found', param=None
            ).error
        )
        self.group_service.get_group_by_uuid.assert_called_once_with(
            group.uuid, False, False
        )

    def test_update_group_name(self):
        group = db_mock.get_sample_group()
        group_in = db_mock.get_sample_group_in()
        group_out = GroupFullOut.from_group(group)
        self.group_service.update_group_name = MagicMock(return_value=group_out)
        res = self.client.patch(
            f'{self.prefix}/groups/{group.uuid}', json=jsonable_encoder(group_in)
        )
        assert res.status_code == 200
        assert jsonable_encoder(group_out) == res.json()
        self.group_service.update_group_name.assert_called_once_with(
            group.uuid, group_in
        )

    def test_update_missing_group_name(self):
        group = db_mock.get_sample_group()
        group_in = db_mock.get_sample_group_in()
        self.group_service.update_group_name = MagicMock(
            side_effect=GroupNotFoundError('error')
        )
        res = self.client.patch(
            f'{self.prefix}/groups/{group.uuid}', json=jsonable_encoder(group_in)
        )
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='group_not_found', param=None
            ).error
        )
        self.group_service.update_group_name.assert_called_once_with(
            group.uuid, group_in
        )

    def test_get_associable_keys(self):
        group = db_mock.get_sample_group()
        keys_out = [
            KeyFullOut.from_key_obscured(
                db_mock.get_sample_key(uuid=uuid.uuid4(), name='k1')
            ),
            KeyFullOut.from_key_obscured(
                db_mock.get_sample_key(uuid=uuid.uuid4(), name='k2')
            ),
        ]
        self.group_service.get_associable_keys = MagicMock(return_value=keys_out)
        res = self.client.get(f'{self.prefix}/groups/{group.uuid}/associable-keys')
        assert res.status_code == 200
        assert jsonable_encoder(keys_out) == res.json()
        self.group_service.get_associable_keys.assert_called_once_with(group.uuid)

    def test_get_associable_keys_empty(self):
        group = db_mock.get_sample_group()
        self.group_service.get_associable_keys = MagicMock(return_value=[])
        res = self.client.get(f'{self.prefix}/groups/{group.uuid}/associable-keys')
        assert res.status_code == 200
        assert res.json() == []
        self.group_service.get_associable_keys.assert_called_once_with(group.uuid)

    def test_get_associable_keys_group_not_found(self):
        group = db_mock.get_sample_group()
        self.group_service.get_associable_keys = MagicMock(
            side_effect=GroupNotFoundError('error')
        )
        res = self.client.get(f'{self.prefix}/groups/{group.uuid}/associable-keys')
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='group_not_found', param=None
            ).error
        )
        self.group_service.get_associable_keys.assert_called_once_with(group.uuid)


class TestGroupRouteWithProject(unittest.TestCase):
    def setUp(self):
        self.prefix = '/public/api/v1'
        self.group_service = MagicMock(spec_set=GroupService)
        self.project_service = MagicMock(spec_set=ProjectService)
        router = GroupRoute.get_group_router(self.group_service, self.project_service)
        app = FastAPI(title='AI Gateway', debug=True)
        app.add_exception_handler(AuthRegistryError, auth_registry_exception_handler)
        app.include_router(router, prefix=self.prefix)
        self.client = TestClient(app)
        self.project_uuid = uuid.uuid4()
        self.project_out = db_mock.get_sample_project_out(
            uuid=self.project_uuid, name='my-project'
        )
        self.project_service.get_by_uuid = MagicMock(return_value=self.project_out)

    # ------------------------------------------------------------------
    # PATCH /groups/{group_uuid}/projects/{project_uuid}/routes
    # ------------------------------------------------------------------

    def test_add_project_route(self):
        group_route = db_mock.get_sample_group_route(
            route_name='my-route', project_uuid=self.project_uuid
        )
        group = db_mock.get_sample_group(group_routes=[group_route])
        group_out = GroupFullOut.from_group(group, True)
        group_routes_in = db_mock.get_sample_group_routes_in(['my-route'])
        self.group_service.add_project_routes = MagicMock(return_value=group_out)
        res = self.client.patch(
            f'{self.prefix}/groups/{group.uuid}/projects/{self.project_uuid}/routes',
            json=jsonable_encoder(group_routes_in),
        )
        assert res.status_code == 201
        assert jsonable_encoder(group_out) == res.json()
        self.group_service.add_project_routes.assert_called_once_with(
            group.uuid,
            self.project_uuid,
            'my-project',
            group_routes_in,
            False,
            False,
        )

    def test_add_project_route_not_found(self):
        group = db_mock.get_sample_group()
        group_routes_in = db_mock.get_sample_group_routes_in(['nonexistent'])
        self.group_service.add_project_routes = MagicMock(
            side_effect=RouteNotFoundError('error')
        )
        res = self.client.patch(
            f'{self.prefix}/groups/{group.uuid}/projects/{self.project_uuid}/routes',
            json=jsonable_encoder(group_routes_in),
        )
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='route_not_found', param=None
            ).error
        )

    # ------------------------------------------------------------------
    # DELETE /groups/{group_uuid}/projects/{project_uuid}/routes/{route_name}
    # ------------------------------------------------------------------

    def test_remove_project_route(self):
        group = db_mock.get_sample_group()
        group_out = GroupFullOut.from_group(group)
        self.group_service.remove_project_route = MagicMock(return_value=group_out)
        res = self.client.delete(
            f'{self.prefix}/groups/{group.uuid}/projects/{self.project_uuid}/routes/my-route',
        )
        assert res.status_code == 200
        assert jsonable_encoder(group_out) == res.json()
        self.group_service.remove_project_route.assert_called_once_with(
            group.uuid, self.project_uuid, 'my-project', 'my-route'
        )

    def test_remove_project_route_not_found(self):
        group = db_mock.get_sample_group()
        self.group_service.remove_project_route = MagicMock(
            side_effect=RouteNotFoundError('error')
        )
        res = self.client.delete(
            f'{self.prefix}/groups/{group.uuid}/projects/{self.project_uuid}/routes/my-route',
        )
        assert res.status_code == 404

    # ------------------------------------------------------------------
    # GET /groups/{group_uuid}/projects/{project_uuid}/associable-routes
    # ------------------------------------------------------------------

    def test_get_associable_routes(self):
        group = db_mock.get_sample_group()
        _proj_uuid = uuid.uuid4()
        routes_out = [
            GroupRouteOut(
                name='route-A', project_uuid=_proj_uuid, project_name='my-project'
            ),
            GroupRouteOut(
                name='route-B', project_uuid=_proj_uuid, project_name='my-project'
            ),
        ]
        self.group_service.get_associable_routes = MagicMock(return_value=routes_out)
        res = self.client.get(
            f'{self.prefix}/groups/{group.uuid}/projects/{self.project_uuid}/associable-routes'
        )
        assert res.status_code == 200
        assert jsonable_encoder(routes_out) == res.json()
        self.group_service.get_associable_routes.assert_called_once_with(
            group.uuid, 'my-project'
        )

    def test_get_associable_routes_empty(self):
        group = db_mock.get_sample_group()
        self.group_service.get_associable_routes = MagicMock(return_value=[])
        res = self.client.get(
            f'{self.prefix}/groups/{group.uuid}/projects/{self.project_uuid}/associable-routes'
        )
        assert res.status_code == 200
        assert res.json() == []
        self.group_service.get_associable_routes.assert_called_once_with(
            group.uuid, 'my-project'
        )

    def test_get_associable_routes_group_not_found(self):
        group = db_mock.get_sample_group()
        self.group_service.get_associable_routes = MagicMock(
            side_effect=GroupNotFoundError('error')
        )
        res = self.client.get(
            f'{self.prefix}/groups/{group.uuid}/projects/{self.project_uuid}/associable-routes'
        )
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='group_not_found', param=None
            ).error
        )
        self.group_service.get_associable_routes.assert_called_once_with(
            group.uuid, 'my-project'
        )

    def test_get_associable_routes_project_not_found(self):
        group = db_mock.get_sample_group()
        self.project_service.get_by_uuid = MagicMock(
            side_effect=ProjectNotFoundError('error')
        )
        res = self.client.get(
            f'{self.prefix}/groups/{group.uuid}/projects/{self.project_uuid}/associable-routes'
        )
        assert res.status_code == 404
        assert (
            res.json()['error']
            == ErrorOut(
                'error', 'auth_registry_error', code='project_not_found', param=None
            ).error
        )
        self.group_service.get_associable_routes.assert_not_called()
