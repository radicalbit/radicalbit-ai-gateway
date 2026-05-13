"""Notifier - threshold checking and task execution."""

from collections.abc import Iterable, Sequence
import logging
import time

from worker.app import celery_app
from worker.config import config
from worker.notifications.base import NotificationContext
from worker.notifications.registry import NotifierRegistry

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, config.log.log_level.upper(), logging.INFO))

# Single registry instance
registry = NotifierRegistry(config)


def calculate_usage_percentage(current_usage: int, max_tokens: int) -> int:
    """Calculate usage as percentage of max_tokens."""
    if max_tokens <= 0:
        return 0
    return int((current_usage / max_tokens) * 100)


def _is_channel_notified(redis_client, threshold_key: str, channel: str) -> bool:
    """Check if a channel has already been notified using Redis hash."""
    try:
        return redis_client.hexists(threshold_key, channel)
    except Exception as exc:
        logger.warning('Redis error checking channel notification state: %s', exc)
        return False


def _mark_channel_notified(
    redis_client, threshold_key: str, channel: str, reset_time: int
) -> bool:
    """Mark a channel as notified. Returns True if newly set."""
    try:
        was_set = redis_client.hsetnx(threshold_key, channel, '1')
        if was_set:
            ttl = (
                max(1, int(reset_time - time.time())) + 60
            )  # add buffer to notification ttl
            redis_client.expire(threshold_key, ttl)
        return bool(was_set)
    except Exception as exc:
        logger.warning('Redis error marking channel notification: %s', exc)
        return False


def _check_and_send_threshold_notification(notification_data: dict) -> bool:
    """Check if threshold is crossed and send notification if not already sent."""
    route_name = notification_data.get('ROUTE_NAME', 'unknown')
    direction = notification_data.get('DIRECTION', 'unknown')
    max_tokens = notification_data.get('MAX_TOKENS', 0)
    current_usage = notification_data.get('CURRENT_USAGE', 0)
    reset_time = notification_data.get('RESET_TIME', 0)
    window_id = notification_data.get('WINDOW_ID', 'unknown')

    usage_percentage = calculate_usage_percentage(current_usage, max_tokens)

    thresholds_to_check = config.notification.notification_thresholds
    redis_client = celery_app.redis_client
    notification_sent = False

    for threshold in thresholds_to_check:
        if usage_percentage < threshold:
            continue

        threshold_key = (
            f'notification:threshold:{route_name}:{direction}:{window_id}:{threshold}'
        )
        is_highest = threshold == thresholds_to_check[-1]

        context = NotificationContext(
            route_name=route_name,
            direction=direction,
            max_tokens=max_tokens,
            current_usage=current_usage,
            usage_percentage=usage_percentage,
            reset_time=reset_time,
            threshold=threshold,
            is_highest=is_highest,
        )

        for notifier in registry.get_notifiers():
            if not notifier.is_enabled():
                continue
            if not notifier.can_notify(route_name):
                continue

            if redis_client is not None:
                if _is_channel_notified(
                    redis_client, threshold_key, notifier.channel_name
                ):
                    logger.debug(
                        '%s already notified for route %s (%s) at %d%%, window_id %s',
                        notifier.channel_name.capitalize(),
                        route_name,
                        direction,
                        threshold,
                        window_id,
                    )
                    continue
                if not _mark_channel_notified(
                    redis_client, threshold_key, notifier.channel_name, reset_time
                ):
                    continue

            try:
                if notifier.send(context):
                    logger.info(
                        'Sent %s notification for route %s at %d%%',
                        notifier.channel_name,
                        route_name,
                        threshold,
                    )
                    notification_sent = True
            except Exception as exc:
                logger.error(
                    'Failed to send %s notification: %s', notifier.channel_name, exc
                )

    return notification_sent


def _iter_notification_payload(payload: Sequence[dict]) -> Iterable[dict]:
    """Iterate over notification payload, handling both single dict and list/tuple of dicts."""
    if isinstance(payload, dict):
        yield payload
        return
    if isinstance(payload, (list, tuple)):
        for item in payload:
            if isinstance(item, dict):
                yield item
            else:
                logger.warning(
                    'Skipping non-dict notification payload entry: %s', type(item)
                )
        return
    logger.warning('Unsupported notification payload type received: %s', type(payload))


@celery_app.task(
    name='emit_notification',
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
)
def log_notification(notification_payload):
    """Process notification and send alerts if threshold crossed."""
    if not registry.any_enabled():
        notification_count = len(list(_iter_notification_payload(notification_payload)))
        logger.info(
            'No notification channels enabled, skipping %d notification(s)',
            notification_count,
        )
        return {'status': 'skipped', 'notifications_sent': 0}

    notifications_sent = 0

    for notification_data in _iter_notification_payload(notification_payload):
        logger.info('Notification received: %s', notification_data)

        if _check_and_send_threshold_notification(notification_data):
            notifications_sent += 1

    return {'status': 'processed', 'notifications_sent': notifications_sent}
