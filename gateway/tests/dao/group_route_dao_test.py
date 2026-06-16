import uuid

from tests.common import db_mock
from tests.common.db_integration import DatabaseIntegration

from radicalbit_ai_gateway.db.dao.group_dao import GroupDAO
from radicalbit_ai_gateway.db.dao.group_route_dao import GroupRouteDAO
from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO


class GroupRouteDAOTest(DatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group_route_dao = GroupRouteDAO(cls.db)
        cls.group_dao = GroupDAO(cls.db)
        cls.project_dao = ProjectDAO(cls.db)
        cls.group_one, cls.group_two, cls.group_three = (
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
        )
        cls.project_uuid = uuid.uuid4()

    def setUp(self):
        self.project_dao.insert(
            db_mock.get_sample_project(uuid=self.project_uuid, name='my-project')
        )

    def tearDown(self):
        super().tearDown()

    def test_add_bulk_success(self):
        group_keys = [
            db_mock.get_sample_group_route(
                group_uuid=self.group_one,
                route_name='route-A',
                project_uuid=self.project_uuid,
            ),
            db_mock.get_sample_group_route(
                group_uuid=self.group_two,
                route_name='route-B',
                project_uuid=self.project_uuid,
            ),
            db_mock.get_sample_group_route(
                group_uuid=self.group_three,
                route_name='route-C',
                project_uuid=self.project_uuid,
            ),
        ]
        inserted = self.group_route_dao.add_bulk(group_keys)
        assert len(inserted) == 3

    def test_add_bulk_with_empty_list(self):
        empty_list = []
        inserted_items = self.group_route_dao.add_bulk(empty_list)
        assert inserted_items == []

    def test_add_bulk_with_single_item(self):
        single_group_route = [
            db_mock.get_sample_group_route(
                group_uuid=self.group_one,
                route_name='route-A',
                project_uuid=self.project_uuid,
            )
        ]
        inserted_items = self.group_route_dao.add_bulk(single_group_route)
        assert len(inserted_items) == 1
        assert str(inserted_items[0].route_name) == str(
            single_group_route[0].route_name
        )

    def test_add_bulk_with_project_uuid_stores_local_route_name(self):
        group_route = db_mock.get_sample_group_route(
            group_uuid=self.group_one,
            route_name='route-A',
            project_uuid=self.project_uuid,
        )
        inserted = self.group_route_dao.add_bulk([group_route])
        assert len(inserted) == 1
        assert inserted[0].project_uuid == self.project_uuid
        assert inserted[0].route_name == 'route-A'

    def test_add_bulk_two_projects_same_local_route_name(self):
        project_b_uuid = uuid.uuid4()
        self.project_dao.insert(
            db_mock.get_sample_project(uuid=project_b_uuid, name='other-project')
        )
        routes = [
            db_mock.get_sample_group_route(
                group_uuid=self.group_one,
                route_name='gpt-4',
                project_uuid=self.project_uuid,
            ),
            db_mock.get_sample_group_route(
                group_uuid=self.group_two,
                route_name='gpt-4',
                project_uuid=project_b_uuid,
            ),
        ]
        inserted = self.group_route_dao.add_bulk(routes)
        assert len(inserted) == 2
        project_uuids = {r.project_uuid for r in inserted}
        assert self.project_uuid in project_uuids
        assert project_b_uuid in project_uuids

    def test_delete_orphaned_associations_removes_routes_absent_from_config(self):
        routes = [
            db_mock.get_sample_group_route(
                group_uuid=self.group_one,
                route_name='route-A',
                project_uuid=self.project_uuid,
            ),
            db_mock.get_sample_group_route(
                group_uuid=self.group_two,
                route_name='gone-route',
                project_uuid=self.project_uuid,
            ),
        ]
        self.group_route_dao.add_bulk(routes)
        removed = self.group_dao.delete_orphaned_associations(
            self.project_uuid, ['route-A']
        )
        assert removed == 1
        remaining = self.group_dao.get_all_group_by_route_name(
            self.project_uuid, 'gone-route'
        )
        assert remaining == []

    def test_delete_orphaned_associations_empty_keep_list_removes_all(self):
        routes = [
            db_mock.get_sample_group_route(
                group_uuid=self.group_one,
                route_name='route-A',
                project_uuid=self.project_uuid,
            ),
            db_mock.get_sample_group_route(
                group_uuid=self.group_two,
                route_name='route-B',
                project_uuid=self.project_uuid,
            ),
        ]
        self.group_route_dao.add_bulk(routes)
        removed = self.group_dao.delete_orphaned_associations(self.project_uuid, [])
        assert removed == 2
