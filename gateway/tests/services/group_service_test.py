import datetime
import unittest
from unittest.mock import MagicMock, call
import uuid
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError

from tests.common import db_mock
from tests.common.mocked_gateway_config import get_plain_gateway

from radicalbit_ai_gateway.db.dao.group_dao import GroupDAO
from radicalbit_ai_gateway.db.dao.group_route_dao import GroupRouteDAO
from radicalbit_ai_gateway.db.dao.key_dao import KeyDAO
from radicalbit_ai_gateway.models.auth_dto import (
    GroupFullOut,
    GroupRouteOut,
    GroupsRouteOut,
    KeyFullOut,
    RouteGroupsIn,
)
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.project_entry import ProjectEntry
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.utils.exceptions import (
    GroupAlreadyExistsError,
    GroupInternalError,
    GroupNotFoundError,
    GroupOperationNotAllowedError,
    RouteNotFoundError,
)

_MY_PROJECT_UUID = UUID('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')


class GroupServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.group_dao: GroupDAO = MagicMock(spec_set=GroupDAO)
        cls.key_dao: KeyDAO = MagicMock(spec_set=KeyDAO)
        cls.key_service: KeyService = MagicMock()(spec_set=KeyService)
        cls.group_route_dao: GroupRouteDAO = MagicMock(spec_set=GroupRouteDAO)
        gw_a = get_plain_gateway('route-A')
        gw_b = get_plain_gateway('route-B')
        project_config = GatewayConfig(
            chat_models=gw_a.chat_models,
            embedding_models=gw_a.embedding_models,
            routes={
                'route-A': gw_a.routes['route-A'],
                'route-B': gw_b.routes['route-B'],
            },
            guardrails=[],
            cache=None,
        )
        cls.group_service = GroupService(
            group_dao=cls.group_dao,
            key_service=cls.key_service,
            group_route_dao=cls.group_route_dao,
            project_configs={
                'my-project': ProjectEntry(uuid=_MY_PROJECT_UUID, config=project_config)
            },
        )
        cls.mocks = [
            cls.group_dao,
            cls.key_service,
            cls.group_route_dao,
        ]

    def setUp(self):
        for mock in self.mocks:
            mock.reset_mock()

    def test_create_group_ok(self):
        group = db_mock.get_sample_group_plain()
        self.group_dao.insert = MagicMock(return_value=group)
        group_in = db_mock.get_sample_group_in()
        res = self.group_service.create_group(group_in)
        self.group_dao.insert.assert_called_once()
        assert res == GroupFullOut.from_group(group=group)

    def test_get_all(self):
        groups = [
            db_mock.get_sample_group_plain(uuid=uuid.uuid4(), name='one'),
            db_mock.get_sample_group_plain(uuid=uuid.uuid4(), name='two'),
            db_mock.get_sample_group_plain(uuid=uuid.uuid4(), name='three'),
        ]
        self.group_dao.get_all = MagicMock(return_value=groups)
        res = self.group_service.get_all(include_keys=False, include_routes=False)
        self.group_dao.get_all.assert_called_once()
        routes = [i.routes for i in res]
        assert all(r is None for r in routes)
        keys = [i.keys for i in res]
        assert all(r is None for r in keys)
        assert len(res) == 3

    def test_get_all_include_routes(self):
        group_uuid = uuid.uuid4()
        group_route = db_mock.get_sample_group_route(group_uuid=group_uuid)
        groups = [
            db_mock.get_sample_group(
                uuid=group_uuid, name='one', group_routes=[group_route]
            ),
            db_mock.get_sample_group(uuid=uuid.uuid4(), name='two'),
            db_mock.get_sample_group(uuid=uuid.uuid4(), name='three'),
        ]
        self.group_dao.get_all = MagicMock(return_value=groups)
        res = self.group_service.get_all(include_keys=False, include_routes=True)
        self.group_dao.get_all.assert_called_once()
        assert res[0].routes == [GroupRouteOut.from_group_route(group_route)]
        keys = [i.keys for i in res]
        assert all(r is None for r in keys)
        assert len(res) == 3

    def test_get_all_include_routes_excludes_deleted_project_routes(self):
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        group_uuid = uuid.uuid4()
        live_route = db_mock.get_sample_group_route(
            group_uuid=group_uuid, route_name='live-route'
        )
        deleted_route = db_mock.get_sample_group_route(
            group_uuid=group_uuid, route_name='deleted-route'
        )
        deleted_route.project.deleted_at = datetime.datetime.now(tz=UTC)
        group = db_mock.get_sample_group(
            uuid=group_uuid, group_routes=[live_route, deleted_route]
        )
        self.group_dao.get_all = MagicMock(return_value=[group])
        res = self.group_service.get_all(include_keys=False, include_routes=True)
        assert res[0].routes == [GroupRouteOut.from_group_route(live_route)]

    def test_add_key(self):
        group_uuid = uuid.uuid4()
        keys_uuid = [uuid.uuid4() for i in range(3)]
        keys = [db_mock.get_sample_key(uuid=i) for i in keys_uuid]
        group = db_mock.get_sample_group(uuid=group_uuid, keys=keys)
        keys_in = db_mock.get_sample_keys_uuid_in(keys_uuid)
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.key_service.get_key_by_uuid = MagicMock(return_value=keys[0])
        self.key_service.get_key_by_uuid = MagicMock(return_value=keys[1])
        self.key_service.get_key_by_uuid = MagicMock(return_value=keys[2])
        self.key_service.add_group_to_key = MagicMock(return_value=keys[0])
        self.key_service.add_group_to_key = MagicMock(return_value=keys[1])
        self.key_service.add_group_to_key = MagicMock(return_value=keys[2])
        res = self.group_service.add_keys(
            group_uuid=group.uuid, keys=keys_in, include_routes=False, include_keys=True
        )
        self.group_dao.get_by_uuid.assert_has_calls(
            calls=[call(group.uuid), call(group_uuid=group.uuid)]
        )
        assert self.group_dao.get_by_uuid.call_count == 2
        assert self.key_service.add_group_to_key.call_count == 3
        assert self.key_service.get_key_by_uuid.call_count == 3
        assert res == GroupFullOut.from_group(group, False, True)

    def test_add_key_missing_group(self):
        group = db_mock.get_sample_group_plain()
        self.group_dao.get_by_uuid = MagicMock(return_value=None)
        keys_in = db_mock.get_sample_keys_uuid_in([uuid.uuid4() for i in range(3)])
        pytest.raises(
            GroupNotFoundError,
            self.group_service.add_keys,
            group.uuid,
            keys_in,
            True,
            True,
        )

    def test_add_keys_to_keycloak_group_raises(self):
        group = db_mock.get_sample_group_plain()
        group.owner = 'keycloak'
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        keys_in = db_mock.get_sample_keys_uuid_in([uuid.uuid4()])
        pytest.raises(
            GroupOperationNotAllowedError,
            self.group_service.add_keys,
            group.uuid,
            keys_in,
            False,
            False,
        )
        self.key_service.add_group_to_key.assert_not_called()

    def test_remove_key(self):
        group = db_mock.get_sample_group()
        key = db_mock.get_sample_key_full_out()
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.key_service.remove_group_from_key = MagicMock(return_value=key)
        res = self.group_service.remove_key(group.uuid, key.uuid)
        assert self.group_dao.get_by_uuid.call_count == 2
        self.key_service.remove_group_from_key.assert_called_once_with(
            key_uuid=key.uuid, group_uuid=group.uuid
        )
        assert res == GroupFullOut.from_group(group, True, True)

    def test_remove_key_missing_group(self):
        group = db_mock.get_sample_group_plain()
        key = db_mock.get_sample_key()
        self.group_dao.get_by_uuid = MagicMock(return_value=None)
        self.key_dao.get_by_uuid = MagicMock(return_value=key)
        pytest.raises(
            GroupNotFoundError, self.group_service.remove_key, group.uuid, key.uuid
        )

    def test_remove_key_from_keycloak_group_raises(self):
        group = db_mock.get_sample_group_plain()
        group.owner = 'keycloak'
        key = db_mock.get_sample_key()
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        pytest.raises(
            GroupOperationNotAllowedError,
            self.group_service.remove_key,
            group.uuid,
            key.uuid,
        )
        self.key_service.remove_group_from_key.assert_not_called()

    def test_delete_group(self):
        group = db_mock.get_sample_group_plain()
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.group_dao.delete_by_uuid = MagicMock(return_value=group)
        res = self.group_service.delete_group(group.uuid, False, False)
        self.group_dao.delete_by_uuid.assert_called_once_with(group.uuid)
        assert res == GroupFullOut.from_group(group)

    def test_delete_group_only_routes(self):
        group_uuid = uuid.uuid4()
        group_route = db_mock.get_sample_group_route(group_uuid=group_uuid)
        group = db_mock.get_sample_group(uuid=group_uuid, group_routes=[group_route])
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.group_dao.delete_by_uuid = MagicMock(return_value=group)
        res = self.group_service.delete_group(group.uuid, True, False)
        self.group_dao.delete_by_uuid.assert_called_once_with(group.uuid)
        assert res == GroupFullOut.from_group(group, True, False)

    def test_delete_group_only_keys(self):
        group_uuid = uuid.uuid4()
        key_uuid = uuid.uuid4()
        key = db_mock.get_sample_key(uuid=key_uuid)
        group = db_mock.get_sample_group(uuid=group_uuid, keys=[key])
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.group_dao.delete_by_uuid = MagicMock(return_value=group)
        res = self.group_service.delete_group(group.uuid, False, True)
        self.group_dao.delete_by_uuid.assert_called_once_with(group.uuid)
        assert res == GroupFullOut.from_group(group, False, True)

    def test_delete_group_ko(self):
        group = db_mock.get_sample_group_plain()
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.group_dao.delete_by_uuid = MagicMock(return_value=None)
        pytest.raises(
            GroupInternalError,
            self.group_service.delete_group,
            group.uuid,
            False,
            False,
        )
        self.group_dao.delete_by_uuid.assert_called_once_with(group.uuid)

    def test_delete_not_existing_group(self):
        group = db_mock.get_sample_group_plain()
        self.group_dao.get_by_uuid = MagicMock(return_value=None)
        pytest.raises(
            GroupNotFoundError,
            self.group_service.delete_group,
            group.uuid,
            False,
            False,
        )

    def test_delete_keycloak_group_raises(self):
        group = db_mock.get_sample_group_plain()
        group.owner = 'keycloak'
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.group_dao.delete_by_uuid = MagicMock()
        pytest.raises(
            GroupOperationNotAllowedError,
            self.group_service.delete_group,
            group.uuid,
            False,
            False,
        )
        self.group_dao.delete_by_uuid.assert_not_called()

    def test_get_group_by_uuid(self):
        group = db_mock.get_sample_group_plain()
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        res = self.group_service.get_group_by_uuid(group.uuid, False, False)
        self.group_dao.get_by_uuid.assert_called_once()
        assert res == GroupFullOut.from_group(group)

    def test_get_missing_group_by_uuid(self):
        group = db_mock.get_sample_group_plain()
        self.group_dao.get_by_uuid = MagicMock(return_value=None)
        pytest.raises(
            GroupNotFoundError,
            self.group_service.get_group_by_uuid,
            group.uuid,
            False,
            False,
        )

    def test_update_group_name(self):
        group = db_mock.get_sample_group()
        group_in = db_mock.get_sample_group_in()
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.group_dao.update_group_name = MagicMock(return_value=1)
        res = self.group_service.update_group_name(group.uuid, group_in)
        self.group_dao.get_by_uuid.assert_has_calls(
            calls=[call(group_uuid=group.uuid), call(group_uuid=group.uuid)]
        )
        assert self.group_dao.get_by_uuid.call_count == 2
        self.group_dao.update_group_name.assert_called_once()
        assert res == GroupFullOut.from_group(group)

    def test_update_group_name_ko(self):
        group = db_mock.get_sample_group_plain()
        group_in = db_mock.get_sample_group_in()
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.group_dao.update_group_name = MagicMock(return_value=0)
        pytest.raises(
            GroupInternalError,
            self.group_service.update_group_name,
            group.uuid,
            group_in,
        )
        self.group_dao.get_by_uuid.assert_called_once()
        self.group_dao.update_group_name.assert_called_once()

    def test_update_missing_group_name(self):
        group = db_mock.get_sample_group_plain()
        group_in = db_mock.get_sample_group_in()
        self.group_dao.get_by_uuid = MagicMock(return_value=None)
        pytest.raises(
            GroupNotFoundError,
            self.group_service.update_group_name,
            group.uuid,
            group_in,
        )

    def test_get_all_groups_by_route_empty(self):
        self.group_dao.get_all_group_by_route_name = MagicMock(return_value=[])
        groups = self.group_service.get_all_groups_by_route('my-project', 'route-A')
        assert len(groups) == 0

    def test_get_all_groups_by_route_with_single_group(self):
        admin_group = db_mock.get_sample_group_plain()
        self.group_dao.get_all_group_by_route_name = MagicMock(
            return_value=[admin_group]
        )
        groups = self.group_service.get_all_groups_by_route('my-project', 'route-A')
        assert len(groups) == 1
        assert isinstance(groups[0], GroupFullOut)
        assert groups[0].uuid == admin_group.uuid

    def test_get_all_groups_by_route(self):
        dev = db_mock.get_sample_group_plain()
        data = db_mock.get_sample_group_plain()
        admin = db_mock.get_sample_group_plain()
        self.group_dao.get_all_group_by_route_name = MagicMock(
            return_value=[dev, data, admin]
        )
        groups = self.group_service.get_all_groups_by_route('my-project', 'route-A')
        assert len(groups) == 3
        assert all(isinstance(x, GroupFullOut) for x in groups)

    def test_get_all_groups_by_route_filters_correctly(self):
        dashboard_group = db_mock.get_sample_group_plain(name='Dashboard Users')
        _ = db_mock.get_sample_group_plain(name='Settings Users')
        self.group_dao.get_all_group_by_route_name = MagicMock(
            return_value=[dashboard_group]
        )
        groups = self.group_service.get_all_groups_by_route('my-project', 'route-A')
        assert len(groups) == 1
        assert groups[0].name == 'Dashboard Users'

    def test_get_all_groups_by_non_existent_route(self):
        self.group_dao.get_all_group_by_route_name = MagicMock(return_value=[])
        groups = self.group_service.get_all_groups_by_route(
            'this-project', 'this-route-does-not-exist'
        )
        assert groups == []
        assert len(groups) == 0

    def test_get_associable_keys_ok(self):
        group = db_mock.get_sample_group_plain()
        keys_out = [
            KeyFullOut.from_key_obscured(
                db_mock.get_sample_key(uuid=uuid.uuid4(), name='k1')
            ),
            KeyFullOut.from_key_obscured(
                db_mock.get_sample_key(uuid=uuid.uuid4(), name='k2')
            ),
        ]
        self.key_service.get_associable_keys = MagicMock(return_value=keys_out)
        res = self.group_service.get_associable_keys(group.uuid)
        self.key_service.get_associable_keys.assert_called_once_with(group.uuid)
        assert len(res) == 2

    def test_get_associable_keys_group_not_found(self):
        self.key_service.get_associable_keys = MagicMock(
            side_effect=GroupNotFoundError('error')
        )
        pytest.raises(
            GroupNotFoundError,
            self.group_service.get_associable_keys,
            uuid.uuid4(),
        )

    def test_get_associable_groups_for_project_route_ok(self):
        g1 = db_mock.get_sample_group_plain(uuid=uuid.uuid4(), name='g1')
        g2 = db_mock.get_sample_group_plain(uuid=uuid.uuid4(), name='g2')
        self.group_dao.get_all = MagicMock(return_value=[g1, g2])
        self.group_dao.get_all_group_by_route_name = MagicMock(return_value=[])
        res = self.group_service.get_associable_groups_for_project_route(
            'my-project', 'route-A', False, False
        )
        self.group_dao.get_all.assert_called_once_with()
        self.group_dao.get_all_group_by_route_name.assert_called_once_with(
            _MY_PROJECT_UUID, 'route-A'
        )
        assert len(res) == 2
        assert all(isinstance(g, GroupFullOut) for g in res)

    def test_get_associable_groups_for_project_route_excludes_assigned(self):
        g1 = db_mock.get_sample_group_plain(uuid=uuid.uuid4(), name='g1')
        g2 = db_mock.get_sample_group_plain(uuid=uuid.uuid4(), name='g2')
        self.group_dao.get_all = MagicMock(return_value=[g1, g2])
        self.group_dao.get_all_group_by_route_name = MagicMock(return_value=[g1])
        res = self.group_service.get_associable_groups_for_project_route(
            'my-project', 'route-A', False, False
        )
        assert len(res) == 1
        assert res[0].uuid == g2.uuid

    def test_get_associable_groups_for_project_route_not_found(self):
        pytest.raises(
            RouteNotFoundError,
            self.group_service.get_associable_groups_for_project_route,
            'non-existent',
            'route',
            False,
            False,
        )

    def test_get_associable_routes_ok(self):
        group = db_mock.get_sample_group_plain()
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.group_dao.get_route_names_by_group_uuid = MagicMock(return_value=[])
        res = self.group_service.get_associable_routes(group.uuid, 'my-project')
        self.group_dao.get_route_names_by_group_uuid.assert_called_once_with(group.uuid)
        assert (
            len(res) == 2
        )  # my-project/route-A and my-project/route-B from test config
        assert all(isinstance(r, GroupRouteOut) for r in res)
        assert {r.name for r in res} == {'route-A', 'route-B'}
        assert all(r.project_uuid == _MY_PROJECT_UUID for r in res)
        assert all(r.project_name == 'my-project' for r in res)

    def test_get_associable_routes_excludes_assigned(self):
        group = db_mock.get_sample_group_plain()
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.group_dao.get_route_names_by_group_uuid = MagicMock(
            return_value=['my-project/route-A']
        )
        res = self.group_service.get_associable_routes(group.uuid, 'my-project')
        assert len(res) == 1
        assert res[0].name == 'route-B'

    def test_get_associable_routes_keycloak_group(self):
        group = db_mock.get_sample_group_plain()
        group.owner = 'keycloak'
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.group_dao.get_route_names_by_group_uuid = MagicMock(return_value=[])
        res = self.group_service.get_associable_routes(group.uuid, 'my-project')
        self.group_dao.get_route_names_by_group_uuid.assert_called_once_with(group.uuid)
        assert len(res) == 2  # keycloak groups can also be associated to routes

    def test_get_associable_routes_group_not_found(self):
        self.group_dao.get_by_uuid = MagicMock(return_value=None)
        pytest.raises(
            GroupNotFoundError,
            self.group_service.get_associable_routes,
            uuid.uuid4(),
            'my-project',
        )

    def test_validate_route_finds_project_route(self):
        """_validate_route resolves project routes via the shared project_configs dict."""
        project_config = get_plain_gateway('my-route')
        service = GroupService(
            group_dao=self.group_dao,
            key_service=self.key_service,
            group_route_dao=self.group_route_dao,
            project_configs={
                'my-project': ProjectEntry(uuid=_MY_PROJECT_UUID, config=project_config)
            },
        )
        service._validate_route('my-project', 'my-route')  # must not raise

    def test_validate_route_project_route_not_found(self):
        """_validate_route raises RouteNotFoundError when the project route doesn't exist."""
        service = GroupService(
            group_dao=self.group_dao,
            key_service=self.key_service,
            group_route_dao=self.group_route_dao,
            project_configs={},
        )
        pytest.raises(
            RouteNotFoundError, service._validate_route, 'my-project', 'my-route'
        )

    def test_add_project_routes(self):
        project_uuid = uuid.uuid4()
        project_config = get_plain_gateway('my-route')
        service = GroupService(
            group_dao=self.group_dao,
            key_service=self.key_service,
            group_route_dao=self.group_route_dao,
            project_configs={
                'my-project': ProjectEntry(uuid=_MY_PROJECT_UUID, config=project_config)
            },
        )
        group_route = db_mock.get_sample_group_route(
            route_name='my-route', project_uuid=project_uuid
        )
        group = db_mock.get_sample_group(group_routes=[group_route])
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.group_route_dao.add_bulk = MagicMock(return_value=[group_route])
        group_routes_in = db_mock.get_sample_group_routes_in(['my-route'])
        res = service.add_project_routes(
            group.uuid,
            project_uuid,
            'my-project',
            group_routes_in,
            True,
            False,
        )
        self.group_route_dao.add_bulk.assert_called_once()
        call_args = self.group_route_dao.add_bulk.call_args[0][0]
        assert len(call_args) == 1
        assert call_args[0].route_name == 'my-route'
        assert call_args[0].project_uuid == project_uuid
        assert res == GroupFullOut.from_group(group, True, False)

    def test_add_project_routes_route_not_found(self):
        project_uuid = uuid.uuid4()
        service = GroupService(
            group_dao=self.group_dao,
            key_service=self.key_service,
            group_route_dao=self.group_route_dao,
            project_configs={},
        )
        group = db_mock.get_sample_group_plain()
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        group_routes_in = db_mock.get_sample_group_routes_in(['nonexistent-route'])
        pytest.raises(
            RouteNotFoundError,
            service.add_project_routes,
            group.uuid,
            project_uuid,
            'my-project',
            group_routes_in,
            False,
            False,
        )
        self.group_route_dao.add_bulk.assert_not_called()

    def test_remove_project_route(self):
        project_uuid = uuid.uuid4()
        project_config = get_plain_gateway('my-route')
        service = GroupService(
            group_dao=self.group_dao,
            key_service=self.key_service,
            group_route_dao=self.group_route_dao,
            project_configs={
                'my-project': ProjectEntry(uuid=_MY_PROJECT_UUID, config=project_config)
            },
        )
        group = db_mock.get_sample_group()
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.group_dao.remove_project_route = MagicMock(return_value=1)
        res = service.remove_project_route(
            group.uuid, project_uuid, 'my-project', 'my-route'
        )
        self.group_dao.remove_project_route.assert_called_once_with(
            group.uuid, project_uuid, 'my-route'
        )
        assert res == GroupFullOut.from_group(group)

    def test_remove_project_route_route_not_found(self):
        project_uuid = uuid.uuid4()
        service = GroupService(
            group_dao=self.group_dao,
            key_service=self.key_service,
            group_route_dao=self.group_route_dao,
            project_configs={},
        )
        pytest.raises(
            RouteNotFoundError,
            service.remove_project_route,
            uuid.uuid4(),
            project_uuid,
            'my-project',
            'nonexistent-route',
        )

    def test_remove_project_route_ko(self):
        project_uuid = uuid.uuid4()
        project_config = get_plain_gateway('my-route')
        service = GroupService(
            group_dao=self.group_dao,
            key_service=self.key_service,
            group_route_dao=self.group_route_dao,
            project_configs={
                'my-project': ProjectEntry(uuid=_MY_PROJECT_UUID, config=project_config)
            },
        )
        group = db_mock.get_sample_group()
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.group_dao.remove_project_route = MagicMock(return_value=0)
        pytest.raises(
            GroupInternalError,
            service.remove_project_route,
            group.uuid,
            project_uuid,
            'my-project',
            'my-route',
        )

    def test_add_groups_to_project_route(self):
        project_uuid = uuid.uuid4()
        project_config = get_plain_gateway('my-route')
        service = GroupService(
            group_dao=self.group_dao,
            key_service=self.key_service,
            group_route_dao=self.group_route_dao,
            project_configs={
                'my-project': ProjectEntry(uuid=_MY_PROJECT_UUID, config=project_config)
            },
        )
        g1_uuid = uuid.uuid4()
        group = db_mock.get_sample_group_plain(uuid=g1_uuid)
        group_route = db_mock.get_sample_group_route(
            group_uuid=g1_uuid,
            route_name='my-route',
            project_uuid=project_uuid,
        )
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.group_route_dao.add_bulk = MagicMock(return_value=[group_route])
        route_groups_in = RouteGroupsIn(groups=[g1_uuid])
        res = service.add_groups_to_project_route(
            project_uuid=project_uuid,
            project_name='my-project',
            route_name='my-route',
            route_groups_in=route_groups_in,
            include_groups=False,
        )
        self.group_route_dao.add_bulk.assert_called_once()
        call_args = self.group_route_dao.add_bulk.call_args[0][0]
        assert len(call_args) == 1
        assert call_args[0].route_name == 'my-route'
        assert call_args[0].project_uuid == project_uuid
        assert isinstance(res, GroupsRouteOut)
        assert res.route_name == 'my-route'
        assert res.project_name == 'my-project'
        assert res.groups is None

    def test_add_groups_to_project_route_include_groups(self):
        project_uuid = uuid.uuid4()
        project_config = get_plain_gateway('my-route')
        service = GroupService(
            group_dao=self.group_dao,
            key_service=self.key_service,
            group_route_dao=self.group_route_dao,
            project_configs={
                'my-project': ProjectEntry(uuid=_MY_PROJECT_UUID, config=project_config)
            },
        )
        g1_uuid = uuid.uuid4()
        group = db_mock.get_sample_group_plain(uuid=g1_uuid, name='team-a')
        group_route = db_mock.get_sample_group_route(
            group_uuid=g1_uuid,
            route_name='my-route',
            group_name='team-a',
            project_uuid=project_uuid,
        )
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.group_route_dao.add_bulk = MagicMock(return_value=[group_route])
        route_groups_in = RouteGroupsIn(groups=[g1_uuid])
        res = service.add_groups_to_project_route(
            project_uuid=project_uuid,
            project_name='my-project',
            route_name='my-route',
            route_groups_in=route_groups_in,
            include_groups=True,
        )
        assert isinstance(res, GroupsRouteOut)
        assert res.route_name == 'my-route'
        assert res.project_name == 'my-project'
        assert res.groups is not None
        assert len(res.groups) == 1
        assert res.groups[0].uuid == group.uuid

    def test_add_groups_to_project_route_not_found(self):
        service = GroupService(
            group_dao=self.group_dao,
            key_service=self.key_service,
            group_route_dao=self.group_route_dao,
            project_configs={},
        )
        pytest.raises(
            RouteNotFoundError,
            service.add_groups_to_project_route,
            uuid.uuid4(),
            'my-project',
            'nonexistent-route',
            RouteGroupsIn(groups=[uuid.uuid4()]),
            False,
        )
        self.group_route_dao.add_bulk.assert_not_called()

    def test_add_groups_to_project_route_integrity_error(self):
        project_uuid = uuid.uuid4()
        project_config = get_plain_gateway('my-route')
        service = GroupService(
            group_dao=self.group_dao,
            key_service=self.key_service,
            group_route_dao=self.group_route_dao,
            project_configs={
                'my-project': ProjectEntry(uuid=_MY_PROJECT_UUID, config=project_config)
            },
        )
        g_uuid = uuid.uuid4()
        self.group_dao.get_by_uuid = MagicMock(
            return_value=db_mock.get_sample_group_plain(uuid=g_uuid)
        )
        self.group_route_dao.add_bulk = MagicMock(
            side_effect=IntegrityError(None, None, BaseException())
        )
        pytest.raises(
            GroupAlreadyExistsError,
            service.add_groups_to_project_route,
            project_uuid,
            'my-project',
            'my-route',
            RouteGroupsIn(groups=[g_uuid]),
            False,
        )

    def test_add_groups_to_project_route_group_not_found(self):
        project_uuid = uuid.uuid4()
        project_config = get_plain_gateway('my-route')
        service = GroupService(
            group_dao=self.group_dao,
            key_service=self.key_service,
            group_route_dao=self.group_route_dao,
            project_configs={
                'my-project': ProjectEntry(uuid=_MY_PROJECT_UUID, config=project_config)
            },
        )
        nonexistent_uuid = uuid.uuid4()
        self.group_dao.get_by_uuid = MagicMock(return_value=None)
        pytest.raises(
            GroupNotFoundError,
            service.add_groups_to_project_route,
            project_uuid,
            'my-project',
            'my-route',
            RouteGroupsIn(groups=[nonexistent_uuid]),
            False,
        )
        self.group_route_dao.add_bulk.assert_not_called()

    def test_get_associable_routes_includes_project_routes(self):
        """get_associable_routes lists project routes alongside static routes."""
        project_config = get_plain_gateway('proj-route')
        service = GroupService(
            group_dao=self.group_dao,
            key_service=self.key_service,
            group_route_dao=self.group_route_dao,
            project_configs={
                'my-project': ProjectEntry(uuid=_MY_PROJECT_UUID, config=project_config)
            },
        )
        group = db_mock.get_sample_group_plain()
        self.group_dao.get_by_uuid = MagicMock(return_value=group)
        self.group_dao.get_route_names_by_group_uuid = MagicMock(return_value=[])
        res = service.get_associable_routes(group.uuid, 'my-project')
        names = {r.name for r in res}
        assert 'proj-route' in names
        route = next(r for r in res if r.name == 'proj-route')
        assert route.project_uuid == _MY_PROJECT_UUID
        assert route.project_name == 'my-project'

    def test_cleanup_orphaned_associations_keeps_served_routes(self):
        """Cleanup passes the served config's route names as the keep-list."""
        self.group_dao.delete_orphaned_associations = MagicMock(return_value=2)
        removed = self.group_service.cleanup_orphaned_associations(
            _MY_PROJECT_UUID, 'my-project'
        )
        assert removed == 2
        self.group_dao.delete_orphaned_associations.assert_called_once()
        args = self.group_dao.delete_orphaned_associations.call_args.args
        assert args[0] == _MY_PROJECT_UUID
        assert set(args[1]) == {'route-A', 'route-B'}

    def test_cleanup_orphaned_associations_unknown_project_deletes_all(self):
        """With no served config the keep-list is empty, so every association is
        removed.
        """
        self.group_dao.delete_orphaned_associations = MagicMock(return_value=3)
        removed = self.group_service.cleanup_orphaned_associations(
            uuid.uuid4(), 'unknown-project'
        )
        assert removed == 3
        args = self.group_dao.delete_orphaned_associations.call_args.args
        assert args[1] == []
