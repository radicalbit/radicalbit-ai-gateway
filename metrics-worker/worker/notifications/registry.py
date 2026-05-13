"""Notifier registry for managing notification channels."""

from worker.notifications.base import Notifier
from worker.notifications.sendgrid import SendGridNotifier
from worker.notifications.slack import SlackNotifier


class NotifierRegistry:
    """Registry for notification channels with lazy initialization."""

    def __init__(self, config):
        self._config = config
        self._notifiers: list[Notifier] | None = None

    def get_notifiers(self) -> list[Notifier]:
        """Get all registered notifiers, initializing on first access."""
        if self._notifiers is None:
            self._notifiers = [
                SlackNotifier(self._config),
                SendGridNotifier(self._config),
            ]
        return self._notifiers

    def add_notifier(self, notifier: Notifier) -> None:
        """Add a notifier to the registry."""
        if self._notifiers is None:
            self._notifiers = []
        self._notifiers.append(notifier)

    def any_enabled(self) -> bool:
        """Check if any notifier is enabled."""
        return any(n.is_enabled() for n in self.get_notifiers())
