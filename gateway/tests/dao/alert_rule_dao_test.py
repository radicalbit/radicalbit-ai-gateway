"""Dispatch finds the enabled rules watching an event's target, scope by scope."""

import datetime
import json
import uuid

from tests.common.db_integration import DatabaseIntegration

from radicalbit_ai_gateway.db.dao.alert_rule_dao import AlertRuleDAO
from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule

PROJECT = str(uuid.uuid4())
CREDENTIAL = uuid.uuid4()


class AlertRuleDAOTest(DatabaseIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dao = AlertRuleDAO(cls.db)

    def setUp(self):
        with self.db.begin_session() as session:
            session.query(AlertRule).delete()

    def rule(self, scope: str, **columns) -> AlertRule:
        now = datetime.datetime.now(tz=datetime.UTC)
        return self.insert(
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

    def test_route_rules_are_found_by_project_uuid_and_route(self):
        self.rule('route', project=PROJECT, route='chat', name='hit')
        self.rule('route', project=PROJECT, route='summarise', name='other route')
        self.rule(
            'route', project=str(uuid.uuid4()), route='chat', name='other project'
        )
        self.rule('project', project=PROJECT, name='project scope')

        found = self.dao.get_enabled_route_rules(PROJECT, 'chat')

        assert self.names(found) == {'hit'}

    def test_project_rules_are_found_by_project_uuid(self):
        self.rule('project', project=PROJECT, name='hit')
        self.rule('project', project=str(uuid.uuid4()), name='other project')
        self.rule('route', project=PROJECT, route='chat', name='route scope')

        found = self.dao.get_enabled_project_rules(PROJECT)

        assert self.names(found) == {'hit'}

    def test_credential_rules_are_found_by_credential_uuid(self):
        self.rule('credential', credential_uuid=CREDENTIAL, name='hit')
        self.rule('credential', credential_uuid=uuid.uuid4(), name='other credential')

        found = self.dao.get_enabled_credential_rules(CREDENTIAL)

        assert self.names(found) == {'hit'}

    def test_disabled_and_deleted_rules_are_not_found(self):
        self.rule('project', project=PROJECT, enabled=False)
        self.rule('project', project=PROJECT, deleted=True)

        assert self.dao.get_enabled_project_rules(PROJECT) == []
