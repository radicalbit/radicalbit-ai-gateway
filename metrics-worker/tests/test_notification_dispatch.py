"""When a threshold alert actually goes out, and when it is held back.

The dedupe lives in Redis. Getting it wrong means either an alert storm or a
silent quota breach, so both directions are pinned here.
"""

import pytest

from worker.app import celery_app
from worker.notifications import notifier as notifier_module
from worker.notifications.notifier import (
    _check_and_send_threshold_notification,
    _iter_notification_payload,
    log_notification,
)


class _Recorder:
    """A notifier that records the contexts it was asked to send."""

    def __init__(self, channel_name='recorder', enabled=True, routes=('my-route',)):
        self.channel_name = channel_name
        self._enabled = enabled
        self._routes = routes
        self.sent = []
        self.result = True
        self.error = None

    def is_enabled(self):
        return self._enabled

    def can_notify(self, route_name):
        return route_name in self._routes

    def send(self, context):
        if self.error:
            raise self.error
        self.sent.append(context)
        return self.result


class _FakeRegistry:
    def __init__(self, notifiers):
        self._notifiers = notifiers

    def get_notifiers(self):
        return self._notifiers

    def any_enabled(self):
        return any(n.is_enabled() for n in self._notifiers)


class _FakeRedis:
    """Enough of a Redis hash to exercise the dedupe."""

    def __init__(self):
        self.hashes: dict[str, dict] = {}
        self.expires: dict[str, int] = {}

    def hexists(self, key, field):
        return field in self.hashes.get(key, {})

    def hsetnx(self, key, field, value):
        fields = self.hashes.setdefault(key, {})
        if field in fields:
            return 0
        fields[field] = value
        return 1

    def expire(self, key, ttl):
        self.expires[key] = ttl


class _BrokenRedis:
    def hexists(self, key, field):
        raise ConnectionError('redis is down')

    def hsetnx(self, key, field, value):
        raise ConnectionError('redis is down')

    def expire(self, key, ttl):
        raise ConnectionError('redis is down')


@pytest.fixture
def recorder():
    return _Recorder()


@pytest.fixture
def redis_client(monkeypatch):
    client = _FakeRedis()
    monkeypatch.setattr(celery_app, 'redis_client', client, raising=False)
    return client


@pytest.fixture
def use(monkeypatch):
    """Install a registry of the given notifiers for the module under test."""

    def install(*notifiers, thresholds=(75, 98)):
        monkeypatch.setattr(notifier_module, 'registry', _FakeRegistry(list(notifiers)))
        monkeypatch.setattr(
            notifier_module.config.notification,
            'notification_thresholds',
            list(thresholds),
        )

    return install


def _payload(**overrides) -> dict:
    data = {
        'ROUTE_NAME': 'my-route',
        'DIRECTION': 'input',
        'MAX_TOKENS': 1000,
        'CURRENT_USAGE': 800,
        'RESET_TIME': 4000000000,
        'WINDOW_ID': 'w1',
    }
    data.update(overrides)
    return data


# --- payload shapes ---------------------------------------------------------


def test_a_single_dict_payload_yields_itself():
    assert list(_iter_notification_payload({'a': 1})) == [{'a': 1}]


def test_a_list_payload_yields_each_entry():
    assert list(_iter_notification_payload([{'a': 1}, {'b': 2}])) == [
        {'a': 1},
        {'b': 2},
    ]


def test_non_dict_notification_entries_are_dropped():
    assert list(_iter_notification_payload([{'a': 1}, 42])) == [{'a': 1}]


def test_an_unsupported_notification_payload_yields_nothing():
    assert list(_iter_notification_payload(None)) == []


# --- threshold crossing -----------------------------------------------------


def test_usage_below_every_threshold_sends_nothing(use, recorder, redis_client):
    use(recorder)

    assert _check_and_send_threshold_notification(_payload(CURRENT_USAGE=500)) is False
    assert recorder.sent == []


def test_crossing_the_first_threshold_sends_once(use, recorder, redis_client):
    use(recorder)

    assert _check_and_send_threshold_notification(_payload()) is True
    assert [c.threshold for c in recorder.sent] == [75]


def test_crossing_every_threshold_sends_for_each(use, recorder, redis_client):
    """98% is past 75 too. Both alerts go out, not just the highest."""
    use(recorder)

    _check_and_send_threshold_notification(_payload(CURRENT_USAGE=990))

    assert [c.threshold for c in recorder.sent] == [75, 98]


def test_only_the_last_threshold_is_marked_highest(use, recorder, redis_client):
    use(recorder)

    _check_and_send_threshold_notification(_payload(CURRENT_USAGE=990))

    assert [c.is_highest for c in recorder.sent] == [False, True]


def test_the_context_carries_the_route_and_the_usage(use, recorder, redis_client):
    use(recorder)

    _check_and_send_threshold_notification(_payload())

    context = recorder.sent[0]
    assert context.route_name == 'my-route'
    assert context.direction == 'input'
    assert context.max_tokens == 1000
    assert context.current_usage == 800
    assert context.usage_percentage == 80
    assert context.reset_time == 4000000000


def test_a_route_without_a_cap_never_alerts(use, recorder, redis_client):
    use(recorder)

    assert _check_and_send_threshold_notification(_payload(MAX_TOKENS=0)) is False


