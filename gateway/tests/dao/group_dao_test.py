import uuid

from typing_extensions import override

from tests.common import db_mock
from tests.common.db_integration import AsyncDatabaseIntegration

from radicalbit_ai_gateway.db.dao.group_dao import GroupDAO
from radicalbit_ai_gateway.db.dao.key_dao import KeyDAO
from radicalbit_ai_gateway.db.dao.key_limit_dao import KeyLimitDAO
from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO
from radicalbit_ai_gateway.db.tables.group_route_table import GroupRoute


class GroupDAOTest(AsyncDatabaseIntegration):
    @override
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group_dao = GroupDAO(cls.db)
        cls.key_dao = KeyDAO(cls.db)
        cls.key_limit_dao = KeyLimitDAO(cls.db)
        cls.project_dao = ProjectDAO(cls.db)
        cls.project_uuid = uuid.uuid4()

    @override
    async def asyncSetUp(self):
        await self.insert(
            db_mock.get_sample_project(uuid=self.project_uuid, name='my-project')
        )

    async def test_insert(self):
        group = db_mock.get_sample_group(group_routes=[])
        inserted = await self.group_dao.insert(group)
        assert inserted.uuid == group.uuid

    async def test_get_all(self):
        groups = [
            db_mock.get_sample_group(uuid=uuid.uuid4(), name='one', group_routes=[]),
            db_mock.get_sample_group(uuid=uuid.uuid4(), name='two', group_routes=[]),
            db_mock.get_sample_group(uuid=uuid.uuid4(), name='three', group_routes=[]),
        ]
        _ = [await self.group_dao.insert(i) for i in groups]
        res = await self.group_dao.get_all()
        assert len(res) == 3

    async def test_add_route(self):
        group_uuid = uuid.uuid4()
        group_route = db_mock.get_sample_group_route(
            group_uuid=group_uuid,
            route_name='rb-gateway',
            project_uuid=self.project_uuid,
        )
        inserted_group_route = await self.group_dao.add_route(group_route)
        assert inserted_group_route.route_name == group_route.route_name
        assert inserted_group_route.group_uuid == group_uuid

    async def test_delete_group(self):
        groups = [
            db_mock.get_sample_group(uuid=uuid.uuid4(), name='one', group_routes=[]),
            db_mock.get_sample_group(uuid=uuid.uuid4(), name='two', group_routes=[]),
        ]
        _ = [await self.group_dao.insert(i) for i in groups]
        res = await self.group_dao.get_all()
        assert len(res) == 2
        deleted_group = await self.group_dao.delete_by_uuid(groups[0].uuid)
        assert deleted_group is not None
        assert deleted_group.uuid == groups[0].uuid
        res = await self.group_dao.get_all()
        assert len(res) == 1

    async def test_deleting_a_group_keeps_its_credentials_and_their_limits(self):
        group = db_mock.get_sample_group(uuid=uuid.uuid4(), group_routes=[])
        await self.group_dao.insert(group)
        key = db_mock.get_sample_key(uuid=uuid.uuid4(), group_uuid=group.uuid)
        await self.key_dao.insert(key)
        limit = db_mock.get_sample_key_limit(uuid=uuid.uuid4(), key_uuid=key.uuid)
        await self.key_limit_dao.insert(limit)

        await self.group_dao.delete_by_uuid(group.uuid)

        kept = await self.key_dao.get_by_uuid(key.uuid)
        assert kept is not None
        assert kept.group_uuid is None
        assert [
            item.uuid for item in await self.key_limit_dao.get_by_key_uuid(key.uuid)
        ] == [limit.uuid]

    async def test_get_group_by_uuid(self):
        group = db_mock.get_sample_group(group_routes=[])
        inserted = await self.group_dao.insert(group)
        assert inserted.uuid == group.uuid
        retrieved_group = await self.group_dao.get_by_uuid(group.uuid)
        assert retrieved_group is not None
        assert retrieved_group.uuid == group.uuid
        assert retrieved_group.name == group.name

    async def test_update_group_name(self):
        group = db_mock.get_sample_group(group_routes=[])
        inserted = await self.group_dao.insert(group)
        assert inserted.uuid == group.uuid
        new_name = 'group-new-name'
        update_rows = await self.group_dao.update_group_name(group.uuid, new_name)
        assert update_rows == 1
        retrieved_group = await self.group_dao.get_by_uuid(group.uuid)
        assert retrieved_group is not None
        assert retrieved_group.uuid == group.uuid
        assert retrieved_group.name == new_name

    async def test_get_all_group_by_route_name(self):
        dev_uuid = uuid.uuid4()
        admin_uuid = uuid.uuid4()

        group_route = db_mock.get_sample_group_route(
            group_uuid=dev_uuid,
            group_name='dev-group',
            route_name='rb-gateway',
            project_uuid=self.project_uuid,
        )
        await self.group_dao.add_route(group_route)

        group_route = db_mock.get_sample_group_route(
            group_uuid=admin_uuid,
            group_name='admin-group',
            route_name='rb-gateway',
            project_uuid=self.project_uuid,
        )
        await self.group_dao.add_route(group_route)

        rows = await self.group_dao.get_all_group_by_route_name(
            self.project_uuid, 'rb-gateway'
        )
        assert len(rows) == 2

    async def test_get_all_group_by_route_name_empty(self):
        dev_uuid = uuid.uuid4()
        group = db_mock.get_sample_group(uuid=dev_uuid, name='dev', group_routes=[])
        _ = await self.group_dao.insert(group)
        rows = await self.group_dao.get_all_group_by_route_name(
            self.project_uuid, 'rb-gateway'
        )
        assert len(rows) == 0

    async def test_get_all_group_by_route_name_filters_correctly(self):
        dev_group_uuid = uuid.uuid4()
        admin_group_uuid = uuid.uuid4()

        dev_route = db_mock.get_sample_group_route(
            group_uuid=dev_group_uuid,
            route_name='route-A',
            group_name='group',
            project_uuid=self.project_uuid,
        )
        await self.group_dao.add_route(dev_route)

        admin_route = db_mock.get_sample_group_route(
            group_uuid=admin_group_uuid,
            route_name='route-B',
            group_name='another-group',
            project_uuid=self.project_uuid,
        )
        await self.group_dao.add_route(admin_route)

        rows = await self.group_dao.get_all_group_by_route_name(
            self.project_uuid, 'route-A'
        )
        assert len(rows) == 1
        assert rows[0].uuid == dev_group_uuid
        assert rows[0].name == 'group'

    async def test_get_all_group_by_non_existent_route_name(self):
        dev_route = db_mock.get_sample_group_route(
            route_name='an-existing-route', project_uuid=self.project_uuid
        )
        await self.group_dao.add_route(dev_route)
        rows = await self.group_dao.get_all_group_by_route_name(
            self.project_uuid, 'this-route-does-not-exist'
        )
        assert len(rows) == 0

    async def test_get_route_names_by_group_uuid_excludes_deleted_project_routes(self):
        group_uuid = uuid.uuid4()
        live_project_uuid = self.project_uuid
        deleted_project_uuid = uuid.uuid4()
        await self.insert(
            db_mock.get_sample_project(
                uuid=deleted_project_uuid, name='deleted-project'
            )
        )
        await self.group_dao.insert(
            db_mock.get_sample_group(uuid=group_uuid, group_routes=[])
        )
        await self.group_dao.add_route(
            GroupRoute(
                group_uuid=group_uuid,
                route_name='live-route',
                project_uuid=live_project_uuid,
            )
        )
        await self.group_dao.add_route(
            GroupRoute(
                group_uuid=group_uuid,
                route_name='dead-route',
                project_uuid=deleted_project_uuid,
            )
        )
        await self.project_dao.soft_delete(deleted_project_uuid)
        result = await self.group_dao.get_route_names_by_group_uuid(group_uuid)
        assert result == ['my-project/live-route']

    async def test_get_group_associated_with_multiple_routes(self):
        power_user_group_uuid = uuid.uuid4()
        user_group_uuid = uuid.uuid4()
        route1 = db_mock.get_sample_group_route(
            group_uuid=power_user_group_uuid,
            route_name='route-A',
            project_uuid=self.project_uuid,
        )
        await self.group_dao.add_route(route1)
        route2 = db_mock.get_sample_group_route(
            group_uuid=user_group_uuid,
            route_name='route-b',
            project_uuid=self.project_uuid,
        )
        await self.group_dao.add_route(route2)
        rows_for_A = await self.group_dao.get_all_group_by_route_name(
            self.project_uuid, 'route-A'
        )
        rows_for_B = await self.group_dao.get_all_group_by_route_name(
            self.project_uuid, 'route-b'
        )
        assert len(rows_for_A) == 1
        assert rows_for_A[0].uuid == power_user_group_uuid
        assert len(rows_for_B) == 1
        assert rows_for_B[0].uuid == user_group_uuid

    async def test_get_all_by_owner_returns_only_that_owners_groups(self):
        mine = db_mock.get_sample_group(uuid=uuid.uuid4(), name='mine')
        other = db_mock.get_sample_group(uuid=uuid.uuid4(), name='other')
        other.owner = 'idp'
        await self.group_dao.insert(mine)
        await self.group_dao.insert(other)

        res = await self.group_dao.get_all_by_owner('gateway')

        assert [g.uuid for g in res] == [mine.uuid]

    async def test_delete_by_uuid_of_a_missing_group_returns_none(self):
        assert await self.group_dao.delete_by_uuid(uuid.uuid4()) is None

    async def test_remove_project_route_deletes_only_that_route(self):
        group = db_mock.get_sample_group(uuid=uuid.uuid4(), group_routes=[])
        await self.group_dao.insert(group)
        for route in ('route-A', 'route-B'):
            await self.group_dao.add_route(
                GroupRoute(
                    group_uuid=group.uuid,
                    route_name=route,
                    project_uuid=self.project_uuid,
                )
            )

        removed = await self.group_dao.remove_project_route(
            group.uuid, self.project_uuid, 'route-A'
        )

        assert removed == 1
        assert await self.group_dao.get_route_names_by_group_uuid(group.uuid) == [
            'my-project/route-B'
        ]
        # A route the group no longer has matches nothing.
        assert (
            await self.group_dao.remove_project_route(
                group.uuid, self.project_uuid, 'route-A'
            )
            == 0
        )
        assert (
            await self.group_dao.remove_project_route(
                group.uuid, uuid.uuid4(), 'route-B'
            )
            == 0
        )

    async def test_get_by_name_and_owner(self):
        group = db_mock.get_sample_group(uuid=uuid.uuid4(), name='finance')
        await self.group_dao.insert(group)

        found = await self.group_dao.get_by_name_and_owner('finance', 'gateway')

        assert found is not None
        assert found.uuid == group.uuid
        assert await self.group_dao.get_by_name_and_owner('finance', 'idp') is None

    async def test_check_key_uuid_for_route_finds_the_group_of_a_member_key(self):
        group = db_mock.get_sample_group(uuid=uuid.uuid4(), group_routes=[])
        await self.group_dao.insert(group)
        await self.group_dao.add_route(
            GroupRoute(
                group_uuid=group.uuid,
                route_name='route-A',
                project_uuid=self.project_uuid,
            )
        )
        key = db_mock.get_sample_key(uuid=uuid.uuid4(), group_uuid=group.uuid)
        await self.key_dao.insert(key)

        found = await self.group_dao.check_key_uuid_for_route(
            self.project_uuid, 'route-A', key.uuid
        )

        assert found is not None
        assert found.uuid == group.uuid

    async def test_check_key_uuid_for_route_is_none_off_the_groups_routes(self):
        group = db_mock.get_sample_group(uuid=uuid.uuid4(), group_routes=[])
        await self.group_dao.insert(group)
        await self.group_dao.add_route(
            GroupRoute(
                group_uuid=group.uuid,
                route_name='route-A',
                project_uuid=self.project_uuid,
            )
        )
        member = db_mock.get_sample_key(uuid=uuid.uuid4(), group_uuid=group.uuid)
        stranger = db_mock.get_sample_key(
            uuid=uuid.uuid4(), name='stranger', hashed_key='other-hash'
        )
        await self.key_dao.insert(member)
        await self.key_dao.insert(stranger)

        assert (
            await self.group_dao.check_key_uuid_for_route(
                self.project_uuid, 'route-B', member.uuid
            )
            is None
        )
        assert (
            await self.group_dao.check_key_uuid_for_route(
                self.project_uuid, 'route-A', stranger.uuid
            )
            is None
        )

    async def test_get_names_by_uuids(self):
        one = db_mock.get_sample_group(uuid=uuid.uuid4(), name='one')
        two = db_mock.get_sample_group(uuid=uuid.uuid4(), name='two')
        await self.group_dao.insert(one)
        await self.group_dao.insert(two)

        names = await self.group_dao.get_names_by_uuids([one.uuid, uuid.uuid4()])

        assert names == {one.uuid: 'one'}

    async def test_get_names_by_uuids_with_no_uuids_is_empty(self):
        assert await self.group_dao.get_names_by_uuids([]) == {}
