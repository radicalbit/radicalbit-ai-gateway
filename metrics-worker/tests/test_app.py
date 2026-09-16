"""Worker startup: the Redis client, the notification banner, the shutdown hook."""

import pytest

from worker import app as app_module, task as task_module
from worker.app import (
    _create_celery_app,
    init_clients,
    init_metrics_clients,
    init_notification_clients,
)


class _FakeApp:
    pass


@pytest.fixture
def redis_calls(monkeypatch):
    """Record the Redis client that startup would have built."""
    built = []

    def redis_ctor(**kwargs):
        built.append(kwargs)
        return f'client-{len(built)}'

    monkeypatch.setattr(app_module.redis, 'Redis', redis_ctor)
    return built


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


def test_startup_builds_a_redis_client_from_config(redis_calls):
    app = _FakeApp()

    init_metrics_clients(app)

    assert app.redis_client == 'client-1'
    assert redis_calls[0]['host'] == app_module.config.redis.redis_host
    assert redis_calls[0]['port'] == app_module.config.redis.redis_port
    assert redis_calls[0]['db'] == app_module.config.redis.redis_db


def test_the_redis_client_does_not_block_the_worker(redis_calls):
    """No timeout here would hang every notification behind a dead Redis."""
    init_metrics_clients(_FakeApp())

    assert redis_calls[0]['socket_connect_timeout'] == 2
    assert redis_calls[0]['socket_timeout'] == 2


def test_a_blank_password_is_sent_as_none(redis_calls, monkeypatch):
    monkeypatch.setattr(app_module.config.redis, 'redis_password', '')
    init_metrics_clients(_FakeApp())

    assert redis_calls[0]['password'] is None


def test_a_configured_password_is_passed_through(redis_calls, monkeypatch):
    monkeypatch.setattr(app_module.config.redis, 'redis_password', 'hunter2')
    init_metrics_clients(_FakeApp())

    assert redis_calls[0]['password'] == 'hunter2'


def test_a_redis_that_cannot_be_built_leaves_the_worker_running(monkeypatch):
    """Metrics inserts do not need Redis. Only the alert dedupe does."""

    def explode(**kwargs):
        raise OSError('no route to host')

    monkeypatch.setattr(app_module.redis, 'Redis', explode)
    app = _FakeApp()

    init_metrics_clients(app)

    assert app.redis_client is None


@pytest.mark.parametrize(
    ('slack_enabled', 'mappings'),
    [(True, {'r': 'url'}), (True, {}), (False, {})],
)
def test_the_notification_banner_handles_every_slack_state(
    monkeypatch, slack_enabled, mappings
):
    monkeypatch.setattr(app_module.config.slack, 'slack_enabled', slack_enabled)
    monkeypatch.setattr(app_module.config.slack, 'slack_webhook_mappings', mappings)
    app = _FakeApp()

    init_notification_clients(app)

    assert app.apprise_client is None


@pytest.mark.parametrize(
    ('enabled', 'api_key', 'from_email', 'mappings'),
    [
        (True, 'key', 'a@x.com', {'r': ['b@x.com']}),
        (True, None, 'a@x.com', {'r': ['b@x.com']}),
        (True, 'key', None, {'r': ['b@x.com']}),
        (True, 'key', 'a@x.com', {}),
        (False, None, None, {}),
    ],
)
def test_the_notification_banner_handles_every_sendgrid_state(
    monkeypatch, enabled, api_key, from_email, mappings
):
    monkeypatch.setattr(app_module.config.sendgrid, 'sendgrid_enabled', enabled)
    monkeypatch.setattr(app_module.config.sendgrid, 'sendgrid_api_key', api_key)
    monkeypatch.setattr(app_module.config.sendgrid, 'sendgrid_from_email', from_email)
    monkeypatch.setattr(app_module.config.sendgrid, 'sendgrid_email_mappings', mappings)
    app = _FakeApp()

    init_notification_clients(app)

    assert app.apprise_client is None


def test_worker_startup_wires_both_sets_of_clients(redis_calls):
    init_clients(sender=None)

    assert app_module.celery_app.redis_client == 'client-1'
    assert app_module.celery_app.apprise_client is None


def test_process_shutdown_cleans_up_both_workers(monkeypatch):
    """Without this the last buffered batch never reaches ClickHouse."""
    called = []
    monkeypatch.setattr(task_module._worker, 'cleanup', lambda: called.append('events'))
    monkeypatch.setattr(
        task_module._request_event_worker,
        'cleanup',
        lambda: called.append('request_events'),
    )

    task_module._cleanup_resources()

    assert called == ['events', 'request_events']
