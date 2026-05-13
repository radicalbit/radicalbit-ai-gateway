import uuid

from tests.common import db_mock
from tests.common.db_integration import DatabaseIntegration

from radicalbit_ai_gateway.db.dao.group_dao import GroupDAO
from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO


class GroupDAOTest(DatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group_dao = GroupDAO(cls.db)
        cls.project_dao = ProjectDAO(cls.db)
        cls.project_uuid = uuid.uuid4()

    def setUp(self):
        self.project_dao.insert(
            db_mock.get_sample_project(uuid=self.project_uuid, name='my-project')
        )

    def tearDown(self):
        super().tearDown()

    def test_insert(self):
        group = db_mock.get_sample_group(group_routes=[])
        inserted = self.group_dao.insert(group)
        assert inserted.uuid == group.uuid

    def test_get_all(self):
        groups = [
            db_mock.get_sample_group(uuid=uuid.uuid4(), name='one', group_routes=[]),
            db_mock.get_sample_group(uuid=uuid.uuid4(), name='two', group_routes=[]),
            db_mock.get_sample_group(uuid=uuid.uuid4(), name='three', group_routes=[]),
        ]
        _ = [self.group_dao.insert(i) for i in groups]
        res = self.group_dao.get_all()
        assert len(res) == 3

    def test_add_route(self):
        group_uuid = uuid.uuid4()
        group_route = db_mock.get_sample_group_route(
            group_uuid=group_uuid,
            route_name='rb-gateway',
            project_uuid=self.project_uuid,
        )
        inserted_group_route = self.group_dao.add_route(group_route)
        assert inserted_group_route.route_name == group_route.route_name
        assert inserted_group_route.group_uuid == group_uuid

    def test_delete_group(self):
        groups = [
            db_mock.get_sample_group(uuid=uuid.uuid4(), name='one', group_routes=[]),
            db_mock.get_sample_group(uuid=uuid.uuid4(), name='two', group_routes=[]),
        ]
        _ = [self.group_dao.insert(i) for i in groups]
        res = self.group_dao.get_all()
        assert len(res) == 2
        deleted_group = self.group_dao.delete_by_uuid(groups[0].uuid)
        assert deleted_group.uuid == groups[0].uuid
        res = self.group_dao.get_all()
        assert len(res) == 1

    def test_get_group_by_uuid(self):
        group = db_mock.get_sample_group(group_routes=[])
        inserted = self.group_dao.insert(group)
        assert inserted.uuid == group.uuid
        retrieved_group = self.group_dao.get_by_uuid(group.uuid)
        assert retrieved_group.uuid == group.uuid
        assert retrieved_group.name == group.name

    def test_update_group_name(self):
        group = db_mock.get_sample_group(group_routes=[])
        inserted = self.group_dao.insert(group)
        assert inserted.uuid == group.uuid
        new_name = 'group-new-name'
        update_rows = self.group_dao.update_group_name(group.uuid, new_name)
        assert update_rows == 1
        retrieved_group = self.group_dao.get_by_uuid(group.uuid)
        assert retrieved_group.uuid == group.uuid
        assert retrieved_group.name == new_name

    def test_get_all_group_by_route_name(self):
        dev_uuid = uuid.uuid4()
        admin_uuid = uuid.uuid4()

        group_route = db_mock.get_sample_group_route(
            group_uuid=dev_uuid,
            group_name='dev-group',
            route_name='rb-gateway',
            project_uuid=self.project_uuid,
        )
        self.group_dao.add_route(group_route)

        group_route = db_mock.get_sample_group_route(
            group_uuid=admin_uuid,
            group_name='admin-group',
            route_name='rb-gateway',
            project_uuid=self.project_uuid,
        )
        self.group_dao.add_route(group_route)

        rows = self.group_dao.get_all_group_by_route_name(
            self.project_uuid, 'rb-gateway'
        )
        assert len(rows) == 2

    def test_get_all_group_by_route_name_empty(self):
        dev_uuid = uuid.uuid4()
        group = db_mock.get_sample_group(uuid=dev_uuid, name='dev', group_routes=[])
        _ = self.group_dao.insert(group)
        rows = self.group_dao.get_all_group_by_route_name(
            self.project_uuid, 'rb-gateway'
        )
        assert len(rows) == 0

    def test_get_all_group_by_route_name_filters_correctly(self):
        dev_group_uuid = uuid.uuid4()
        admin_group_uuid = uuid.uuid4()

        dev_route = db_mock.get_sample_group_route(
            group_uuid=dev_group_uuid,
            route_name='route-A',
            group_name='group',
            project_uuid=self.project_uuid,
        )
        self.group_dao.add_route(dev_route)

        admin_route = db_mock.get_sample_group_route(
            group_uuid=admin_group_uuid,
            route_name='route-B',
            group_name='another-group',
            project_uuid=self.project_uuid,
        )
        self.group_dao.add_route(admin_route)

        rows = self.group_dao.get_all_group_by_route_name(self.project_uuid, 'route-A')
        assert len(rows) == 1
        assert rows[0].uuid == dev_group_uuid
        assert rows[0].name == 'group'

    def test_get_all_group_by_non_existent_route_name(self):
        dev_route = db_mock.get_sample_group_route(
            route_name='an-existing-route', project_uuid=self.project_uuid
        )
        self.group_dao.add_route(dev_route)
        rows = self.group_dao.get_all_group_by_route_name(
            self.project_uuid, 'this-route-does-not-exist'
        )
        assert len(rows) == 0

    def test_get_group_associated_with_multiple_routes(self):
        power_user_group_uuid = uuid.uuid4()
        user_group_uuid = uuid.uuid4()
        route1 = db_mock.get_sample_group_route(
            group_uuid=power_user_group_uuid,
            route_name='route-A',
            project_uuid=self.project_uuid,
        )
        self.group_dao.add_route(route1)
        route2 = db_mock.get_sample_group_route(
            group_uuid=user_group_uuid,
            route_name='route-b',
            project_uuid=self.project_uuid,
        )
        self.group_dao.add_route(route2)
        rows_for_A = self.group_dao.get_all_group_by_route_name(
            self.project_uuid, 'route-A'
        )
        rows_for_B = self.group_dao.get_all_group_by_route_name(
            self.project_uuid, 'route-b'
        )
        assert len(rows_for_A) == 1
        assert rows_for_A[0].uuid == power_user_group_uuid
        assert len(rows_for_B) == 1
        assert rows_for_B[0].uuid == user_group_uuid
