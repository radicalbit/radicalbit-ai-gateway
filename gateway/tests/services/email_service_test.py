"""Sending an email logs in to the SMTP server only with credentials."""

import smtplib
from unittest.mock import MagicMock, patch

import pytest

from radicalbit_ai_gateway.services.email_service import EmailService

SMTP = 'radicalbit_ai_gateway.services.email_service.smtplib.SMTP'


def _send(service: EmailService) -> tuple[bool, MagicMock, MagicMock]:
    server = MagicMock(spec_set=smtplib.SMTP)
    smtp = MagicMock(spec_set=smtplib.SMTP)
    smtp.return_value.__enter__.return_value = server
    with patch(SMTP, smtp):
        sent = service.send_email(['ops@example.com'], 'Alert', 'Budget exceeded')
    return sent, smtp, server


def test_sending_with_credentials_logs_in_over_tls():
    service = EmailService(
        smtp_host='smtp.example.com',
        smtp_port=587,
        smtp_user='alerts',
        smtp_password='s3cret',
        from_email='gateway@example.com',
    )

    sent, smtp, server = _send(service)

    assert sent is True
    smtp.assert_called_once_with('smtp.example.com', 587, timeout=10)
    server.starttls.assert_called_once_with()
    server.login.assert_called_once_with('alerts', 's3cret')
    server.sendmail.assert_called_once()
    assert server.sendmail.call_args.args[:2] == (
        'gateway@example.com',
        ['ops@example.com'],
    )


@pytest.mark.parametrize(
    ('user', 'password'),
    [
        pytest.param(None, None, id='no-credentials'),
        pytest.param('alerts', None, id='no-password'),
    ],
)
def test_sending_without_credentials_does_not_log_in(user, password):
    service = EmailService(smtp_user=user, smtp_password=password)
    # Not taken from the environment's SMTP settings.
    service.smtp_user = user
    service.smtp_password = password

    sent, _, server = _send(service)

    assert sent is True
    server.starttls.assert_not_called()
    server.login.assert_not_called()
    server.sendmail.assert_called_once()
