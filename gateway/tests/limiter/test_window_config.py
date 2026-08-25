"""Tests for WindowConfig and WindowStats."""

import pytest

from radicalbit_ai_gateway.limiter.window_config import (
    ScenarioType,
    WindowConfig,
    parse_window,
)

_PROJECT_UUID = '2f1c6d4e-0000-4000-8000-0000000000aa'


class TestFromParts:
    """Tests for WindowConfig.from_parts() factory method."""

    def test_from_parts_with_string_window(self) -> None:
        config = WindowConfig.from_parts(
            limit=100,
            window='1 minute',
            project_uuid=_PROJECT_UUID,
            route_name='gpt-4',
            scenario_type=ScenarioType.REQUEST_RATE,
        )
        assert config.limit == 100
        assert config.window_seconds == 60
        assert config.route_name == 'gpt-4'
        assert config.scenario_type == ScenarioType.REQUEST_RATE

    def test_from_parts_with_int_window(self) -> None:
        config = WindowConfig.from_parts(
            limit=50,
            window=30,
            project_uuid=_PROJECT_UUID,
            route_name='my-route',
            scenario_type=ScenarioType.TOKEN_INPUT,
        )
        assert config.limit == 50
        assert config.window_seconds == 30
        assert config.route_name == 'my-route'

    def test_from_parts_seconds(self) -> None:
        config = WindowConfig.from_parts(
            limit=100,
            window='1 second',
            project_uuid=_PROJECT_UUID,
            route_name='test',
            scenario_type=ScenarioType.REQUEST_RATE,
        )
        assert config.window_seconds == 1

    def test_from_parts_seconds_plural(self) -> None:
        config = WindowConfig.from_parts(
            limit=50,
            window='10 seconds',
            project_uuid=_PROJECT_UUID,
            route_name='test',
            scenario_type=ScenarioType.REQUEST_RATE,
        )
        assert config.window_seconds == 10

    def test_from_parts_minute(self) -> None:
        config = WindowConfig.from_parts(
            limit=100,
            window='1 minute',
            project_uuid=_PROJECT_UUID,
            route_name='test',
            scenario_type=ScenarioType.REQUEST_RATE,
        )
        assert config.window_seconds == 60

    def test_from_parts_minutes_plural(self) -> None:
        config = WindowConfig.from_parts(
            limit=200,
            window='5 minutes',
            project_uuid=_PROJECT_UUID,
            route_name='test',
            scenario_type=ScenarioType.REQUEST_RATE,
        )
        assert config.window_seconds == 300

    def test_from_parts_hour(self) -> None:
        config = WindowConfig.from_parts(
            limit=1000,
            window='1 hour',
            project_uuid=_PROJECT_UUID,
            route_name='test',
            scenario_type=ScenarioType.REQUEST_RATE,
        )
        assert config.window_seconds == 3600

    def test_from_parts_hours_plural(self) -> None:
        config = WindowConfig.from_parts(
            limit=5000,
            window='2 hours',
            project_uuid=_PROJECT_UUID,
            route_name='test',
            scenario_type=ScenarioType.REQUEST_RATE,
        )
        assert config.window_seconds == 7200

    def test_from_parts_day(self) -> None:
        config = WindowConfig.from_parts(
            limit=10000,
            window='1 day',
            project_uuid=_PROJECT_UUID,
            route_name='test',
            scenario_type=ScenarioType.REQUEST_RATE,
        )
        assert config.window_seconds == 86400

    def test_from_parts_week(self) -> None:
        config = WindowConfig.from_parts(
            limit=50000,
            window='1 week',
            project_uuid=_PROJECT_UUID,
            route_name='test',
            scenario_type=ScenarioType.REQUEST_RATE,
        )
        assert config.window_seconds == 604800

    def test_from_parts_weeks_plural(self) -> None:
        config = WindowConfig.from_parts(
            limit=100000,
            window='2 weeks',
            project_uuid=_PROJECT_UUID,
            route_name='test',
            scenario_type=ScenarioType.REQUEST_RATE,
        )
        assert config.window_seconds == 1209600

    def test_from_parts_month(self) -> None:
        config = WindowConfig.from_parts(
            limit=100000,
            window='1 month',
            project_uuid=_PROJECT_UUID,
            route_name='test',
            scenario_type=ScenarioType.REQUEST_RATE,
        )
        assert config.window_seconds == 2592000

    def test_from_parts_months_plural(self) -> None:
        config = WindowConfig.from_parts(
            limit=200000,
            window='3 months',
            project_uuid=_PROJECT_UUID,
            route_name='test',
            scenario_type=ScenarioType.REQUEST_RATE,
        )
        assert config.window_seconds == 7776000


class TestParseWindow:
    """Tests for parse_window() function."""

    def test_parse_seconds(self) -> None:
        assert parse_window('1 second') == 1

    def test_parse_seconds_plural(self) -> None:
        assert parse_window('10 seconds') == 10

    def test_parse_minute(self) -> None:
        assert parse_window('1 minute') == 60

    def test_parse_minutes_plural(self) -> None:
        assert parse_window('5 minutes') == 300

    def test_parse_hour(self) -> None:
        assert parse_window('1 hour') == 3600

    def test_parse_hours_plural(self) -> None:
        assert parse_window('2 hours') == 7200

    def test_parse_day(self) -> None:
        assert parse_window('1 day') == 86400

    def test_parse_week(self) -> None:
        assert parse_window('1 week') == 604800

    def test_parse_weeks_plural(self) -> None:
        assert parse_window('2 weeks') == 1209600

    def test_parse_month(self) -> None:
        assert parse_window('1 month') == 2592000

    def test_parse_months_plural(self) -> None:
        assert parse_window('3 months') == 7776000

    def test_parse_with_spaces(self) -> None:
        assert parse_window('  1 minute  ') == 60

    def test_parse_invalid_format(self) -> None:
        with pytest.raises(ValueError, match='Invalid window format'):
            parse_window('invalid')

    def test_parse_invalid_unit(self) -> None:
        with pytest.raises(ValueError, match='Unknown time unit'):
            parse_window('1 year')