def test_a_missing_payload_falls_back_to_unknown(use, recorder, redis_client):
    use(recorder, thresholds=[1])
    recorder._routes = ('unknown',)

    _check_and_send_threshold_notification({'MAX_TOKENS': 10, 'CURRENT_USAGE': 10})

    assert recorder.sent[0].route_name == 'unknown'
    assert recorder.sent[0].direction == 'unknown'


# --- channel selection ------------------------------------------------------


def test_a_disabled_channel_is_skipped(use, redis_client):
    disabled = _Recorder(enabled=False)
    use(disabled)

    _check_and_send_threshold_notification(_payload())

    assert disabled.sent == []


def test_a_channel_that_does_not_cover_the_route_is_skipped(use, redis_client):
    elsewhere = _Recorder(routes=('other-route',))
    use(elsewhere)

    _check_and_send_threshold_notification(_payload())

    assert elsewhere.sent == []


def test_every_eligible_channel_is_notified(use, redis_client):
    slack = _Recorder(channel_name='slack')
    email = _Recorder(channel_name='sendgrid')
    use(slack, email)

    _check_and_send_threshold_notification(_payload())

    assert len(slack.sent) == 1
    assert len(email.sent) == 1


def test_a_channel_that_declines_to_send_is_not_counted(use, redis_client):
    declining = _Recorder()
    declining.result = False
    use(declining)

    assert _check_and_send_threshold_notification(_payload()) is False


def test_one_failing_channel_does_not_stop_the_others(use, redis_client):
    """A Slack outage must not swallow the email alert."""
    broken = _Recorder(channel_name='slack')
    broken.error = RuntimeError('slack is down')
    working = _Recorder(channel_name='sendgrid')
    use(broken, working)

    assert _check_and_send_threshold_notification(_payload()) is True
    assert len(working.sent) == 1


# --- dedupe -----------------------------------------------------------------


def test_the_same_threshold_is_only_sent_once(use, recorder, redis_client):
    use(recorder)

    _check_and_send_threshold_notification(_payload())
    _check_and_send_threshold_notification(_payload())

    assert len(recorder.sent) == 1


def test_each_channel_dedupes_on_its_own(use, redis_client):
    slack = _Recorder(channel_name='slack')
    email = _Recorder(channel_name='sendgrid')
    use(slack, email)

    _check_and_send_threshold_notification(_payload())
    _check_and_send_threshold_notification(_payload())

    assert len(slack.sent) == 1
    assert len(email.sent) == 1


def test_a_new_window_alerts_again(use, recorder, redis_client):
    """The quota reset starts a fresh window, so the alert is due again."""
    use(recorder)

    _check_and_send_threshold_notification(_payload(WINDOW_ID='w1'))
    _check_and_send_threshold_notification(_payload(WINDOW_ID='w2'))

    assert len(recorder.sent) == 2


def test_each_direction_alerts_on_its_own(use, recorder, redis_client):
    use(recorder)

    _check_and_send_threshold_notification(_payload(DIRECTION='input'))
    _check_and_send_threshold_notification(_payload(DIRECTION='output'))

    assert len(recorder.sent) == 2


def test_the_dedupe_key_expires_past_the_window_reset(use, recorder, redis_client):
    """Without a TTL the key outlives its window and mutes the next one."""
    use(recorder)

    _check_and_send_threshold_notification(_payload())

    (ttl,) = redis_client.expires.values()
    assert ttl > 0


def test_a_lost_race_to_mark_the_channel_does_not_double_send(
    use, recorder, redis_client
):
    """Two workers can process the same window. Only the one that sets wins."""
    use(recorder)
    redis_client.hsetnx = lambda key, field, value: 0

    assert _check_and_send_threshold_notification(_payload()) is False
    assert recorder.sent == []


def test_without_redis_the_alert_still_goes_out(use, recorder, monkeypatch):
    """Losing the dedupe is better than losing the alert."""
    use(recorder)
    monkeypatch.setattr(celery_app, 'redis_client', None, raising=False)

    assert _check_and_send_threshold_notification(_payload()) is True


def test_a_broken_redis_mutes_the_alert(use, recorder, monkeypatch):
    """Current behaviour, pinned so a change to it is deliberate.

    The read side fails open (an unreadable mark reads as "not yet notified"),
    but the write side fails closed: a mark that cannot be stored skips the
    send. So a Redis outage silences every threshold alert, while a Redis that
    is simply absent (redis_client is None) does not.
    """
    use(recorder)
    monkeypatch.setattr(celery_app, 'redis_client', _BrokenRedis(), raising=False)

    assert _check_and_send_threshold_notification(_payload()) is False
    assert recorder.sent == []


# --- the celery task --------------------------------------------------------


def test_the_task_skips_everything_when_no_channel_is_enabled(use, redis_client):
    disabled = _Recorder(enabled=False)
    use(disabled)

    result = log_notification([_payload(), _payload()])

    assert result == {'status': 'skipped', 'notifications_sent': 0}


def test_the_task_reports_what_it_sent(use, recorder, redis_client):
    use(recorder)

    result = log_notification(_payload())

    assert result == {'status': 'processed', 'notifications_sent': 1}


def test_the_task_counts_each_notification_it_sent(use, recorder, redis_client):
    use(recorder)

    result = log_notification([_payload(WINDOW_ID='w1'), _payload(WINDOW_ID='w2')])

    assert result['notifications_sent'] == 2


def test_a_payload_below_threshold_counts_as_nothing_sent(use, recorder, redis_client):
    use(recorder)

    result = log_notification(_payload(CURRENT_USAGE=10))

    assert result == {'status': 'processed', 'notifications_sent': 0}
