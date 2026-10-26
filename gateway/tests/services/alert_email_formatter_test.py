from datetime import UTC, datetime

from radicalbit_ai_gateway.services.alert_email_formatter import (
    build_alert_email_body,
    build_alert_email_subject,
)

TIME = datetime(2026, 10, 13, 9, 30, 5, tzinfo=UTC)


def body(**overrides) -> str:
    args = {
        'rule_name': 'PII watch',
        'description': None,
        'scope': 'route',
        'target': 'acme / chat',
        'event': 'guardrail-input-pii',
        'time': TIME,
        'details': [],
    }
    return build_alert_email_body(**{**args, **overrides})


def test_the_subject_names_rule_event_and_target():
    subject = build_alert_email_subject(
        rule_name='PII watch', event='guardrail-input-pii', target='acme / chat'
    )

    assert subject == '[Alert] PII watch: guardrail-input-pii on acme / chat'


def test_the_body_always_names_rule_scope_target_event_and_time():
    html = body()

    for expected in (
        'PII watch',
        'route',
        'acme / chat',
        'guardrail-input-pii',
        '2026-10-13 09:30:05 UTC',
    ):
        assert expected in html


def test_the_body_carries_the_description_when_there_is_one():
    assert 'Watches PII' in body(description='Watches PII')
    assert 'Description' not in body(description=None)


def test_the_body_lists_the_details_in_order():
    html = body(details=[('Credential', 'billing-service'), ('Group', 'finance')])

    assert html.index('billing-service') < html.index('finance')
    assert 'Credential' in html


def test_the_body_has_no_details_section_without_details():
    assert 'Details' not in body(details=[])


def test_every_value_is_html_escaped():
    html = body(
        rule_name='<script>alert(1)</script>',
        description='a & b',
        target='<b>acme</b> / chat',
        event='guardrail-input-<x>',
        details=[('Credential', '<img src=x>')],
    )

    assert '<script>' not in html
    assert '&lt;script&gt;' in html
    assert 'a &amp; b' in html
    assert '&lt;b&gt;acme&lt;/b&gt;' in html
    assert 'guardrail-input-&lt;x&gt;' in html
    assert '<img' not in html
