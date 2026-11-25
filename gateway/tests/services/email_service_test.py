"""EmailService sends alert emails over SMTP with aiosmtplib.

SMTP is the boundary: `aiosmtplib.send` is replaced, and the tests check what
reaches it and what `send_email` reports back.
"""

from unittest.mock import AsyncMock, patch

import aiosmtplib
import pytest

from radicalbit_ai_gateway.services.email_service import EmailService


@pytest.fixture
def smtp_send():
    with patch.object(aiosmtplib, 'send', AsyncMock()) as send:
        yield send


def service(**credentials) -> EmailService:
    return EmailService(
        smtp_host='smtp.example.com',
        smtp_port=2525,
        from_email='gateway@example.com',
        **credentials,
    )


async def test_an_email_is_sent_to_every_recipient(smtp_send):
    sent = await service().send_email(
        recipients=['ops@example.com', 'dev@example.com'],
        subject='[Alert] PII watch',
        body='<p>PII found</p>',
    )

    assert sent is True
    [call] = smtp_send.await_args_list
    message = call.args[0]
    assert message['Subject'] == '[Alert] PII watch'
    assert message['From'] == 'gateway@example.com'
    assert message['To'] == 'ops@example.com, dev@example.com'
    assert call.kwargs['recipients'] == ['ops@example.com', 'dev@example.com']
    assert call.kwargs['hostname'] == 'smtp.example.com'
    assert call.kwargs['port'] == 2525


async def test_an_html_body_is_sent_as_html_and_text_as_plain(smtp_send):
    await service().send_email(['ops@example.com'], 's', '<p>html</p>')
    await service().send_email(['ops@example.com'], 's', 'plain text')

    html, plain = (c.args[0] for c in smtp_send.await_args_list)
    assert html.get_payload()[0].get_content_type() == 'text/html'
    assert plain.get_payload()[0].get_content_type() == 'text/plain'


async def test_without_credentials_there_is_no_starttls_and_no_login(smtp_send):
    await service().send_email(['ops@example.com'], 's', 'b')

    kwargs = smtp_send.await_args.kwargs
    assert kwargs['start_tls'] is False
    assert kwargs.get('username') is None
    assert kwargs.get('password') is None


async def test_with_credentials_it_upgrades_with_starttls_and_logs_in(smtp_send):
    await service(smtp_user='user', smtp_password='pwd').send_email(
        ['ops@example.com'], 's', 'b'
    )

    kwargs = smtp_send.await_args.kwargs
    assert kwargs['start_tls'] is True
    assert kwargs['username'] == 'user'
    assert kwargs['password'] == 'pwd'


async def test_no_recipients_sends_nothing(smtp_send):
    sent = await service().send_email([], 's', 'b')

    assert sent is False
    smtp_send.assert_not_awaited()


async def test_an_smtp_failure_is_reported_as_not_sent(smtp_send):
    smtp_send.side_effect = aiosmtplib.SMTPConnectError('refused')

    sent = await service().send_email(['ops@example.com'], 's', 'b')

    assert sent is False
