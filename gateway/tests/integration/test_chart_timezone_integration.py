"""Integration test for timezone-aware chart data bucketing.

This test uses real ClickHouse data to verify that timezone-aware bucketing works correctly.
"""

import datetime
from unittest.mock import MagicMock
import uuid

import pytest

from tests.common.db_integration_ch import DatabaseIntegrationClickhouse
from tests.common.db_mock import get_sample_event, get_sample_request_event

from radicalbit_ai_gateway.db.dao.event_dao import EventDAO
from radicalbit_ai_gateway.db.dao.request_event_dao import RequestEventDAO
from radicalbit_ai_gateway.services.event_service import EventService
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.services.request_event_service import RequestEventService

_iso = datetime.datetime.fromisoformat


def _utc(*parts: int) -> datetime.datetime:
    return datetime.datetime(*parts, tzinfo=datetime.timezone.utc)


def _token_event(route_name, timestamp, kind, value, cost=0.01):
    return get_sample_event(
        event_type=f'{kind}_TOKEN_PROCESSED',
        route_name=route_name,
        timestamp=timestamp,
        api_key_uuid=uuid.UUID(int=1),
        api_key_name='key-1',
        value=value,
        model_id='gpt-4',
        cost=cost,
    )


class TestChartTimezoneIntegration(DatabaseIntegrationClickhouse):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Key name resolution returns the UUID string as name
        key_service = MagicMock(spec_set=KeyService)
        key_service.get_names_by_uuids.side_effect = lambda uuids: {
            u: str(u) for u in uuids
        }
        cls.event_service = EventService(
            event_dao=EventDAO(cls.db),
            request_event_dao=MagicMock(spec_set=RequestEventDAO),
            key_service=key_service,
            group_service=MagicMock(spec_set=GroupService),
        )
        cls.request_event_service = RequestEventService(
            request_event_dao=RequestEventDAO(cls.db),
        )

    def test_costs_chart_buckets_events_in_the_user_timezone(self):
        """Every event inside the user's local range lands in a bucket.

        Each case pairs (UTC timestamp, cost) events with a local-time range;
        the granularity follows from the range length.
        """
        cases = [
            # Events at local 00:30 GMT+01:00 fall on the user's day, not the UTC one.
            (
                'days',
                [
                    (_utc(2025, 12, 31, 23, 30), 0.01),
                    (_utc(2025, 12, 31, 23, 30), 0.015),
                    (_utc(2026, 1, 1, 23, 30), 0.02),
                ],
                '2026-01-01T00:00:00+01:00',
                '2026-01-04T00:00:00+01:00',
            ),
            (
                'months',
                [(_utc(2026, 1, 15, 12), 0.01), (_utc(2026, 2, 15, 12), 0.02)],
                '2025-01-01T00:00:00+01:00',
                '2026-03-01T00:00:00+01:00',
            ),
            (
                'hours',
                [(_utc(2025, 12, 31, 23, 30), 0.01), (_utc(2026, 1, 1, 0, 30), 0.02)],
                '2026-01-01T00:00:00+01:00',
                '2026-01-01T03:00:00+01:00',
            ),
            # Range starts on a Thursday in GMT-08:00.
            (
                'weeks',
                [(_utc(2026, 1, 8, 20), 0.01)],
                '2026-01-08T00:00:00-08:00',
                '2026-03-08T00:00:00-08:00',
            ),
            (
                'days',
                [(_utc(2026, 1, 15, 5, 30), 0.01)],
                '2026-01-15T00:00:00-05:00',
                '2026-01-18T00:00:00-05:00',
            ),
            (
                'months',
                [(_utc(2026, 1, 15, 12), 0.01), (_utc(2026, 2, 15, 12), 0.02)],
                '2025-01-01T00:00:00-05:00',
                '2026-03-01T00:00:00-05:00',
            ),
            # Long range over several years: buckets used to come back all zero.
            (
                'months',
                [
                    (_utc(2024, 12, 15, 12), 0.01),
                    (_utc(2025, 1, 15, 12), 0.02),
                    (_utc(2025, 2, 15, 12), 0.03),
                    (_utc(2025, 3, 15, 12), 0.04),
                    (_utc(2026, 1, 15, 12), 0.05),
                ],
                '2024-12-01T00:00:00+01:00',
                '2026-02-27T22:00:00+01:00',
            ),
        ]
        for i, (granularity, events, _from, _to) in enumerate(cases):
            with self.subTest(granularity=granularity, _from=_from):
                route_name = f'test-route-costs-{i}'
                self.insert(
                    [_token_event(route_name, ts, 'INPUT', 1000, c) for ts, c in events]
                )

                result = self.event_service.get_costs_chart_data(
                    None,
                    route_names=[route_name],
                    _from=_iso(_from),
                    _to=_iso(_to),
                    group_by='keys',
                )

                expected = sum(c for _, c in events)
                assert result.granularity == granularity
                assert len(result.timestamp) > 0
                assert len(result.data) == 1
                assert sum(result.data[0].data) == pytest.approx(expected)
                assert result.total == pytest.approx(expected)

    def test_token_chart_buckets_events_in_the_user_timezone(self):
        cases = [
            (
                'days',
                [
                    (_utc(2025, 12, 31, 23, 30), 'INPUT', 1000),
                    (_utc(2025, 12, 31, 23, 30), 'OUTPUT', 500),
                    (_utc(2026, 1, 1, 23, 30), 'INPUT', 2000),
                ],
                '2026-01-01T00:00:00+01:00',
                '2026-01-03T00:00:00+01:00',
            ),
            (
                'hours',
                [
                    (_utc(2025, 12, 31, 23, 30), 'INPUT', 1000),
                    (_utc(2026, 1, 1, 0, 30), 'OUTPUT', 500),
                ],
                '2026-01-01T00:00:00+01:00',
                '2026-01-01T03:00:00+01:00',
            ),
            (
                'months',
                [
                    (_utc(2026, 1, 15, 12), 'INPUT', 1500),
                    (_utc(2026, 1, 15, 12), 'OUTPUT', 750),
                    (_utc(2026, 2, 15, 12), 'INPUT', 3000),
                ],
                '2026-01-01T00:00:00-05:00',
                '2026-03-01T00:00:00-05:00',
            ),
            (
                'weeks',
                [(_utc(2026, 1, 8, 20), 'INPUT', 2500)],
                '2026-01-08T00:00:00-08:00',
                '2026-01-22T00:00:00-08:00',
            ),
            (
                'months',
                [
                    (_utc(2024, 12, 15, 12), 'INPUT', 1000),
                    (_utc(2025, 1, 15, 12), 'INPUT', 2000),
                    (_utc(2026, 2, 15, 12), 'OUTPUT', 3000),
                ],
                '2024-12-01T00:00:00+01:00',
                '2026-02-27T22:00:00+01:00',
            ),
        ]
        for i, (granularity, events, _from, _to) in enumerate(cases):
            with self.subTest(granularity=granularity, _from=_from):
                route_name = f'test-route-tokens-{i}'
                self.insert(
                    [_token_event(route_name, ts, kind, v) for ts, kind, v in events]
                )

                result = self.event_service.get_token_chart_data(
                    None,
                    route_names=[route_name],
                    _from=_iso(_from),
                    _to=_iso(_to),
                    granularity=granularity,
                )

                assert result.granularity == granularity
                assert len(result.timestamp) > 0
                assert [s.name for s in result.data] == ['INPUT', 'OUTPUT']
                for series in result.data:
                    assert sum(series.data) == sum(
                        v for _, kind, v in events if kind == series.name
                    )
                assert result.total == sum(v for _, _, v in events)

    def test_token_chart_empty_result(self):
        result = self.event_service.get_token_chart_data(
            None,
            route_names=['test-route-tokens-empty'],
            _from=_iso('2026-01-01T00:00:00+01:00'),
            _to=_iso('2026-01-03T00:00:00+01:00'),
            granularity='days',
        )

        assert result.granularity == 'days'
        assert result.total == 0
        assert result.timestamp == []
        assert result.data == []

    def test_monthly_buckets_no_skipped_months_gmt_plus_2(self):
        """Test monthly buckets progression with GMT+02:00 timezone.

        This test reproduces the specific bug where month advancement would skip
        months (e.g., October → December, skipping November) when using
        timedelta(days=32) instead of relativedelta.

        Scenario: User in GMT+02:00 queries token data for a full year.
        Expected: Exactly 12 buckets with all months present, no duplicates.
        Explicitly checks October → November progression which was problematic.
        """
        route_name = 'test-route-months-progression'

        # Insert one event per month for a full year
        events = [
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2024, month, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='gpt-4',
                cost=0.01,
            )
            for month in range(1, 13)
        ]

        for event in events:
            self.insert([event])

        # Query with GMT+02:00 timezone for the full year
        # Note: _to is exclusive, so 2025-01-01 gives us buckets through Dec 2024
        # The bucket generation creates one extra bucket at the end (Jan 2025)
        # which will have 0 data since we only inserted data for 2024
        _from = datetime.datetime.fromisoformat('2024-01-01T00:00:00+02:00')
        _to = datetime.datetime.fromisoformat('2025-01-01T00:00:00+02:00')

        result = self.event_service.get_token_chart_data(
            None,
            route_names=[route_name],
            _from=_from,
            _to=_to,
            granularity='months',
        )

        # Basic assertions
        assert result.granularity == 'months'
        assert len(result.timestamp) == 13, (
            f'Expected 13 monthly buckets (Jan-Dec + Jan), got {len(result.timestamp)}'
        )
        assert len(result.data) == 2, 'Should have INPUT and OUTPUT series'
        assert result.total == 12000, 'Total tokens should be 12 * 1000'

        # Verify first 12 months have non-zero data (Jan-Dec 2024)
        # The 13th bucket (Jan 2025) will have 0 since we only inserted data for 2024
        data_values = result.data[0].data  # INPUT series
        assert len(data_values) == 13, (
            f'Expected 13 data points, got {len(data_values)}'
        )
        assert all(v > 0 for v in data_values[:12]), (
            'First 12 months (Jan-Dec 2024) should have non-zero values'
        )
        assert data_values[12] == 0, (
            '13th bucket (Jan 2025) should have 0 since no data was inserted'
        )

        # Verify October → November progression explicitly
        # This was the specific bug case
        # Find October and November bucket indices (excluding the last Jan 2025 bucket)
        months_in_buckets = []
        years_in_buckets = []
        for ts in result.timestamp:
            # Convert timestamp to datetime in GMT+02:00
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
            # Adjust to GMT+02:00
            dt_gmt2 = dt + datetime.timedelta(hours=2)
            months_in_buckets.append(dt_gmt2.month)
            years_in_buckets.append(dt_gmt2.year)

        # We should have: Jan 2024, Feb-Dec 2024, and Jan 2025
        # That's: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1] for months
        # And: [2024, 2024, 2024, 2024, 2024, 2024, 2024, 2024, 2024, 2024, 2024, 2024, 2025] for years
        assert months_in_buckets == [
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            11,
            12,
            1,
        ], f'Expected month sequence for 2024 + Jan 2025, got {months_in_buckets}'
        assert years_in_buckets == [2024] * 12 + [2025], (
            f'Expected 12 months in 2024 + Jan 2025, got years: {years_in_buckets}'
        )

        # Verify October (10) is followed by November (11)
        # Find the first October (index 9, 0-based) and verify November is at index 10
        october_idx = months_in_buckets.index(10)
        november_idx = months_in_buckets.index(11)
        assert october_idx == 9, f'October should be at index 9, got {october_idx}'
        assert november_idx == 10, f'November should be at index 10, got {november_idx}'
        assert november_idx == october_idx + 1, (
            f'November should immediately follow October, got indices {october_idx} -> {november_idx}'
        )

    def test_request_chart_buckets_events_in_the_user_timezone(self):
        cases = [
            (
                'days',
                [
                    _utc(2025, 12, 31, 23, 30),
                    _utc(2025, 12, 31, 23, 45),
                    _utc(2026, 1, 1, 23, 30),
                ],
                '2026-01-01T00:00:00+01:00',
                '2026-01-03T00:00:00+01:00',
            ),
            (
                'hours',
                [_utc(2025, 12, 31, 23, 30), _utc(2026, 1, 1, 0, 30)],
                '2026-01-01T00:00:00+01:00',
                '2026-01-01T03:00:00+01:00',
            ),
            (
                'months',
                [_utc(2026, 1, 15, 12), _utc(2026, 2, 15, 12)],
                '2026-01-01T00:00:00-05:00',
                '2026-03-01T00:00:00-05:00',
            ),
            (
                'weeks',
                [_utc(2026, 1, 8, 20)],
                '2026-01-08T00:00:00-08:00',
                '2026-01-22T00:00:00-08:00',
            ),
        ]
        for i, (granularity, timestamps, _from, _to) in enumerate(cases):
            with self.subTest(granularity=granularity, _from=_from):
                route_name = f'test-route-requests-{i}'
                self.insert(
                    [
                        get_sample_request_event(
                            route_name=route_name,
                            timestamp=ts,
                            api_key_uuid=uuid.UUID(int=1),
                            api_key_name='key-1',
                        )
                        for ts in timestamps
                    ]
                )

                result = self.request_event_service.get_request_chart_data(
                    None,
                    route_name=route_name,
                    _from=_iso(_from),
                    _to=_iso(_to),
                    granularity=granularity,
                )

                assert result.granularity == granularity
                assert len(result.timestamp) > 0
                assert result.total == len(timestamps)
                assert sum(result.data) == len(timestamps)
