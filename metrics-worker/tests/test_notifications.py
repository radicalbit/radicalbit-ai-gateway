"""Threshold alerts: who gets told, once, and what the message says."""

import datetime

import pytest

from worker.notifications.base import NotificationContext
from worker.notifications.notifier import calculate_usage_percentage
from worker.notifications.registry import NotifierRegistry
from worker.notifications.sendgrid import SendGridNotifier, _build_sendgrid_url
from worker.notifications.slack import SlackNotifier


class _Section:
    def __init__(self, **values):
        self.__dict__.update(values)


def _config(**overrides) -> _Section:
    sections = {
        'slack': _Section(
            slack_enabled=True,
            slack_webhook_mappings={'my-route': 'slack://T/B/xxx'},
            slack_user_mappings={},
        ),
        'sendgrid': _Section(
            sendgrid_enabled=True,
            sendgrid_api_key='key',
            sendgrid_from_email='alerts@example.com',
            sendgrid_template_id=None,
            sendgrid_email_mappings={'my-route': ['a@example.com']},
        ),
        'notification': _Section(notification_thresholds=[75, 98]),
        'log': _Section(log_level='INFO'),
    }
    sections.update(overrides)
    return _Section(**sections)


def _context(**overrides) -> NotificationContext:
    fields = {
        'route_name': 'my-route',
        'direction': 'input',
        'max_tokens': 1000,
        'current_usage': 800,
        'usage_percentage': 80,
        'reset_time': 1700000000,
        'threshold': 75,
        'is_highest': False,
    }
    fields.update(overrides)
    return NotificationContext(**fields)


class _FakeApprise:
    """Stands in for apprise.Apprise. Records what would have been sent."""

    instances: list['_FakeApprise'] = []

    def __init__(self, add_succeeds: bool = True):
        self.urls: list[str] = []
        self.sent: list[dict] = []
        self._add_succeeds = add_succeeds
        _FakeApprise.instances.append(self)

    def add(self, url: str) -> bool:
        self.urls.append(url)
        return self._add_succeeds


@pytest.fixture
def apprise_calls(monkeypatch):
    """Capture every Apprise notification instead of sending one."""
    _FakeApprise.instances = []

    def notify(self, title, body, body_format):
        self.sent.append({'title': title, 'body': body, 'format': body_format})

    monkeypatch.setattr(_FakeApprise, 'notify', notify, raising=False)
    for module in ('worker.notifications.slack', 'worker.notifications.sendgrid'):
        monkeypatch.setattr(f'{module}.apprise.Apprise', _FakeApprise)
    return _FakeApprise.instances


# --- usage percentage -------------------------------------------------------


@pytest.mark.parametrize(
    ('usage', 'maximum', 'expected'),
    [
        (800, 1000, 80),
        (0, 1000, 0),
        (1000, 1000, 100),
        (1500, 1000, 150),
        (999, 1000, 99),
        (5, 1000, 0),
    ],
)
def test_usage_percentage(usage, maximum, expected):
    assert calculate_usage_percentage(usage, maximum) == expected


@pytest.mark.parametrize('maximum', [0, -1])
def test_an_unlimited_route_reports_zero_percent(maximum):
    """No cap means no threshold to cross, and never a divide by zero."""
    assert calculate_usage_percentage(800, maximum) == 0


# --- slack ------------------------------------------------------------------


def test_slack_is_disabled_when_the_flag_is_off():
    config = _config(slack=_Section(slack_enabled=False, slack_webhook_mappings={}))

    assert SlackNotifier(config).is_enabled() is False


def test_slack_only_notifies_routes_that_have_a_webhook():
    notifier = SlackNotifier(_config())

    assert notifier.can_notify('my-route') is True
    assert notifier.can_notify('other-route') is False


