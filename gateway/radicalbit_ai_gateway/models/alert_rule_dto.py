import datetime
from enum import Enum
import json
import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')


def _validate_recipients(recipients: list[str] | None) -> list[str] | None:
    if recipients is None:
        return None
    cleaned = []
    for r in recipients:
        email = r.strip()
        if not email or not EMAIL_REGEX.match(email):
            raise ValueError(f'Invalid email recipient format: "{r}"')
        cleaned.append(email)
    if not cleaned:
        raise ValueError('At least one email recipient is required')
    return cleaned


class AlertRuleScope(str, Enum):
    ROUTE = 'route'


class AlertRuleTimeAggregation(str, Enum):
    INSTANT = 'instant'
    WINDOW = 'window'


class AlertRuleChannel(str, Enum):
    EMAIL = 'email'


class AlertRuleIn(BaseModel):
    name: str
    description: str | None = None
    project: str
    route: str
    scope: AlertRuleScope = AlertRuleScope.ROUTE
    event: str
    time_aggregation: AlertRuleTimeAggregation = Field(
        AlertRuleTimeAggregation.INSTANT, alias='timeAggregation'
    )
    channel: AlertRuleChannel = AlertRuleChannel.EMAIL
    recipients: list[str] = Field(..., min_length=1)
    enabled: bool = False

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    @field_validator('recipients')
    @classmethod
    def validate_recipients_format(cls, v: list[str]) -> list[str]:
        return _validate_recipients(v) or []

    def to_alert_rule(self) -> AlertRule:
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        now = datetime.datetime.now(tz=UTC)
        return AlertRule(
            name=self.name,
            description=self.description,
            project=self.project,
            route=self.route,
            scope=self.scope.value
            if isinstance(self.scope, Enum)
            else (self.scope or 'route'),
            event=self.event,
            time_aggregation=(
                self.time_aggregation.value
                if isinstance(self.time_aggregation, Enum)
                else (self.time_aggregation or 'instant')
            ),
            channel=(
                self.channel.value
                if isinstance(self.channel, Enum)
                else (self.channel or 'email')
            ),
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
    scope: AlertRuleScope | None = None
    event: str | None = None
    time_aggregation: AlertRuleTimeAggregation | None = Field(
        None, alias='timeAggregation'
    )
    channel: AlertRuleChannel | None = None
    recipients: list[str] | None = Field(None, min_length=1)

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    @field_validator('recipients')
    @classmethod
    def validate_recipients_format(cls, v: list[str] | None) -> list[str] | None:
        return _validate_recipients(v)


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
    project_name: str | None = Field(None, alias='projectName')
    route: str
    scope: AlertRuleScope
    event: str
    time_aggregation: AlertRuleTimeAggregation = Field(..., alias='timeAggregation')
    channel: AlertRuleChannel
    recipients: list[str]
    enabled: bool
    disabled_reason: str | None = Field(None, alias='disabledReason')
    created_at: str = Field(..., alias='createdAt')
    updated_at: str = Field(..., alias='updatedAt')

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    @staticmethod
    def from_alert_rule(
        alert_rule: AlertRule, project_name: str | None = None
    ) -> 'AlertRuleOut':
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
            project_name=project_name,
            route=alert_rule.route,
            scope=(
                AlertRuleScope(alert_rule.scope)
                if alert_rule.scope
                else AlertRuleScope.ROUTE
            ),
            event=alert_rule.event,
            time_aggregation=(
                AlertRuleTimeAggregation(alert_rule.time_aggregation)
                if alert_rule.time_aggregation
                else AlertRuleTimeAggregation.INSTANT
            ),
            channel=(
                AlertRuleChannel(alert_rule.channel)
                if alert_rule.channel
                else AlertRuleChannel.EMAIL
            ),
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
