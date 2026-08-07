import datetime
import json
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule


class AlertRuleIn(BaseModel):
    name: str
    description: str | None = None
    project: str
    route: str
    scope: str = 'route'
    event: str
    time_aggregation: str = Field('instant', alias='timeAggregation')
    channel: str = 'email'
    recipients: list[str] = Field(default_factory=list)
    enabled: bool = False

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    def to_alert_rule(self) -> AlertRule:
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        now = datetime.datetime.now(tz=UTC)
        return AlertRule(
            name=self.name,
            description=self.description,
            project=self.project,
            route=self.route,
            scope=self.scope or 'route',
            event=self.event,
            time_aggregation=self.time_aggregation or 'instant',
            channel=self.channel or 'email',
            recipients=json.dumps(self.recipients),
            enabled=self.enabled,
            disabled_reason=None,
            deleted=False,
            created_at=now,
            updated_at=now,
        )


class AlertRuleUpdateIn(BaseModel):
    name: str | None = None
    description: str | None = None
    project: str | None = None
    route: str | None = None
    scope: str | None = None
    event: str | None = None
    time_aggregation: str | None = Field(None, alias='timeAggregation')
    channel: str | None = None
    recipients: list[str] | None = None

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class AlertRuleToggleIn(BaseModel):
    enabled: bool

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class AlertRuleOut(BaseModel):
    uuid: UUID
    name: str
    description: str | None = None
    project: str
    route: str
    scope: str
    event: str
    time_aggregation: str = Field(..., alias='timeAggregation')
    channel: str
    recipients: list[str]
    enabled: bool
    disabled_reason: str | None = Field(None, alias='disabledReason')
    created_at: str = Field(..., alias='createdAt')
    updated_at: str = Field(..., alias='updatedAt')

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    @staticmethod
    def from_alert_rule(alert_rule: AlertRule) -> 'AlertRuleOut':
        try:
            parsed_recipients = (
                json.loads(alert_rule.recipients) if alert_rule.recipients else []
            )
        except Exception:
            parsed_recipients = (
                [r.strip() for r in alert_rule.recipients.split(',')]
                if alert_rule.recipients
                else []
            )

        return AlertRuleOut(
            uuid=alert_rule.uuid,
            name=alert_rule.name,
            description=alert_rule.description,
            project=alert_rule.project,
            route=alert_rule.route,
            scope=alert_rule.scope,
            event=alert_rule.event,
            time_aggregation=alert_rule.time_aggregation,
            channel=alert_rule.channel,
            recipients=parsed_recipients,
            enabled=alert_rule.enabled,
            disabled_reason=alert_rule.disabled_reason,
            created_at=str(alert_rule.created_at),
            updated_at=str(alert_rule.updated_at),
        )


class AlertableEventItem(BaseModel):
    event: str
    label: str

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class AlertableEventsOut(BaseModel):
    guardrail: list[AlertableEventItem] = Field(default_factory=list)
    caching: list[AlertableEventItem] = Field(default_factory=list)
    fallback: list[AlertableEventItem] = Field(default_factory=list)

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )
