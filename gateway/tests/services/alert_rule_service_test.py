from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from radicalbit_ai_gateway.db.dao.alert_rule_dao import AlertRuleDAO
from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule
from radicalbit_ai_gateway.services.alert_email_formatter import AlertEmailFormatter
from radicalbit_ai_gateway.services.alert_rule_service import AlertRuleService
from radicalbit_ai_gateway.services.email_service import EmailService


def test_dispatch_event_notification_custom_formatter():
    mock_dao = MagicMock(spec=AlertRuleDAO)
    mock_email = MagicMock(spec=EmailService)
    mock_formatter = MagicMock(spec=AlertEmailFormatter)

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
        disabled_reason=None,
        created_at=now,
        updated_at=now,
    )
    mock_dao.get_active_by_route.return_value = [rule]
    mock_email.send_email.return_value = True
    mock_formatter.build_subject.return_value = 'Custom Subject'
    mock_formatter.build_html_body.return_value = '<p>Custom Body</p>'

    service = AlertRuleService(
        alert_rule_dao=mock_dao,
        email_service=mock_email,
        email_formatter=mock_formatter,
    )

    dispatched = service.dispatch_event_notification(
        project_uuid='p1',
        route_name='route1',
        event_name='guardrail-input-pii',
        event_details={'request_uuid': 'req-1'},
    )

    assert dispatched == 1
    mock_formatter.build_subject.assert_called_once_with('Guardrail Rule', 'route1')
    mock_formatter.build_html_body.assert_called_once_with(
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


def test_dispatch_event_notification_default_formatter():
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
        disabled_reason=None,
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
