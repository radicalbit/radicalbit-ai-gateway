"""Celery app instance for metrics worker."""

import logging

from celery import Celery, signals
import redis

from worker.config import config

# Configure root logger at module import time
logging.basicConfig(
    level=getattr(logging, config.log.log_level.upper(), logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)

logger = logging.getLogger(__name__)


def _create_celery_app(name: str) -> Celery:
    """Create a Celery app with standard configuration."""
    app = Celery(name, broker=config.celery.celery_broker_url)
    app.conf.update(
        worker_prefetch_multiplier=config.metrics.metrics_worker_prefetch,
        task_acks_late=True,
    )
    return app


celery_app = _create_celery_app('worker_app')


def init_metrics_clients(app: Celery) -> None:
    """Initialize Redis client for metrics worker."""
    try:
        app.redis_client = redis.Redis(
            host=config.redis.redis_host,
            port=config.redis.redis_port,
            db=config.redis.redis_db,
            password=config.redis.redis_password
            if config.redis.redis_password
            else None,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        logger.info('Redis client initialized')
    except Exception as exc:
        logger.warning('Failed to create Redis client: %s', exc)
        app.redis_client = None


def init_notification_clients(app: Celery) -> None:
    """Log notification configuration status."""
    # Slack status
    if config.slack.slack_enabled:
        if config.slack.slack_webhook_mappings:
            logger.info(
                'Slack notifications ENABLED for %d routes',
                len(config.slack.slack_webhook_mappings),
            )
        else:
            logger.warning(
                'Slack notifications enabled but no webhook mappings configured'
            )
    else:
        logger.info('Slack notifications DISABLED')

    # SendGrid status
    if config.sendgrid.sendgrid_enabled:
        if (
            config.sendgrid.sendgrid_api_key
            and config.sendgrid.sendgrid_from_email
            and config.sendgrid.sendgrid_email_mappings
        ):
            logger.info(
                'SendGrid notifications ENABLED for %d routes',
                len(config.sendgrid.sendgrid_email_mappings),
            )
        else:
            logger.warning(
                'SendGrid notifications enabled but configuration incomplete'
            )
    else:
        logger.info('SendGrid notifications DISABLED')

    app.apprise_client = None  # Created lazily per route


@signals.worker_init.connect
def init_clients(sender, **kwargs):
    """Initialize clients at worker startup based on configuration."""
    init_metrics_clients(celery_app)
    init_notification_clients(
        celery_app
    )  # Always call (checks individual flags internally)
