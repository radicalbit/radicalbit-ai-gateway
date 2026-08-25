from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from radicalbit_ai_gateway.db.dao.alert_rule_dao import AlertRuleDAO
from radicalbit_ai_gateway.db.tables.alert_rule_table import AlertRule
from radicalbit_ai_gateway.models.caching import CacheConfig, SemanticCaching
from radicalbit_ai_gateway.models.fallback import Fallback
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.guardrails import (
    CheckParameter,
    Guardrail,
    GuardrailWhereType,
)
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.project_entry import ProjectEntry
from radicalbit_ai_gateway.services.alert_rule_service import AlertRuleService
from radicalbit_ai_gateway.services.email_service import EmailService


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
        disabled_reason=None,
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
        disabled_reason=None,
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


def test_get_alertable_events_empty_when_no_guardrails_or_features():
    mock_dao = MagicMock(spec=AlertRuleDAO)
    project_uuid = uuid4()

    model = Model(model_id='gpt-4', model='gpt-4', provider='openai')
    route_cfg = GatewayRouteConfig(
        route_name='plain-route',
        chat_models=['gpt-4'],
    )
    gw_cfg = GatewayConfig(
        routes={'plain-route': route_cfg},
        chat_models=[model],
    )
    project_entry = ProjectEntry(uuid=project_uuid, config=gw_cfg)

    service = AlertRuleService(
        alert_rule_dao=mock_dao,
        project_configs={'my-project': project_entry},
    )

    events = service.get_alertable_events_for_route('my-project', 'plain-route')
    assert events.guardrail == []
    assert events.caching == []
    assert events.fallback == []


def test_get_alertable_events_configured_route():
    mock_dao = MagicMock(spec=AlertRuleDAO)
    project_uuid = uuid4()

    model1 = Model(model_id='gpt-4', model='gpt-4', provider='openai')
    model2 = Model(model_id='gpt-3.5', model='gpt-3.5', provider='openai')
    emb_model = Model(model_id='text-emb', model='text-emb', provider='openai')

    guardrail_input = Guardrail(
        name='pii_check',
        where=GuardrailWhereType.INPUT,
        parameters=CheckParameter(values=['test']),
    )
    guardrail_io = Guardrail(
        name='toxicity_check',
        where=GuardrailWhereType.IO,
        parameters=CheckParameter(values=['toxic']),
    )

    route_cfg = GatewayRouteConfig(
        route_name='protected-route',
        chat_models=['gpt-4', 'gpt-3.5'],
        embedding_models=['text-emb'],
        guardrails=['pii_check', 'toxicity_check'],
        caching=SemanticCaching(
            type='semantic',
            distance_threshold=0.2,
            embedding_model_id='text-emb',
        ),
        fallback=[Fallback(target='gpt-4', fallbacks=['gpt-3.5'])],
    )
    gw_cfg = GatewayConfig(
        routes={'protected-route': route_cfg},
        chat_models=[model1, model2],
        embedding_models=[emb_model],
        guardrails=[guardrail_input, guardrail_io],
        cache=CacheConfig(redis_host='localhost', redis_port=6379),
    )
    project_entry = ProjectEntry(uuid=project_uuid, config=gw_cfg)

    service = AlertRuleService(
        alert_rule_dao=mock_dao,
        project_configs={'my-project': project_entry},
    )

    events = service.get_alertable_events_for_route('my-project', 'protected-route')

    # Guardrails: pii_check is only input; toxicity_check is io (input and output)
    guardrail_events = [item.event for item in events.guardrail]
    assert guardrail_events == [
        'guardrail-input-pii_check',
        'guardrail-input-toxicity_check',
        'guardrail-output-toxicity_check',
    ]

    # Caching: semantic
    caching_events = [item.event for item in events.caching]
    assert caching_events == ['cache-semantic']

    # Fallback: triggered
    fallback_events = [item.event for item in events.fallback]
    assert fallback_events == ['fallback-triggered']