def test_slack_sends_the_usage_and_the_reset_time(apprise_calls):
    notifier = SlackNotifier(_config())

    assert notifier.send(_context()) is True

    (client,) = apprise_calls
    assert client.urls == ['slack://T/B/xxx']
    body = client.sent[0]['body']
    assert '*Route:* my-route' in body
    assert '*Direction:* INPUT' in body
    assert '800 / 1,000 tokens (80%)' in body
    assert client.sent[0]['title'].endswith('Token Usage Alert')


def test_slack_tags_the_configured_user(apprise_calls):
    config = _config(
        slack=_Section(
            slack_enabled=True,
            slack_webhook_mappings={'my-route': 'slack://T/B/xxx'},
            slack_user_mappings={'my-route': 'U123'},
        )
    )

    SlackNotifier(config).send(_context())

    assert '<@U123>' in apprise_calls[0].sent[0]['body']


def test_slack_leaves_out_the_tag_when_no_user_is_mapped(apprise_calls):
    SlackNotifier(_config()).send(_context())

    assert '<@' not in apprise_calls[0].sent[0]['body']


def test_the_highest_threshold_escalates_the_slack_icon(apprise_calls):
    SlackNotifier(_config()).send(_context(is_highest=True))

    assert apprise_calls[0].sent[0]['title'].startswith('🚨')


def test_a_lower_threshold_uses_the_warning_icon(apprise_calls):
    SlackNotifier(_config()).send(_context(is_highest=False))

    assert apprise_calls[0].sent[0]['title'].startswith('⚠️')


def test_slack_sends_nothing_for_an_unmapped_route(apprise_calls):
    assert SlackNotifier(_config()).send(_context(route_name='other')) is False
    assert apprise_calls == []


def test_a_slack_webhook_apprise_rejects_sends_nothing(apprise_calls, monkeypatch):
    monkeypatch.setattr(
        'worker.notifications.slack.apprise.Apprise',
        lambda: _FakeApprise(add_succeeds=False),
    )

    assert SlackNotifier(_config()).send(_context()) is False
    assert apprise_calls[0].sent == []


# --- sendgrid url building --------------------------------------------------


def test_no_recipients_builds_no_url():
    assert _build_sendgrid_url('key', 'from@x.com', [], None) == ''


def test_a_single_recipient_needs_no_query_string():
    url = _build_sendgrid_url('key', 'from@x.com', ['a@x.com'], None)

    assert url == 'sendgrid://key:from@x.com/a@x.com'


def test_extra_recipients_go_to_cc():
    url = _build_sendgrid_url('key', 'from@x.com', ['a@x.com', 'b@x.com'], None)

    assert url.endswith('?cc=b@x.com')


def test_many_extra_recipients_are_comma_separated():
    url = _build_sendgrid_url(
        'key', 'from@x.com', ['a@x.com', 'b@x.com', 'c@x.com'], None
    )

    assert url.endswith('?cc=b@x.com,c@x.com')


def test_a_template_id_rides_in_the_query_string():
    url = _build_sendgrid_url('key', 'from@x.com', ['a@x.com'], 'd-123')

    assert url.endswith('?template=d-123')


def test_template_variables_take_the_plus_prefix():
    url = _build_sendgrid_url(
        'key', 'from@x.com', ['a@x.com'], 'd-123', {'route_name': 'my-route'}
    )

    assert '+route_name=my-route' in url


def test_template_variables_are_url_encoded():
    """A usage string carries '%', '/' and spaces. Unencoded they break the URL."""
    url = _build_sendgrid_url(
        'key', 'from@x.com', ['a@x.com'], 'd-123', {'msg': '80% (800 / 1,000)'}
    )

    assert '+msg=80%25%20%28800%20%2F%201%2C000%29' in url


def test_template_variables_are_dropped_without_a_template():
    url = _build_sendgrid_url('key', 'from@x.com', ['a@x.com'], None, {'a': 'b'})

    assert '+a=b' not in url


# --- sendgrid notifier ------------------------------------------------------


def test_sendgrid_is_disabled_when_the_flag_is_off():
    config = _config(sendgrid=_Section(sendgrid_enabled=False))

    assert SendGridNotifier(config).is_enabled() is False


