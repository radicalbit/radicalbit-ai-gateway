"""The alert rule DTOs. Service behaviour is covered through the API in
`tests/routes/test_alert_rule_route.py` and dispatch in `tests/alerting`.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule
from radicalbit_ai_gateway.models.alert_rule_dto import (
    AlertRuleChannel,
    AlertRuleIn,
    AlertRuleOut,
    AlertRuleScope,
    AlertRuleTimeAggregation,
)


def test_alert_rule_dto_recipient_validation():
    # Valid recipients
    valid_dto = AlertRuleIn(
        name='Valid',
        project=str(uuid4()),
        route='r1',
        event='e1',
        recipients=['test@example.com', 'user.name+tag@sub.domain.co.uk'],
    )
    assert len(valid_dto.recipients) == 2

    # Invalid recipient raises ValueError
    with pytest.raises(ValueError) as exc_info:
        AlertRuleIn(
            name='Invalid',
            project=str(uuid4()),
            route='r1',
            event='e1',
            recipients=['not-an-email'],
        )
    assert 'Invalid email recipient format' in str(exc_info.value)

    # Empty recipients raises ValueError / ValidationError
    with pytest.raises(ValueError) as exc_info:
        AlertRuleIn(
            name='Empty',
            project=str(uuid4()),
            route='r1',
            event='e1',
            recipients=[],
        )
    assert 'At least one email recipient is required' in str(
        exc_info.value
    ) or 'at least 1 item' in str(exc_info.value)


def test_from_alert_rule_handles_uppercase_db_values():
    now = datetime.now(timezone.utc)
    rule = AlertRule(
        uuid=uuid4(),
        name='Old Rule',
        description=None,
        project=str(uuid4()),
        route='r1',
        scope='ROUTE',
        credential_uuid=None,
        event='e1',
        time_aggregation='INSTANT',
        window_size=None,
        channel='EMAIL',
        recipients='["test@example.com"]',
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    out = AlertRuleOut.from_alert_rule(rule)
    assert out.scope == AlertRuleScope.ROUTE
    assert out.time_aggregation == AlertRuleTimeAggregation.INSTANT
    assert out.channel == AlertRuleChannel.EMAIL
