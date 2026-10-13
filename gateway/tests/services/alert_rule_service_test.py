from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from radicalbit_ai_gateway.db.dao.alert_rule_dao import AlertRuleDAO
from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule
from radicalbit_ai_gateway.models.alert_rule_dto import (
    AlertRuleChannel,
    AlertRuleIn,
    AlertRuleOut,
    AlertRuleScope,
    AlertRuleTimeAggregation,
    AlertRuleUpdateIn,
)
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.project_entry import ProjectEntry
from radicalbit_ai_gateway.services.alert_rule_service import AlertRuleService
from radicalbit_ai_gateway.services.email_service import EmailService
from radicalbit_ai_gateway.utils.exceptions import (
    AlertRuleInvalidEventError,
    AlertRuleUnsupportedTimeAggregationError,
)


@patch('radicalbit_ai_gateway.services.alert_rule_service.build_alert_email_body')
@patch('radicalbit_ai_gateway.services.alert_rule_service.build_alert_email_subject')
def test_dispatch_event_notification_mocked_formatter(
    mock_build_subject, mock_build_body
):
    mock_dao = MagicMock(spec=AlertRuleDAO)
    mock_email = MagicMock(spec=EmailService)

    now = datetime.now(timezone.utc)
    rule = AlertRule(
        uuid=uuid4(),
        name='Guardrail Rule',
        description='Desc',
        project='p1',
        route='route1',
        scope='route',
        event='guardrail-input-pii',
        time_aggregation='instant',
        channel='email',
        recipients='["test@example.com"]',
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    mock_dao.get_active_by_route.return_value = [rule]
    mock_email.send_email.return_value = True
    mock_build_subject.return_value = 'Custom Subject'
    mock_build_body.return_value = '<p>Custom Body</p>'

    service = AlertRuleService(
        alert_rule_dao=mock_dao,
        email_service=mock_email,
    )

    dispatched = service.dispatch_event_notification(
        project_uuid='p1',
        route_name='route1',
        event_name='guardrail-input-pii',
        event_details={'request_uuid': 'req-1'},
    )

    assert dispatched == 1
    mock_build_subject.assert_called_once_with('Guardrail Rule', 'route1')
    mock_build_body.assert_called_once_with(
        rule_name='Guardrail Rule',
        description='Desc',
        project_uuid='p1',
        route_name='route1',
        event_name='guardrail-input-pii',
        event_details={'request_uuid': 'req-1'},
    )
    mock_email.send_email.assert_called_once_with(
        recipients=['test@example.com'],
        subject='Custom Subject',
        body='<p>Custom Body</p>',
    )


def test_dispatch_event_notification_e2e_formatting():
    mock_dao = MagicMock(spec=AlertRuleDAO)
    mock_email = MagicMock(spec=EmailService)

    now = datetime.now(timezone.utc)
    rule = AlertRule(
        uuid=uuid4(),
        name='Default Formatter Rule',
        description='Desc',
        project='p1',
        route='route1',
        scope='route',
        event='fallback-triggered',
        time_aggregation='instant',
        channel='email',
        recipients='["admin@example.com"]',
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    mock_dao.get_active_by_route.return_value = [rule]
    mock_email.send_email.return_value = True

    service = AlertRuleService(
        alert_rule_dao=mock_dao,
        email_service=mock_email,
    )

    dispatched = service.dispatch_event_notification(
        project_uuid='p1',
        route_name='route1',
        event_name='fallback-triggered',
        event_details={'request_uuid': 'req-fallback'},
    )

    assert dispatched == 1
    mock_email.send_email.assert_called_once()
    call_args = mock_email.send_email.call_args[1]
    assert call_args['recipients'] == ['admin@example.com']
    assert (
        '[Alert Notification] Default Formatter Rule triggered on route1'
        in call_args['subject']
    )
    assert 'Default Formatter Rule' in call_args['body']
    assert 'req-fallback' in call_args['body']


def test_dispatch_event_notification_skips_window_time_aggregation():
    mock_dao = MagicMock(spec=AlertRuleDAO)
    mock_email = MagicMock(spec=EmailService)

    now = datetime.now(timezone.utc)
    rule = AlertRule(
        uuid=uuid4(),
        name='Window Rule',
        description='Desc',
        project='p1',
        route='route1',
        scope='route',
        event='fallback-triggered',
        time_aggregation='window',
        channel='email',
        recipients='["admin@example.com"]',
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    mock_dao.get_active_by_route.return_value = [rule]

    service = AlertRuleService(
        alert_rule_dao=mock_dao,
        email_service=mock_email,
    )

    dispatched = service.dispatch_event_notification(
        project_uuid='p1',
        route_name='route1',
        event_name='fallback-triggered',
        event_details={'request_uuid': 'req-fallback'},
    )

    # Should not dispatch anything because time_aggregation is window
    assert dispatched == 0
    mock_email.send_email.assert_not_called()


def test_create_rule_raises_on_invalid_event():
    mock_dao = MagicMock(spec=AlertRuleDAO)
    project_uuid = uuid4()
    model = Model(model_id='gpt-4', model='gpt-4', provider='openai')
    route_cfg = GatewayRouteConfig(
        route_name='active-route',
        chat_models=['gpt-4'],
    )
    gw_cfg = GatewayConfig(
        routes={'active-route': route_cfg},
        chat_models=[model],
    )
    project_entry = ProjectEntry(uuid=project_uuid, config=gw_cfg)

    service = AlertRuleService(
        alert_rule_dao=mock_dao,
        project_configs={'my-project': project_entry},
    )

    rule_in = AlertRuleIn(
        name='Invalid Event Rule',
        project='my-project',
        route='active-route',
        event='non-existent-event',
        recipients=['admin@example.com'],
    )

    with pytest.raises(AlertRuleInvalidEventError) as exc_info:
        service.create_rule(rule_in)
    assert 'not valid for route "active-route"' in str(exc_info.value)


def test_create_rule_raises_on_window_time_aggregation():
    mock_dao = MagicMock(spec=AlertRuleDAO)
    service = AlertRuleService(
        alert_rule_dao=mock_dao,
        project_configs={},
    )

    rule_in = AlertRuleIn(
        name='Window Rule',
        project='my-project',
        route='active-route',
        event='fallback-triggered',
        time_aggregation=AlertRuleTimeAggregation.WINDOW,
        recipients=['admin@example.com'],
    )

    with pytest.raises(AlertRuleUnsupportedTimeAggregationError) as exc_info:
        service.create_rule(rule_in)
    assert 'not supported' in str(exc_info.value)


def test_update_rule_raises_on_invalid_event_or_window():
    mock_dao = MagicMock(spec=AlertRuleDAO)
    project_uuid = uuid4()
    model = Model(model_id='gpt-4', model='gpt-4', provider='openai')
    route_cfg = GatewayRouteConfig(
        route_name='active-route',
        chat_models=['gpt-4'],
    )
    gw_cfg = GatewayConfig(
        routes={'active-route': route_cfg},
        chat_models=[model],
    )
    project_entry = ProjectEntry(uuid=project_uuid, config=gw_cfg)

    now = datetime.now(timezone.utc)
    rule_id = uuid4()
    existing = AlertRule(
        uuid=rule_id,
        name='Existing Rule',
        description=None,
        project='my-project',
        route='active-route',
        scope='route',
        event='fallback-triggered',
        time_aggregation='instant',
        channel='email',
        recipients='["admin@example.com"]',
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    mock_dao.get_by_uuid.return_value = existing

    service = AlertRuleService(
        alert_rule_dao=mock_dao,
        project_configs={'my-project': project_entry},
    )

    # 1. Update with invalid event
    with pytest.raises(AlertRuleInvalidEventError):
        service.update_rule(rule_id, AlertRuleUpdateIn(event='invalid-event'))

    # 2. Update with window time aggregation
    with pytest.raises(AlertRuleUnsupportedTimeAggregationError):
        service.update_rule(
            rule_id,
            AlertRuleUpdateIn(time_aggregation=AlertRuleTimeAggregation.WINDOW),
        )


def test_alert_rule_dto_recipient_validation():
    # Valid recipients
    valid_dto = AlertRuleIn(
        name='Valid',
        project='p1',
        route='r1',
        event='e1',
        recipients=['test@example.com', 'user.name+tag@sub.domain.co.uk'],
    )
    assert len(valid_dto.recipients) == 2

    # Invalid recipient raises ValueError
    with pytest.raises(ValueError) as exc_info:
        AlertRuleIn(
            name='Invalid',
            project='p1',
            route='r1',
            event='e1',
            recipients=['not-an-email'],
        )
    assert 'Invalid email recipient format' in str(exc_info.value)

    # Empty recipients raises ValueError / ValidationError
    with pytest.raises(ValueError) as exc_info:
        AlertRuleIn(
            name='Empty',
            project='p1',
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
        project='p1',
        route='r1',
        scope='ROUTE',
        event='e1',
        time_aggregation='INSTANT',
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
