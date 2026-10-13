"""Every alert send attempt leaves one record on the ``emit_alert`` buffer."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import uuid

from radicalbit_ai_gateway.db.dao.alert_rule_dao import AlertRuleDAO
from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule
from radicalbit_ai_gateway.services.alert_rule_service import AlertRuleService
from radicalbit_ai_gateway.services.email_service import EmailService

BUFFER = 'radicalbit_ai_gateway.events.alerts_processor._alerts_buffer'
PROJECT_UUID = '11111111-1111-1111-1111-111111111111'


def _rule() -> AlertRule:
    now = datetime.now(timezone.utc)
    return AlertRule(
        uuid=uuid.uuid4(),
        name='Fallback Rule',
        description='Desc',
        project=PROJECT_UUID,
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


def _dispatch(rule: AlertRule, sent: bool) -> MagicMock:
    dao = MagicMock(spec=AlertRuleDAO)
    dao.get_active_by_route.return_value = [rule]
    email = MagicMock(spec=EmailService)
    email.send_email.return_value = sent
    service = AlertRuleService(alert_rule_dao=dao, email_service=email)

    with patch(BUFFER) as buffer:
        service.dispatch_event_notification(
            project_uuid=PROJECT_UUID,
            route_name='route1',
            event_name='fallback-triggered',
        )
    return buffer


def test_an_instant_alert_hands_one_record_to_the_buffer():
    rule = _rule()

    buffer = _dispatch(rule, sent=True)

    buffer.add.assert_called_once()
    record = buffer.add.call_args.args[0]
    uuid.UUID(record['ALERT_UUID'])
    assert isinstance(record['TIMESTAMP'], datetime)
    assert record['RULE_UUID'] == str(rule.uuid)
    assert record['RULE_NAME'] == 'Fallback Rule'
    assert record['SCOPE'] == 'route'
    assert record['PROJECT_UUID'] == PROJECT_UUID
    assert record['ROUTE_NAME'] == 'route1'
    assert record['CREDENTIAL_UUID'] is None
    assert record['EVENT'] == 'fallback-triggered'
    assert record['AGGREGATION'] == 'instant'
    assert record['COUNT'] == 1
    assert record['WINDOW_START'] is None
    assert record['WINDOW_END'] is None
    assert record['STATUS'] == 'sent'


def test_an_smtp_failure_is_recorded_as_failed():
    buffer = _dispatch(_rule(), sent=False)

    assert buffer.add.call_args.args[0]['STATUS'] == 'failed'


def test_each_alert_gets_its_own_uuid():
    first = _dispatch(_rule(), sent=True).add.call_args.args[0]
    second = _dispatch(_rule(), sent=True).add.call_args.args[0]

    assert first['ALERT_UUID'] != second['ALERT_UUID']


def test_a_send_that_raises_is_recorded_as_failed_and_the_next_rule_still_runs():
    dao = MagicMock(spec=AlertRuleDAO)
    dao.get_active_by_route.return_value = [_rule(), _rule()]
    email = MagicMock(spec=EmailService)
    email.send_email.side_effect = [RuntimeError('smtp down'), True]
    service = AlertRuleService(alert_rule_dao=dao, email_service=email)

    with patch(BUFFER) as buffer:
        dispatched = service.dispatch_event_notification(
            project_uuid=PROJECT_UUID,
            route_name='route1',
            event_name='fallback-triggered',
        )

    statuses = [call.args[0]['STATUS'] for call in buffer.add.call_args_list]
    assert statuses == ['failed', 'sent']
    assert dispatched == 1