@pytest.mark.parametrize('missing', ['sendgrid_api_key', 'sendgrid_from_email'])
def test_sendgrid_cannot_notify_without_full_credentials(missing):
    config = _config()
    setattr(config.sendgrid, missing, None)

    assert SendGridNotifier(config).can_notify('my-route') is False


def test_sendgrid_only_notifies_routes_with_a_recipient():
    notifier = SendGridNotifier(_config())

    assert notifier.can_notify('my-route') is True
    assert notifier.can_notify('other-route') is False


@pytest.mark.parametrize('missing', ['sendgrid_api_key', 'sendgrid_from_email'])
def test_sendgrid_sends_nothing_without_full_credentials(missing, apprise_calls):
    config = _config()
    setattr(config.sendgrid, missing, None)

    assert SendGridNotifier(config).send(_context()) is False
    assert apprise_calls == []


def test_sendgrid_sends_nothing_for_an_unmapped_route(apprise_calls):
    assert SendGridNotifier(_config()).send(_context(route_name='other')) is False
    assert apprise_calls == []


def test_sendgrid_sends_html_when_no_template_is_configured(apprise_calls):
    assert SendGridNotifier(_config()).send(_context()) is True

    sent = apprise_calls[0].sent[0]
    assert '<strong>Route:</strong> my-route' in sent['body']
    assert '800 / 1,000 tokens (80%)' in sent['body']


def test_sendgrid_reports_the_reset_time_in_utc(apprise_calls):
    expected = datetime.datetime.fromtimestamp(1700000000, tz=datetime.UTC).strftime(
        '%d-%m-%Y, %H:%M:%S UTC'
    )

    SendGridNotifier(_config()).send(_context())

    assert expected in apprise_calls[0].sent[0]['body']


def test_a_configured_template_replaces_the_body(apprise_calls):
    config = _config()
    config.sendgrid.sendgrid_template_id = 'd-123'

    assert SendGridNotifier(config).send(_context()) is True

    client = apprise_calls[0]
    assert 'template=d-123' in client.urls[0]
    assert '+route_name=my-route' in client.urls[0]
    assert client.sent[0]['body'] == 'Template notification'


def test_a_sendgrid_url_apprise_rejects_sends_nothing(apprise_calls, monkeypatch):
    monkeypatch.setattr(
        'worker.notifications.sendgrid.apprise.Apprise',
        lambda: _FakeApprise(add_succeeds=False),
    )

    assert SendGridNotifier(_config()).send(_context()) is False
    assert apprise_calls[0].sent == []


# --- registry ---------------------------------------------------------------


def test_the_registry_builds_slack_and_sendgrid_once():
    registry = NotifierRegistry(_config())

    first = registry.get_notifiers()

    assert [n.channel_name for n in first] == ['slack', 'sendgrid']
    assert registry.get_notifiers() is first


def test_a_registry_reports_enabled_when_any_channel_is():
    config = _config(sendgrid=_Section(sendgrid_enabled=False))

    assert NotifierRegistry(config).any_enabled() is True


def test_a_registry_with_every_channel_off_reports_disabled():
    config = _config(
        slack=_Section(slack_enabled=False, slack_webhook_mappings={}),
        sendgrid=_Section(sendgrid_enabled=False),
    )

    assert NotifierRegistry(config).any_enabled() is False


def test_an_added_notifier_joins_the_defaults():
    registry = NotifierRegistry(_config())
    registry.get_notifiers()

    registry.add_notifier(SlackNotifier(_config()))

    assert len(registry.get_notifiers()) == 3


def test_a_notifier_added_before_first_use_replaces_the_defaults():
    """add_notifier() on a cold registry skips lazy init, by design."""
    registry = NotifierRegistry(_config())

    registry.add_notifier(SlackNotifier(_config()))

    assert [n.channel_name for n in registry.get_notifiers()] == ['slack']
