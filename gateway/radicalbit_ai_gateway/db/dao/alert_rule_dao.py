from collections.abc import Sequence
import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, select

from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule
from radicalbit_ai_gateway.models.alert_rule_dto import AlertRuleScope


class AlertRuleDAO:
    def __init__(self, database: Database):
        self.db = database

    def insert(self, alert_rule: AlertRule) -> AlertRule:
        with self.db.begin_session() as session:
            session.add(alert_rule)
            session.flush()
            return alert_rule

    def get_by_uuid(self, alert_rule_uuid: UUID) -> AlertRule | None:
        with self.db.begin_session() as session:
            stmt = select(AlertRule).where(
                AlertRule.uuid == alert_rule_uuid,
                AlertRule.deleted == False,  # noqa: E712
            )
            return session.scalar(stmt)

    def get_all(self) -> Sequence[AlertRule]:
        with self.db.begin_session() as session:
            stmt = (
                select(AlertRule)
                .where(AlertRule.deleted == False)  # noqa: E712
                .order_by(AlertRule.created_at.desc())
            )
            return session.scalars(stmt).all()

    def get_enabled_route_rules(
        self, project_uuid: str, route_name: str
    ) -> Sequence[AlertRule]:
        return self._get_enabled(
            AlertRule.scope == AlertRuleScope.ROUTE.value,
            AlertRule.project == project_uuid,
            AlertRule.route == route_name,
        )

    def get_enabled_project_rules(self, project_uuid: str) -> Sequence[AlertRule]:
        return self._get_enabled(
            AlertRule.scope == AlertRuleScope.PROJECT.value,
            AlertRule.project == project_uuid,
        )

    def get_enabled_credential_rules(
        self, credential_uuid: UUID
    ) -> Sequence[AlertRule]:
        return self._get_enabled(
            AlertRule.scope == AlertRuleScope.CREDENTIAL.value,
            AlertRule.credential_uuid == credential_uuid,
        )

    def _get_enabled(self, *conditions: ColumnElement[bool]) -> Sequence[AlertRule]:
        with self.db.begin_session() as session:
            stmt = select(AlertRule).where(
                *conditions,
                AlertRule.enabled == True,  # noqa: E712
                AlertRule.deleted == False,  # noqa: E712
            )
            return session.scalars(stmt).all()

    def soft_delete_by_uuid(self, alert_rule_uuid: UUID) -> AlertRule | None:
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        now = datetime.datetime.now(tz=UTC)
        with self.db.begin_session() as session:
            rule = session.scalar(
                select(AlertRule).where(
                    AlertRule.uuid == alert_rule_uuid,
                    AlertRule.deleted == False,  # noqa: E712
                )
            )
            if not rule:
                return None
            rule.deleted = True
            rule.updated_at = now
            session.flush()
            return rule

    def toggle_enabled(self, alert_rule_uuid: UUID, enabled: bool) -> AlertRule | None:
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        now = datetime.datetime.now(tz=UTC)
        with self.db.begin_session() as session:
            rule = session.scalar(
                select(AlertRule).where(
                    AlertRule.uuid == alert_rule_uuid,
                    AlertRule.deleted == False,  # noqa: E712
                )
            )
            if not rule:
                return None
            rule.enabled = enabled
            rule.updated_at = now
            session.flush()
            return rule

    def update_rule(
        self, alert_rule_uuid: UUID, update_fields: dict
    ) -> AlertRule | None:
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        now = datetime.datetime.now(tz=UTC)
        with self.db.begin_session() as session:
            rule = session.scalar(
                select(AlertRule).where(
                    AlertRule.uuid == alert_rule_uuid,
                    AlertRule.deleted == False,  # noqa: E712
                )
            )
            if not rule:
                return None
            for field, value in update_fields.items():
                if hasattr(rule, field):
                    setattr(rule, field, value)
            rule.updated_at = now
            session.flush()
            return rule
