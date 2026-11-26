"""Dispatch finds the enabled rules watching an event's target, scope by scope."""

import datetime
import json
import uuid

from typing_extensions import override

from tests.common.db_integration import AsyncDatabaseIntegration

from radicalbit_ai_gateway.db.dao.alert_rule_dao import AlertRuleDAO
from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule

PROJECT = str(uuid.uuid4())
CREDENTIAL = uuid.uuid4()


class AlertRuleDAOTest(AsyncDatabaseIntegration):
    @override
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dao = AlertRuleDAO(cls.db)

    async def rule(self, scope: str, **columns) -> AlertRule:
        now = datetime.datetime.now(tz=datetime.UTC)
        return await self.insert(
            AlertRule(
                **{
                    'name': f'{scope} rule',
                    'scope': scope,
                    'event': 'some-event',
                    'time_aggregation': 'instant',
                    'channel': 'email',
                    'recipients': json.dumps(['ops@example.com']),
                    'enabled': True,
                    'deleted': False,
                    'created_at': now,
                    'updated_at': now,
                    **columns,
                }
            )
        )

    @staticmethod
    def names(rules) -> set[str]:
        return {r.name for r in rules}

    async def test_route_rules_are_found_by_project_uuid_and_route(self):
        await self.rule('route', project=PROJECT, route='chat', name='hit')
        await self.rule('route', project=PROJECT, route='summarise', name='other route')
        await self.rule(
            'route', project=str(uuid.uuid4()), route='chat', name='other project'
        )
        await self.rule('project', project=PROJECT, name='project scope')

        found = await self.dao.get_enabled_route_rules(PROJECT, 'chat')

        assert self.names(found) == {'hit'}

    async def test_project_rules_are_found_by_project_uuid(self):
        await self.rule('project', project=PROJECT, name='hit')
        await self.rule('project', project=str(uuid.uuid4()), name='other project')
        await self.rule('route', project=PROJECT, route='chat', name='route scope')

        found = await self.dao.get_enabled_project_rules(PROJECT)

        assert self.names(found) == {'hit'}

    async def test_credential_rules_are_found_by_credential_uuid(self):
        await self.rule('credential', credential_uuid=CREDENTIAL, name='hit')
        await self.rule(
            'credential', credential_uuid=uuid.uuid4(), name='other credential'
        )

        found = await self.dao.get_enabled_credential_rules(CREDENTIAL)

        assert self.names(found) == {'hit'}

    async def test_disabled_and_deleted_rules_are_not_found(self):
        await self.rule('project', project=PROJECT, enabled=False)
        await self.rule('project', project=PROJECT, deleted=True)

        assert await self.dao.get_enabled_project_rules(PROJECT) == []

    async def test_a_rule_is_read_back_by_uuid_and_not_once_deleted(self):
        rule = await self.rule('project', project=PROJECT, name='kept')

        found = await self.dao.get_by_uuid(rule.uuid)
        deleted = await self.dao.soft_delete_by_uuid(rule.uuid)

        assert found is not None
        assert found.name == 'kept'
        assert deleted is not None
        assert deleted.deleted is True
        assert await self.dao.get_by_uuid(rule.uuid) is None
        assert await self.dao.soft_delete_by_uuid(rule.uuid) is None

    async def test_all_rules_are_listed_newest_first_without_deleted_ones(self):
        old = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        new = datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC)
        await self.rule('project', project=PROJECT, name='old', created_at=old)
        await self.rule('project', project=PROJECT, name='new', created_at=new)
        await self.rule('project', project=PROJECT, name='gone', deleted=True)

        assert [r.name for r in await self.dao.get_all()] == ['new', 'old']

    async def test_a_rule_is_inserted_toggled_and_updated(self):
        now = datetime.datetime.now(tz=datetime.UTC)
        inserted = await self.dao.insert(
            AlertRule(
                name='new rule',
                scope='project',
                project=PROJECT,
                event='some-event',
                time_aggregation='instant',
                channel='email',
                recipients=json.dumps(['ops@example.com']),
                enabled=False,
                deleted=False,
                created_at=now,
                updated_at=now,
            )
        )

        toggled = await self.dao.toggle_enabled(inserted.uuid, True)
        updated = await self.dao.update_rule(inserted.uuid, {'name': 'renamed'})

        assert inserted.uuid is not None
        reread = await self.dao.get_by_uuid(inserted.uuid)
        assert toggled is not None
        assert toggled.enabled is True
        assert updated is not None
        assert updated.name == 'renamed'
        assert reread is not None
        assert reread.name == 'renamed'
        assert await self.dao.toggle_enabled(uuid.uuid4(), True) is None
        assert await self.dao.update_rule(uuid.uuid4(), {'name': 'x'}) is None
