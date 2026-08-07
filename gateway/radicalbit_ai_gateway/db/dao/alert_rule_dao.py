from collections.abc import Sequence
import datetime
import logging
from uuid import UUID

from sqlalchemy import or_, select

from radicalbit_ai_gateway.db.database import Database
from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule

logger = logging.getLogger('radicalbit-ai-gateway')


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

    def get_active_by_route(
        self, project_uuid: str = '', route_name: str = '', project_name: str = ''
    ) -> Sequence[AlertRule]:
        if not project_uuid and not project_name:
            logger.error(
                'Missing project identification when querying active alert rules for route %s',
                route_name,
            )
            return []

        with self.db.begin_session() as session:
            conditions = [
                AlertRule.route == route_name,
                AlertRule.enabled == True,  # noqa: E712
                AlertRule.deleted == False,  # noqa: E712
            ]

            p_filters = []
            if project_uuid:
                p_filters.append(AlertRule.project == project_uuid)
            if project_name:
                p_filters.append(AlertRule.project == project_name)

            if p_filters:
                conditions.append(or_(*p_filters))

            stmt = select(AlertRule).where(*conditions)
            return session.scalars(stmt).all()

    def get_all_by_route(
        self, project_name: str, route_name: str
    ) -> Sequence[AlertRule]:
        with self.db.begin_session() as session:
            stmt = select(AlertRule).where(
                AlertRule.project == project_name,
                AlertRule.route == route_name,
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

    def toggle_enabled(
        self, alert_rule_uuid: UUID, enabled: bool, clear_disabled_reason: bool = True
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
            rule.enabled = enabled
            if enabled and clear_disabled_reason:
                rule.disabled_reason = None
            rule.updated_at = now
            session.flush()
            return rule

    def auto_disable_rule(self, alert_rule_uuid: UUID, reason: str) -> AlertRule | None:
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
            rule.enabled = False
            rule.disabled_reason = reason
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
