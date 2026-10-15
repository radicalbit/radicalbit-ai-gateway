"""Worker startup: the Celery app and the shutdown hook."""

from worker import app as app_module, task as task_module
from worker.app import _create_celery_app


def test_the_celery_app_takes_the_configured_broker():
    app = _create_celery_app('test_app')

    assert app.main == 'test_app'
    assert app.conf.broker_url == app_module.config.celery.celery_broker_url


def test_the_celery_app_acknowledges_tasks_late():
    """A task that dies mid-flight must be redelivered, not lost."""
    app = _create_celery_app('test_app')

    assert app.conf.task_acks_late is True
    assert (
        app.conf.worker_prefetch_multiplier
        == app_module.config.metrics.metrics_worker_prefetch
    )


def test_process_shutdown_cleans_up_every_worker(monkeypatch):
    """Without this the last buffered batch never reaches ClickHouse."""
    called = []
    monkeypatch.setattr(task_module._worker, 'cleanup', lambda: called.append('events'))
    monkeypatch.setattr(
        task_module._request_event_worker,
        'cleanup',
        lambda: called.append('request_events'),
    )
    monkeypatch.setattr(
        task_module._alert_worker, 'cleanup', lambda: called.append('alerts')
    )

    task_module._cleanup_resources()

    assert called == ['events', 'request_events', 'alerts']
