from radicalbit_ai_gateway.services.alert_email_formatter import (
    build_alert_email_body,
    build_alert_email_subject,
)


def test_build_subject():
    subject = build_alert_email_subject(
        rule_name='High Latency', route_name='chat-route'
    )
    assert subject == '[Alert Notification] High Latency triggered on chat-route'


def test_build_html_body_minimal():
    html = build_alert_email_body(
        rule_name='PII Detector',
        description=None,
        project_uuid='proj-123',
        route_name='openai-prod',
        event_name='guardrail-input-pii',
        event_details=None,
    )

    assert 'PII Detector' in html
    assert 'openai-prod' in html
    assert 'guardrail-input-pii' in html
    assert 'proj-123' in html
    assert 'N/A' in html


def test_build_html_body_full():
    details = {
        'request_uuid': 'req-999',
        'project_name': 'My Project',
        'api_key_name': 'test-key',
        'group_name': 'dev-team',
        'name': 'pii_filter',
        'type': 'anonymize',
        'where': 'input',
        'behavior': 'mask',
        'parameters': '{"entity_types": ["EMAIL"]}',
        'cache_type': 'exact',
        'target': 'primary_model',
        'fallback': 'backup_model',
    }

    html = build_alert_email_body(
        rule_name='PII and Fallback Alert',
        description='Triggers on PII in prompt',
        project_uuid='proj-123',
        route_name='chat-route',
        event_name='guardrail-input-pii',
        event_details=details,
    )

    assert 'PII and Fallback Alert' in html
    assert 'Triggers on PII in prompt' in html
    assert 'My Project' in html
    assert 'req-999' in html
    assert 'test-key' in html
    assert 'dev-team' in html
    assert 'Guardrail Name:' in html
    assert 'pii_filter' in html
    assert 'Guardrail Type:' in html
    assert 'anonymize' in html
    assert 'Cache Type:' in html
    assert 'exact' in html
    assert 'Fallback:' in html
    assert 'primary_model &rarr; backup_model' in html


def test_build_html_body_escapes_html_entities():
    details = {
        'request_uuid': '<script>alert(1)</script>',
        'name': '<b>malicious_guardrail</b>',
        'parameters': '<tag attr="val">',
    }
    html = build_alert_email_body(
        rule_name='<Rule & Test>',
        description='<img src=x onerror=alert(1)>',
        project_uuid='proj<123>',
        route_name='route<name>',
        event_name='event<name>',
        event_details=details,
    )

    assert '<script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    assert '&lt;Rule &amp; Test&gt;' in html
    assert '&lt;img src=x onerror=alert(1)&gt;' in html
    assert '&lt;b&gt;malicious_guardrail&lt;/b&gt;' in html
    assert '&lt;tag attr=&quot;val&quot;&gt;' in html
