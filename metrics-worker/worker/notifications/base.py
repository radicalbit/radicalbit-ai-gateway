"""Base types for the notification system."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class NotificationContext:
    """Immutable container for notification data."""

    route_name: str
    direction: str
    max_tokens: int
    current_usage: int
    usage_percentage: int
    reset_time: int
    threshold: int
    is_highest: bool


class Notifier(Protocol):
    """Protocol defining the interface for notification channels."""

    channel_name: str

    def is_enabled(self) -> bool: ...
    def can_notify(self, route_name: str) -> bool: ...
    def send(self, context: NotificationContext) -> bool: ...
