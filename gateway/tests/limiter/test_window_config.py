"""Tests for WindowConfig and parse_window."""

import pytest

from radicalbit_ai_gateway.limiter.window_config import (
    ScenarioType,
    WindowConfig,
    parse_window,
)

_PROJECT_UUID = '2f1c6d4e-0000-4000-8000-0000000000aa'


@pytest.mark.parametrize(
    ('window', 'seconds'),
    [
        ('1 second', 1),
        ('10 seconds', 10),
        ('1 minute', 60),
        ('5 minutes', 300),
        ('1 hour', 3600),
        ('2 hours', 7200),
        ('1 day', 86400),
        ('1 week', 604800),
        ('2 weeks', 1209600),
        ('1 month', 2592000),
        ('3 months', 7776000),
        ('  1 minute  ', 60),
    ],
)
def test_parse_window_reads_a_count_and_a_unit_singular_or_plural(
    window, seconds
) -> None:
    assert parse_window(window) == seconds


@pytest.mark.parametrize(
    ('window', 'error'),
    [
        pytest.param('invalid', 'Invalid window format', id='no-count'),
        pytest.param('1 year', 'Unknown time unit', id='unknown-unit'),
    ],
)
def test_parse_window_rejects_what_it_cannot_read(window, error) -> None:
    with pytest.raises(ValueError, match=error):
        parse_window(window)


@pytest.mark.parametrize(
    ('window', 'scenario_type', 'window_seconds'),
    [
        pytest.param('5 minutes', ScenarioType.REQUEST_RATE, 300, id='string-parsed'),
        pytest.param(30, ScenarioType.TOKEN_INPUT, 30, id='int-in-seconds'),
    ],
)
def test_from_parts_takes_the_window_as_a_string_or_in_seconds(
    window, scenario_type, window_seconds
) -> None:
    config = WindowConfig.from_parts(
        limit=100,
        window=window,
        project_uuid=_PROJECT_UUID,
        route_name='gpt-4',
        scenario_type=scenario_type,
    )

    assert config.limit == 100
    assert config.window_seconds == window_seconds
    assert config.project_uuid == _PROJECT_UUID
    assert config.route_name == 'gpt-4'
    assert config.scenario_type == scenario_type
