"""The global alert settings: the threshold percentages and the window tick."""

from pydantic import ValidationError
import pytest

from radicalbit_ai_gateway.utils.app_config import AlertConfig, AppConfig


def test_the_thresholds_default_to_75_and_98(monkeypatch):
    monkeypatch.delenv('ALERT_THRESHOLD_PERCENTAGES', raising=False)

    assert AlertConfig().alert_threshold_percentages == [75, 98]


def test_the_thresholds_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv('ALERT_THRESHOLD_PERCENTAGES', '[50, 80, 90]')

    assert AlertConfig().alert_threshold_percentages == [50, 80, 90]


@pytest.mark.parametrize('value', ['[0]', '[100]', '[75, 120]', '[-5]'])
def test_a_threshold_outside_1_to_99_is_rejected(monkeypatch, value):
    monkeypatch.setenv('ALERT_THRESHOLD_PERCENTAGES', value)

    with pytest.raises(ValidationError):
        AlertConfig()


@pytest.mark.parametrize('value', ['[1]', '[99]'])
def test_the_bounds_are_inclusive(monkeypatch, value):
    monkeypatch.setenv('ALERT_THRESHOLD_PERCENTAGES', value)

    assert AlertConfig().alert_threshold_percentages == [int(value[1:-1])]


def test_the_app_config_carries_the_alert_section():
    assert isinstance(AppConfig().alert_config, AlertConfig)


def test_the_window_tick_defaults_to_30_seconds(monkeypatch):
    monkeypatch.delenv('ALERT_WINDOW_TICK_SECONDS', raising=False)

    assert AlertConfig().alert_window_tick_seconds == 30


def test_the_window_tick_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv('ALERT_WINDOW_TICK_SECONDS', '5')

    assert AlertConfig().alert_window_tick_seconds == 5


@pytest.mark.parametrize('value', ['0', '-1'])
def test_a_window_tick_that_is_not_positive_is_rejected(monkeypatch, value):
    monkeypatch.setenv('ALERT_WINDOW_TICK_SECONDS', value)

    with pytest.raises(ValidationError):
        AlertConfig()
