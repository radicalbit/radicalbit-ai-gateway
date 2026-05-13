"""Integration test for timezone-aware chart data bucketing.

This test uses real ClickHouse data to verify that timezone-aware bucketing works correctly.
"""

import datetime
from unittest.mock import MagicMock
import uuid

from tests.common.db_integration_ch import DatabaseIntegrationClickhouse
from tests.common.db_mock import get_sample_event, get_sample_request_event
from tests.common.mocked_gateway_config import (
    get_default_cache_config,
    get_default_gateway,
    get_global_guardrails,
)

from radicalbit_ai_gateway.db.dao.event_dao import EventDAO
from radicalbit_ai_gateway.db.dao.request_event_dao import RequestEventDAO
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.services.event_service import EventService
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.services.request_event_service import RequestEventService


class TestChartTimezoneIntegration(DatabaseIntegrationClickhouse):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.event_dao = EventDAO(cls.db)
        cls.request_event_dao = MagicMock(spec_set=RequestEventDAO)

        # Create mock services for EventService dependencies
        cls.key_service = MagicMock(spec_set=KeyService)
        cls.group_service = MagicMock(spec_set=GroupService)
        cls.cost_service = MagicMock(spec_set=CostService)

        # Create a minimal gateway config
        gw = get_default_gateway(route_name='test-route')
        global_guardrails = get_global_guardrails()
        cls.gateway_config = GatewayConfig(
            chat_models=gw.chat_models,
            embedding_models=gw.embedding_models,
            routes=gw.routes,
            guardrails=global_guardrails,
            cache=get_default_cache_config(),
        )

        cls.request_event_dao = MagicMock(spec_set=RequestEventDAO)
        cls.event_service = EventService(
            event_dao=cls.event_dao,
            request_event_dao=cls.request_event_dao,
            key_service=cls.key_service,
            group_service=cls.group_service,
        )

        cls.request_event_dao = RequestEventDAO(cls.db)
        cls.request_event_service = RequestEventService(
            request_event_dao=cls.request_event_dao,
        )

        # Default: key/group name resolution returns the UUID string as name
        cls.key_service.get_names_by_uuids = MagicMock(
            side_effect=lambda uuids: {u: str(u) for u in uuids}
        )
        cls.group_service.get_names_by_uuids = MagicMock(
            side_effect=lambda uuids: {u: str(u) for u in uuids}
        )

    def test_daily_buckets_with_gmt_plus_1(self):
        """Test daily buckets with user in GMT+01:00 timezone.

        Scenario: User in GMT+01:00 requests data for 2026-01-01 to 2026-01-02.
        Expected: Data should be returned in daily buckets aligned to GMT+01:00.
        """
        route_name = 'test-route'

        # Insert test data:
        # Event at 2026-01-01 00:30:00 GMT+01:00 (2025-12-31 23:30:00 UTC)
        # This should appear in the "2026-01-01" bucket for the user, not "2025-12-31"
        events = [
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2025, 12, 31, 23, 30, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='gpt-4',
                cost=0.01,
            ),
            get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2025, 12, 31, 23, 30, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=500,
                model_id='gpt-4',
                cost=0.015,
            ),
            # Another event on 2026-01-02 00:30:00 GMT+01:00 (2026-01-01 23:30:00 UTC)
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 1, 23, 30, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=2000,
                model_id='gpt-4',
                cost=0.02,
            ),
        ]

        for event in events:
            self.insert([event])

        # Query with GMT+01:00 timezone
        # 2026-01-01T00:00:00+01:00 = 2025-12-31T23:00:00Z
        # 2026-01-03T00:00:00+01:00 = 2026-01-02T23:00:00Z
        _from = datetime.datetime.fromisoformat('2026-01-01T00:00:00+01:00')
        _to = datetime.datetime.fromisoformat('2026-01-04T00:00:00+01:00')

        result = self.event_service.get_costs_chart_data(
            None,
            route_names=[route_name],
            _from=_from,
            _to=_to,
            group_by='keys',
        )

        # Assertions
        assert result.granularity == 'days'
        assert len(result.timestamp) > 0, 'Should have at least one bucket'
        assert len(result.data) > 0, 'Should have at least one series'

        # The total cost should be non-zero if data is matched correctly
        total_cost = sum(result.data[0].data)
        assert total_cost > 0, (
            f'Expected non-zero cost, got {total_cost}. Data not matched to buckets correctly!'
        )

    def test_monthly_buckets_with_gmt_plus_1(self):
        """Test monthly buckets work correctly with UTC bucketing.

        Buckets are created in UTC to match ClickHouse's toStartOfMonth() output.
        User queries with timezone-aware parameters, which are converted to UTC for the query.
        """
        route_name = 'test-route-monthly'

        # Insert test data in January 2026 (UTC)
        events = [
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='gpt-4',
                cost=0.01,
            ),
            # More data in February 2026
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 2, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=2000,
                model_id='gpt-4',
                cost=0.02,
            ),
        ]

        for event in events:
            self.insert([event])

        # Query with GMT+01:00 timezone for January-February 2026
        # Range must be >336 days for 'months' granularity
        _from = datetime.datetime.fromisoformat('2025-01-01T00:00:00+01:00')
        _to = datetime.datetime.fromisoformat('2026-03-01T00:00:00+01:00')

        result = self.event_service.get_costs_chart_data(
            None,
            route_names=[route_name],
            _from=_from,
            _to=_to,
            group_by='keys',
        )

        # Assertions
        assert result.granularity == 'months'
        assert len(result.timestamp) > 0, 'Should have at least one bucket'
        assert len(result.data) > 0, 'Should have at least one series'

        # The total cost should be non-zero if data is matched correctly
        total_cost = sum(result.data[0].data)
        assert total_cost > 0, (
            f'Expected non-zero cost, got {total_cost}. Data not matched to buckets correctly!'
        )

    def test_hourly_buckets_with_gmt_plus_1(self):
        """Test hourly buckets with user in GMT+01:00 timezone.

        Scenario: User in GMT+01:00 requests data for a specific hour.
        Expected: Data should be returned in hourly buckets aligned to GMT+01:00.
        """
        route_name = 'test-route-hourly'

        # Insert test data:
        # Event at 2026-01-01 00:30:00 GMT+01:00 (2025-12-31 23:30:00 UTC)
        events = [
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2025, 12, 31, 23, 30, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='gpt-4',
                cost=0.01,
            ),
            # Another event at 2026-01-01 01:30:00 GMT+01:00 (2026-01-01 00:30:00 UTC)
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 1, 0, 30, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=2000,
                model_id='gpt-4',
                cost=0.02,
            ),
        ]

        for event in events:
            self.insert([event])

        # Query with GMT+01:00 timezone
        _from = datetime.datetime.fromisoformat('2026-01-01T00:00:00+01:00')
        _to = datetime.datetime.fromisoformat('2026-01-01T03:00:00+01:00')

        result = self.event_service.get_costs_chart_data(
            None,
            route_names=[route_name],
            _from=_from,
            _to=_to,
            group_by='keys',
        )

        # Assertions
        assert result.granularity == 'hours'
        assert len(result.timestamp) > 0, 'Should have at least one bucket'
        assert len(result.data) > 0, 'Should have at least one series'

        # The total cost should be non-zero if data is matched correctly
        total_cost = sum(result.data[0].data)
        assert total_cost > 0, (
            f'Expected non-zero cost, got {total_cost}. Data not matched to buckets correctly!'
        )

    def test_weekly_buckets_with_gmt_minus_8(self):
        """Test weekly buckets with user in GMT-08:00 timezone (negative offset).

        Scenario: User in GMT-08:00 (US Pacific) requests data starting from a Thursday.
        Expected: Weekly bucket should start from the Monday of that week in GMT-08:00.
        """
        route_name = 'test-route-weekly-negative'

        # Insert test data:
        # Event at 2026-01-08 12:00:00 GMT-08:00 (2026-01-08 20:00:00 UTC - Thursday)
        events = [
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 8, 20, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='gpt-4',
                cost=0.01,
            ),
        ]

        for event in events:
            self.insert([event])

        # Query with GMT-08:00 timezone starting from Thursday Jan 8
        # Range must be >48 days for 'weeks' granularity
        _from = datetime.datetime.fromisoformat('2026-01-08T00:00:00-08:00')
        _to = datetime.datetime.fromisoformat('2026-03-08T00:00:00-08:00')

        result = self.event_service.get_costs_chart_data(
            None,
            route_names=[route_name],
            _from=_from,
            _to=_to,
            group_by='keys',
        )

        # Assertions
        assert result.granularity == 'weeks'
        assert len(result.timestamp) > 0, 'Should have at least one bucket'
        assert len(result.data) > 0, 'Should have at least one series'

        # The total cost should be non-zero if data is matched correctly
        total_cost = sum(result.data[0].data)
        assert total_cost > 0, (
            f'Expected non-zero cost, got {total_cost}. Data not matched to buckets correctly!'
        )

    def test_daily_buckets_with_gmt_minus_5(self):
        """Test daily buckets with user in GMT-05:00 timezone (negative offset).

        Scenario: User in GMT-05:00 (US Eastern) requests data.
        Expected: Daily buckets should be aligned to GMT-05:00 midnight.
        """
        route_name = 'test-route-daily-negative'

        # Insert test data:
        # Event at 2026-01-15 00:30:00 GMT-05:00 (2026-01-15 05:30:00 UTC)
        events = [
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 5, 30, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='gpt-4',
                cost=0.01,
            ),
        ]

        for event in events:
            self.insert([event])

        # Query with GMT-05:00 timezone
        # Range must be >48 hours for 'days' granularity
        _from = datetime.datetime.fromisoformat('2026-01-15T00:00:00-05:00')
        _to = datetime.datetime.fromisoformat('2026-01-18T00:00:00-05:00')

        result = self.event_service.get_costs_chart_data(
            None,
            route_names=[route_name],
            _from=_from,
            _to=_to,
            group_by='keys',
        )

        # Assertions
        assert result.granularity == 'days'
        assert len(result.timestamp) > 0, 'Should have at least one bucket'
        assert len(result.data) > 0, 'Should have at least one series'

        # The total cost should be non-zero if data is matched correctly
        total_cost = sum(result.data[0].data)
        assert total_cost > 0, (
            f'Expected non-zero cost, got {total_cost}. Data not matched to buckets correctly!'
        )

    def test_monthly_buckets_with_gmt_minus_5(self):
        """Test monthly buckets with user in GMT-05:00 timezone.

        Scenario: User in GMT-05:00 queries data across month boundary.
        Expected: Monthly buckets should be aligned to user's timezone.
        """
        route_name = 'test-route-monthly-negative'

        # Insert test data in January 2026 (UTC)
        events = [
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='gpt-4',
                cost=0.01,
            ),
            # More data in February 2026
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 2, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=2000,
                model_id='gpt-4',
                cost=0.02,
            ),
        ]

        for event in events:
            self.insert([event])

        # Query with GMT-05:00 timezone for January-February 2026
        # Range must be >336 days for 'months' granularity
        _from = datetime.datetime.fromisoformat('2025-01-01T00:00:00-05:00')
        _to = datetime.datetime.fromisoformat('2026-03-01T00:00:00-05:00')

        result = self.event_service.get_costs_chart_data(
            None,
            route_names=[route_name],
            _from=_from,
            _to=_to,
            group_by='keys',
        )

        # Assertions
        assert result.granularity == 'months'
        assert len(result.timestamp) > 0, 'Should have at least one bucket'
        assert len(result.data) > 0, 'Should have at least one series'

        # The total cost should be non-zero if data is matched correctly
        total_cost = sum(result.data[0].data)
        assert total_cost > 0, (
            f'Expected non-zero cost, got {total_cost}. Data not matched to buckets correctly!'
        )

    def test_monthly_buckets_long_range_gmt_plus_1(self):
        """Test monthly buckets with a long date range spanning multiple years.

        Scenario: User queries data from December 2024 to February 2026 with GMT+01:00.
        This reproduces the issue where buckets are generated correctly but all data values are 0.
        """
        route_name = 'test-route-long-range'

        # Insert test data at various points from December 2024 to February 2026
        events = [
            # December 2024 data (middle of the month)
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2024, 12, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='gpt-4',
                cost=0.01,
            ),
            # January 2025 data
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2025, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=2000,
                model_id='gpt-4',
                cost=0.02,
            ),
            # February 2025 data
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2025, 2, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=3000,
                model_id='gpt-4',
                cost=0.03,
            ),
            # March 2025 data
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2025, 3, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=4000,
                model_id='gpt-4',
                cost=0.04,
            ),
            # January 2026 data
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=5000,
                model_id='gpt-4',
                cost=0.05,
            ),
        ]

        for event in events:
            self.insert([event])

        # Query with GMT+01:00 timezone - same as the user's query
        _from = datetime.datetime.fromisoformat('2024-12-01T00:00:00+01:00')
        _to = datetime.datetime.fromisoformat('2026-02-27T22:00:00+01:00')

        result = self.event_service.get_costs_chart_data(
            None,
            route_names=[route_name],
            _from=_from,
            _to=_to,
            group_by='keys',
        )

        # Assertions
        assert result.granularity == 'months'
        assert len(result.timestamp) > 0, 'Should have at least one bucket'
        assert len(result.data) > 0, 'Should have at least one series'

        # The total cost should be non-zero if data is matched correctly
        total_cost = sum(result.data[0].data)
        assert total_cost > 0, (
            f'Expected non-zero cost, got {total_cost}. Data not matched to buckets correctly!'
        )

    # Token chart integration tests

    def test_token_chart_daily_buckets_with_gmt_plus_1(self):
        """Test token chart daily buckets with user in GMT+01:00 timezone.

        Scenario: User in GMT+01:00 requests token data for 2026-01-01 to 2026-01-02.
        Expected: Token data should be returned in daily buckets aligned to GMT+01:00,
        with separate INPUT and OUTPUT series.
        """
        route_name = 'test-route-tokens-daily'

        # Insert test data with INPUT_TOKEN_PROCESSED and OUTPUT_TOKEN_PROCESSED
        events = [
            # Input tokens at 2026-01-01 00:30:00 GMT+01:00 (2025-12-31 23:30:00 UTC)
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2025, 12, 31, 23, 30, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='gpt-4',
                cost=0.01,
            ),
            # Output tokens at same time
            get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2025, 12, 31, 23, 30, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=500,
                model_id='gpt-4',
                cost=0.015,
            ),
            # More input tokens on 2026-01-02 00:30:00 GMT+01:00 (2026-01-01 23:30:00 UTC)
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 1, 23, 30, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=2000,
                model_id='gpt-4',
                cost=0.02,
            ),
        ]

        for event in events:
            self.insert([event])

        # Query with GMT+01:00 timezone
        _from = datetime.datetime.fromisoformat('2026-01-01T00:00:00+01:00')
        _to = datetime.datetime.fromisoformat('2026-01-03T00:00:00+01:00')

        result = self.event_service.get_token_chart_data(
            None,
            route_names=[route_name],
            _from=_from,
            _to=_to,
            granularity='days',
        )

        # Assertions
        assert result.granularity == 'days'
        assert len(result.timestamp) > 0, 'Should have at least one bucket'
        assert len(result.data) == 2, 'Should have INPUT and OUTPUT series'
        assert result.data[0].name == 'INPUT'
        assert result.data[1].name == 'OUTPUT'
        assert result.total > 0, 'Total tokens should be non-zero'

    def test_token_chart_hourly_buckets_with_gmt_plus_1(self):
        """Test token chart hourly buckets with user in GMT+01:00 timezone.

        Scenario: User in GMT+01:00 requests token data for a specific hour.
        Expected: Token data should be returned in hourly buckets with INPUT/OUTPUT series.
        """
        route_name = 'test-route-tokens-hourly'

        events = [
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2025, 12, 31, 23, 30, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='gpt-4',
                cost=0.01,
            ),
            get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 1, 0, 30, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=500,
                model_id='gpt-4',
                cost=0.015,
            ),
        ]

        for event in events:
            self.insert([event])

        _from = datetime.datetime.fromisoformat('2026-01-01T00:00:00+01:00')
        _to = datetime.datetime.fromisoformat('2026-01-01T03:00:00+01:00')

        result = self.event_service.get_token_chart_data(
            None,
            route_names=[route_name],
            _from=_from,
            _to=_to,
            granularity='hours',
        )

        assert result.granularity == 'hours'
        assert len(result.timestamp) > 0, 'Should have at least one bucket'
        assert len(result.data) == 2, 'Should have INPUT and OUTPUT series'
        assert result.total > 0, 'Total tokens should be non-zero'

    def test_token_chart_monthly_buckets_with_gmt_minus_5(self):
        """Test token chart monthly buckets with user in GMT-05:00 timezone.

        Scenario: User in GMT-05:00 queries token data across month boundary.
        Expected: Monthly token buckets with INPUT/OUTPUT series aligned to user's timezone.
        """
        route_name = 'test-route-tokens-monthly'

        events = [
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1500,
                model_id='gpt-4',
                cost=0.015,
            ),
            get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=750,
                model_id='gpt-4',
                cost=0.0225,
            ),
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 2, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=3000,
                model_id='gpt-4',
                cost=0.03,
            ),
        ]

        for event in events:
            self.insert([event])

        _from = datetime.datetime.fromisoformat('2026-01-01T00:00:00-05:00')
        _to = datetime.datetime.fromisoformat('2026-03-01T00:00:00-05:00')

        result = self.event_service.get_token_chart_data(
            None,
            route_names=[route_name],
            _from=_from,
            _to=_to,
            granularity='months',
        )

        assert result.granularity == 'months'
        assert len(result.timestamp) > 0, 'Should have at least one bucket'
        assert len(result.data) == 2, 'Should have INPUT and OUTPUT series'
        assert result.total == 5250, 'Total tokens should be sum of all input + output'

    def test_token_chart_weekly_buckets_with_gmt_minus_8(self):
        """Test token chart weekly buckets with user in GMT-08:00 timezone.

        Scenario: User in GMT-08:00 requests token data starting from a Thursday.
        Expected: Weekly token buckets should start from Monday of that week.
        """
        route_name = 'test-route-tokens-weekly'

        events = [
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 8, 20, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=2500,
                model_id='gpt-4',
                cost=0.025,
            ),
        ]

        for event in events:
            self.insert([event])

        _from = datetime.datetime.fromisoformat('2026-01-08T00:00:00-08:00')
        _to = datetime.datetime.fromisoformat('2026-01-22T00:00:00-08:00')

        result = self.event_service.get_token_chart_data(
            None,
            route_names=[route_name],
            _from=_from,
            _to=_to,
            granularity='weeks',
        )

        assert result.granularity == 'weeks'
        assert len(result.timestamp) > 0, 'Should have at least one bucket'
        assert len(result.data) == 2, 'Should have INPUT and OUTPUT series'
        assert result.total == 2500, 'Total tokens should match input'

    def test_token_chart_empty_result(self):
        """Test token chart with no data in the time range.

        Scenario: User queries token data for a time range with no events.
        Expected: Should return empty data structure with total=0.
        """
        route_name = 'test-route-tokens-empty'

        # No events inserted

        _from = datetime.datetime.fromisoformat('2026-01-01T00:00:00+01:00')
        _to = datetime.datetime.fromisoformat('2026-01-03T00:00:00+01:00')

        result = self.event_service.get_token_chart_data(
            None,
            route_names=[route_name],
            _from=_from,
            _to=_to,
            granularity='days',
        )

        assert result.granularity == 'days'
        assert result.total == 0, 'Total tokens should be 0 for empty result'
        assert len(result.timestamp) == 0, 'Should have no timestamps'
        assert len(result.data) == 0, 'Should have no data series'

    def test_token_chart_long_range_months(self):
        """Test token chart with a long date range spanning multiple months.

        Scenario: User queries token data from December 2024 to February 2026.
        Expected: Monthly token buckets with correct total calculation.
        """
        route_name = 'test-route-tokens-long'

        events = [
            # December 2024
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2024, 12, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=1000,
                model_id='gpt-4',
                cost=0.01,
            ),
            # January 2025
            get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2025, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=2000,
                model_id='gpt-4',
                cost=0.02,
            ),
            # February 2026
            get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 2, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                value=3000,
                model_id='gpt-4',
                cost=0.03,
            ),
        ]

        for event in events:
            self.insert([event])

        _from = datetime.datetime.fromisoformat('2024-12-01T00:00:00+01:00')
        _to = datetime.datetime.fromisoformat('2026-02-27T22:00:00+01:00')

        result = self.event_service.get_token_chart_data(
            None,
            route_names=[route_name],
            _from=_from,
            _to=_to,
            granularity='months',
        )

        assert result.granularity == 'months'
        assert len(result.timestamp) > 0, 'Should have at least one bucket'
        assert len(result.data) == 2, 'Should have INPUT and OUTPUT series'
        assert result.total == 6000, 'Total tokens should be sum of all events'

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

    # Request chart integration tests

    def test_request_chart_daily_buckets_with_gmt_plus_1(self):
        """Test request chart daily buckets with user in GMT+01:00 timezone.

        Scenario: User in GMT+01:00 requests request count data for 2026-01-01 to 2026-01-02.
        Expected: Request counts should be returned in daily buckets aligned to GMT+01:00.
        """
        route_name = 'test-route-requests-daily'

        # Insert test data with request events (each represents one request)
        events = [
            # Request at 2026-01-01 00:30:00 GMT+01:00 (2025-12-31 23:30:00 UTC)
            get_sample_request_event(
                route_name=route_name,
                timestamp=datetime.datetime(
                    2025, 12, 31, 23, 30, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
            ),
            # Another request at same time
            get_sample_request_event(
                route_name=route_name,
                timestamp=datetime.datetime(
                    2025, 12, 31, 23, 45, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
            ),
            # More requests on 2026-01-02 00:30:00 GMT+01:00 (2026-01-01 23:30:00 UTC)
            get_sample_request_event(
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 1, 23, 30, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
            ),
        ]

        for event in events:
            self.insert([event])

        # Query with GMT+01:00 timezone
        _from = datetime.datetime.fromisoformat('2026-01-01T00:00:00+01:00')
        _to = datetime.datetime.fromisoformat('2026-01-03T00:00:00+01:00')

        result = self.request_event_service.get_request_chart_data(
            None,
            route_name=route_name,
            _from=_from,
            _to=_to,
            granularity='days',
        )

        # Assertions
        assert result.granularity == 'days'
        assert len(result.timestamp) > 0, 'Should have at least one bucket'
        assert result.total == 3, 'Total requests should be 3'
        assert sum(result.data) == 3, 'Sum of bucket data should equal total'

    def test_request_chart_hourly_buckets_with_gmt_plus_1(self):
        """Test request chart hourly buckets with user in GMT+01:00 timezone.

        Scenario: User in GMT+01:00 requests request count data for a specific hour.
        Expected: Request counts should be returned in hourly buckets aligned to GMT+01:00.
        """
        route_name = 'test-route-requests-hourly'

        events = [
            get_sample_request_event(
                route_name=route_name,
                timestamp=datetime.datetime(
                    2025, 12, 31, 23, 30, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
            ),
            get_sample_request_event(
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 1, 0, 30, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
            ),
        ]

        for event in events:
            self.insert([event])

        _from = datetime.datetime.fromisoformat('2026-01-01T00:00:00+01:00')
        _to = datetime.datetime.fromisoformat('2026-01-01T03:00:00+01:00')

        result = self.request_event_service.get_request_chart_data(
            None,
            route_name=route_name,
            _from=_from,
            _to=_to,
            granularity='hours',
        )

        assert result.granularity == 'hours'
        assert len(result.timestamp) > 0, 'Should have at least one bucket'
        assert result.total == 2, 'Total requests should be 2'

    def test_request_chart_monthly_buckets_with_gmt_minus_5(self):
        """Test request chart monthly buckets with user in GMT-05:00 timezone.

        Scenario: User in GMT-05:00 queries request count data across month boundary.
        Expected: Monthly request buckets aligned to user's timezone.
        """
        route_name = 'test-route-requests-monthly'

        events = [
            get_sample_request_event(
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
            ),
            get_sample_request_event(
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 2, 15, 12, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
            ),
        ]

        for event in events:
            self.insert([event])

        _from = datetime.datetime.fromisoformat('2026-01-01T00:00:00-05:00')
        _to = datetime.datetime.fromisoformat('2026-03-01T00:00:00-05:00')

        result = self.request_event_service.get_request_chart_data(
            None,
            route_name=route_name,
            _from=_from,
            _to=_to,
            granularity='months',
        )

        assert result.granularity == 'months'
        assert len(result.timestamp) > 0, 'Should have at least one bucket'
        assert result.total == 2, 'Total requests should be 2'

    def test_request_chart_weekly_buckets_with_gmt_minus_8(self):
        """Test request chart weekly buckets with user in GMT-08:00 timezone.

        Scenario: User in GMT-08:00 requests request count data starting from a Thursday.
        Expected: Weekly request buckets should start from Monday of that week.
        """
        route_name = 'test-route-requests-weekly'

        events = [
            get_sample_request_event(
                route_name=route_name,
                timestamp=datetime.datetime(
                    2026, 1, 8, 20, 0, 0, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
            ),
        ]

        for event in events:
            self.insert([event])

        _from = datetime.datetime.fromisoformat('2026-01-08T00:00:00-08:00')
        _to = datetime.datetime.fromisoformat('2026-01-22T00:00:00-08:00')

        result = self.request_event_service.get_request_chart_data(
            None,
            route_name=route_name,
            _from=_from,
            _to=_to,
            granularity='weeks',
        )

        assert result.granularity == 'weeks'
        assert len(result.timestamp) > 0, 'Should have at least one bucket'
        assert result.total == 1, 'Total requests should be 1'
