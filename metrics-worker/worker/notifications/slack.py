"""Slack notification channel."""

import datetime
import logging

import apprise

from worker.notifications.base import NotificationContext

logger = logging.getLogger(__name__)


class SlackNotifier:
    """Slack notification channel."""

    channel_name = 'slack'

    def __init__(self, config):
        self._config = config

    def is_enabled(self) -> bool:
        return self._config.slack.slack_enabled

    def can_notify(self, route_name: str) -> bool:
        return bool(self._config.slack.slack_webhook_mappings.get(route_name))

    def send(self, context: NotificationContext) -> bool:
        """Send Slack notification for a threshold alert."""
        webhook_url = self._config.slack.slack_webhook_mappings.get(context.route_name)
        if not webhook_url:
            return False

        icon = '🚨' if context.is_highest else '⚠️'
        user_tag = ''
        slack_user_id = self._config.slack.slack_user_mappings.get(context.route_name)
        if slack_user_id:
            user_tag = f' <@{slack_user_id}>'

        message = (
            f'{user_tag}\n'
            f'*Route:* {context.route_name}\n'
            f'*Direction:* {context.direction.upper()}\n'
            f'*Current Usage:* {context.current_usage:,} / {context.max_tokens:,} tokens ({context.usage_percentage}%)\n'
            f'*Window resets:* {datetime.datetime.fromtimestamp(int(context.reset_time)).strftime("%d-%m-%Y, %H:%M:%S")} UTC'
        )

        client = apprise.Apprise()
        if not client.add(webhook_url):
            logger.error('Failed to add Slack webhook for route %s', context.route_name)
            return False

        client.notify(
            title=f'{icon} Token Usage Alert',
            body=message,
            body_format=apprise.NotifyFormat.MARKDOWN,
        )
        return True
