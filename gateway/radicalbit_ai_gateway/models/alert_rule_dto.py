import datetime
from enum import Enum, StrEnum
import json
import re
from typing import Any
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


class _LenientEnum(str, Enum):
    """Accepts a value or a member name in any case, as older clients send either."""

    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            for member in cls:
                if member.value == value.lower() or member.name == value.upper():
                    return member
        return None


class AlertRuleScope(_LenientEnum):
    ROUTE = 'route'
    PROJECT = 'project'
    CREDENTIAL = 'credential'


class AlertRuleTimeAggregation(_LenientEnum):
    INSTANT = 'instant'
    WINDOW = 'window'
    LIMIT_WINDOW = 'limit_window'


class AlertRuleWindowSize(_LenientEnum):
    FIVE_MINUTES = '5m'
    FIFTEEN_MINUTES = '15m'
    ONE_HOUR = '1h'
    SIX_HOURS = '6h'
    ONE_DAY = '24h'


class AlertRuleChannel(_LenientEnum):
    EMAIL = 'email'


class AlertableEventAggregation(StrEnum):
    """The time aggregations a rule on an alertable event may use."""

    SELECTABLE = 'selectable'  # instant or window, the user chooses
    LIMIT_WINDOW = 'limit_window'


class AlertRuleIn(BaseModel):
    name: str
    description: str | None = None
    scope: AlertRuleScope = AlertRuleScope.ROUTE
    project: str | None = None  # the project uuid
    route: str | None = None
    credential: UUID | None = None
    event: str
    time_aggregation: AlertRuleTimeAggregation = AlertRuleTimeAggregation.INSTANT
    window_size: AlertRuleWindowSize | None = None
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
        now = datetime.datetime.now(tz=datetime.UTC)
        return AlertRule(
            name=self.name,
            description=self.description,
            scope=self.scope.value,
            project=self.project,
            route=self.route,
            credential_uuid=self.credential,
            event=self.event,
            time_aggregation=self.time_aggregation.value,
            window_size=self.window_size.value if self.window_size else None,
            channel=self.channel.value,
            recipients=json.dumps(self.recipients),
            enabled=self.enabled,
            deleted=False,
            created_at=now,
            updated_at=now,
        )


class AlertRuleUpdateIn(BaseModel):
    name: str | None = None
    description: str | None = None
    scope: AlertRuleScope | None = None
    project: str | None = None  # the project uuid
    route: str | None = None
    credential: UUID | None = None
    event: str | None = None
    time_aggregation: AlertRuleTimeAggregation | None = None
    window_size: AlertRuleWindowSize | None = None
    channel: AlertRuleChannel | None = None
    recipients: list[str] | None = Field(None, min_length=1)

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    @field_validator('recipients')
    @classmethod
    def validate_recipients_format(cls, v: list[str] | None) -> list[str] | None:
        return _validate_recipients(v)

    def to_update_fields(self) -> dict[str, Any]:
        """Return the fields the client sent, as `AlertRule` column values."""
        fields = self.model_dump(exclude_unset=True)
        if 'credential' in fields:
            fields['credential_uuid'] = fields.pop('credential')
        if fields.get('recipients') is not None:
            fields['recipients'] = json.dumps(fields['recipients'])
        return {k: v.value if isinstance(v, Enum) else v for k, v in fields.items()}


class AlertRuleToggleIn(BaseModel):
    enabled: bool

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class AlertRuleOut(BaseModel):
    uuid: UUID
    name: str
    description: str | None = None
    scope: AlertRuleScope
    project: str | None = None
    project_name: str | None = None
    route: str | None = None
    credential_uuid: UUID | None = None
    credential_name: str | None = None
    event: str
    time_aggregation: AlertRuleTimeAggregation
    window_size: AlertRuleWindowSize | None = None
    channel: AlertRuleChannel
    recipients: list[str]
    enabled: bool
    stale: bool = False
    stale_reason: str | None = None
    created_at: str
    updated_at: str

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    @staticmethod
    def from_alert_rule(
        alert_rule: AlertRule,
        project_name: str | None = None,
        credential_name: str | None = None,
        stale_reason: str | None = None,
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
            scope=(
                AlertRuleScope(alert_rule.scope)
                if alert_rule.scope
                else AlertRuleScope.ROUTE
            ),
            project=alert_rule.project,
            project_name=project_name,
            route=alert_rule.route,
            credential_uuid=alert_rule.credential_uuid,
            credential_name=credential_name,
            event=alert_rule.event,
            time_aggregation=(
                AlertRuleTimeAggregation(alert_rule.time_aggregation)
                if alert_rule.time_aggregation
                else AlertRuleTimeAggregation.INSTANT
            ),
            window_size=(
                AlertRuleWindowSize(alert_rule.window_size)
                if alert_rule.window_size
                else None
            ),
            channel=(
                AlertRuleChannel(alert_rule.channel)
                if alert_rule.channel
                else AlertRuleChannel.EMAIL
            ),
            recipients=parsed_recipients,
            enabled=alert_rule.enabled,
            stale=stale_reason is not None,
            stale_reason=stale_reason,
            created_at=str(alert_rule.created_at),
            updated_at=str(alert_rule.updated_at),
        )


class AlertableEventItem(BaseModel):
    event: str
    label: str
    aggregation: AlertableEventAggregation

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class AlertableEventsOut(BaseModel):
    guardrail: list[AlertableEventItem] = Field(default_factory=list)
    fallback: list[AlertableEventItem] = Field(default_factory=list)

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )
