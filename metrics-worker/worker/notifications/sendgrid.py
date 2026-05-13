"""SendGrid email notification channel."""

import datetime
import logging
from urllib.parse import quote

import apprise

from worker.notifications.base import NotificationContext

logger = logging.getLogger(__name__)


def _build_sendgrid_url(
    api_key: str,
    from_email: str,
    emails: list[str],
    template_id: str | None,
    template_vars: dict[str, str] | None = None,
) -> str:
    """Build SendGrid Apprise URL from email list.

    Template variables are passed with + prefix per Apprise's SendGrid integration.
    """
    if not emails:
        return ''
    to_email = emails[0]
    url = f'sendgrid://{api_key}:{from_email}/{to_email}'
    params = []
    if len(emails) > 1:
        # Use comma-separated CC addresses
        params.append(f'cc={",".join(emails[1:])}')
    if template_id:
        params.append(f'template={template_id}')
        # Add template variables with + prefix
        if template_vars:
            for key, value in template_vars.items():
                params.append(f'+{key}={quote(value, safe="")}')
    if params:
        url += f'?{"&".join(params)}'
    return url


class SendGridNotifier:
    """SendGrid email notification channel."""

    channel_name = 'sendgrid'

    def __init__(self, config):
        self._config = config

    def is_enabled(self) -> bool:
        return self._config.sendgrid.sendgrid_enabled

    def can_notify(self, route_name: str) -> bool:
        if (
            not self._config.sendgrid.sendgrid_api_key
            or not self._config.sendgrid.sendgrid_from_email
        ):
            return False
        return bool(self._config.sendgrid.sendgrid_email_mappings.get(route_name))

    def send(self, context: NotificationContext) -> bool:
        """Send SendGrid email notification for a threshold alert."""
        if (
            not self._config.sendgrid.sendgrid_api_key
            or not self._config.sendgrid.sendgrid_from_email
        ):
            return False

        emails = self._config.sendgrid.sendgrid_email_mappings.get(
            context.route_name, []
        )
        if not emails:
            return False

        window_resets = datetime.datetime.fromtimestamp(
            int(context.reset_time), tz=datetime.UTC
        ).strftime('%d-%m-%Y, %H:%M:%S UTC')

        template_id = self._config.sendgrid.sendgrid_template_id
        template_vars = None

        if template_id:
            # Template variables passed via URL with + prefix
            template_vars = {
                'first_name': emails[0],
                'msg': f'{context.usage_percentage}% ({context.current_usage:,} / {context.max_tokens:,})',
                'route_name': context.route_name,
                'direction': context.direction.upper(),
                'window_resets': window_resets,
            }

        url = _build_sendgrid_url(
            self._config.sendgrid.sendgrid_api_key,
            self._config.sendgrid.sendgrid_from_email,
            emails,
            template_id,
            template_vars,
        )

        client = apprise.Apprise()
        if not client.add(url):
            logger.error('Failed to add SendGrid URL for route %s', context.route_name)
            return False

        if template_id:
            # Body is ignored when using templates, pass placeholder to avoid warning
            client.notify(
                title='Token Usage Alert',
                body='Template notification',
                body_format=apprise.NotifyFormat.TEXT,
            )
        else:
            # Use HTML message when no template
            icon = '🚨' if context.is_highest else '⚠️'
            message = (
                f'<strong>Route:</strong> {context.route_name}<br>'
                f'<strong>Direction:</strong> {context.direction.upper()}<br>'
                f'<strong>Current Usage:</strong> {context.current_usage:,} / {context.max_tokens:,} tokens ({context.usage_percentage}%)<br>'
                f'<strong>Window resets:</strong> {window_resets}'
            )
            client.notify(
                title=f'{icon} Token Usage Alert',
                body=message,
                body_format=apprise.NotifyFormat.HTML,
            )
        return True
