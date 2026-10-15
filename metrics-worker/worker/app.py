"""Celery app instance for metrics worker."""

import logging

from celery import Celery

from worker.config import config

# Configure root logger at module import time
logging.basicConfig(
    level=getattr(logging, config.log.log_level.upper(), logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)


def _create_celery_app(name: str) -> Celery:
    """Create a Celery app with standard configuration."""
    app = Celery(name, broker=config.celery.celery_broker_url)
    app.conf.update(
        worker_prefetch_multiplier=config.metrics.metrics_worker_prefetch,
        task_acks_late=True,
    )
    return app


celery_app = _create_celery_app('worker_app')
