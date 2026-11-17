"""The global alert settings: the threshold percentages and the window tick."""

from pydantic import ValidationError
import pytest

from radicalbit_ai_gateway.utils.app_config import AlertConfig, AppConfig

THRESHOLDS = 'ALERT_THRESHOLD_PERCENTAGES'
TICK = 'ALERT_WINDOW_TICK_SECONDS'


@pytest.mark.parametrize(
    ('env', 'value', 'attribute', 'expected'),
    [
        pytest.param(THRESHOLDS, None, 'alert_threshold_percentages', [75, 98], id='thresholds-default'),
        pytest.param(THRESHOLDS, '[50, 80, 90]', 'alert_threshold_percentages', [50, 80, 90], id='thresholds-from-env'),
        # The 1..99 bounds are inclusive.
        pytest.param(THRESHOLDS, '[1]', 'alert_threshold_percentages', [1], id='threshold-lower-bound'),
        pytest.param(THRESHOLDS, '[99]', 'alert_threshold_percentages', [99], id='threshold-upper-bound'),
        pytest.param(TICK, None, 'alert_window_tick_seconds', 30, id='tick-default'),
        pytest.param(TICK, '5', 'alert_window_tick_seconds', 5, id='tick-from-env'),
    ],
)  # fmt: skip
def test_alert_setting_is_read(monkeypatch, env, value, attribute, expected):
    if value is None:
        monkeypatch.delenv(env, raising=False)
    else:
        monkeypatch.setenv(env, value)

    assert getattr(AlertConfig(), attribute) == expected


@pytest.mark.parametrize(
    ('env', 'value'),
    [
        # A threshold outside 1..99.
        pytest.param(THRESHOLDS, '[0]', id='threshold-0'),
        pytest.param(THRESHOLDS, '[100]', id='threshold-100'),
        pytest.param(THRESHOLDS, '[75, 120]', id='threshold-120'),
        pytest.param(THRESHOLDS, '[-5]', id='threshold-negative'),
        # A window tick that is not positive.
        pytest.param(TICK, '0', id='tick-0'),
        pytest.param(TICK, '-1', id='tick-negative'),
    ],
)
def test_invalid_alert_setting_is_rejected(monkeypatch, env, value):
    monkeypatch.setenv(env, value)

    with pytest.raises(ValidationError):
        AlertConfig()


def test_the_app_config_carries_the_alert_section():
    assert isinstance(AppConfig().alert_config, AlertConfig)
