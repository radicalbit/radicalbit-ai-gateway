import datetime
import uuid

from tests.common import db_mock
from tests.common.db_integration_ch import DatabaseIntegrationClickhouse

from radicalbit_ai_gateway.db.dao.event_dao import EventDAO
from radicalbit_ai_gateway.db.models.event import (
    Counters,
    LastEventFallback,
    LastEventGuardrail,
    MostExpensiveChartData,
    MostExpensiveRoute,
    TokensCounter,
)


class EventDAOTest(DatabaseIntegrationClickhouse):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.event_dao = EventDAO(cls.db)

    def _insert_test_data(self):
        to_insert = [
            db_mock.get_sample_event(
                event_type='GUARDRAIL',
                route_name='route-A',
                timestamp=datetime.datetime(
                    2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=0),
                name='PRESIDIO',
                type='READACT',
                where='INPUT',
                parameters='PARAMS',
                behavior='BLOCK',
            ),
            db_mock.get_sample_event(
                event_type='GUARDRAIL',
                route_name='route-B',
                timestamp=datetime.datetime(
                    2025, 10, 12, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=0),
            ),
            db_mock.get_sample_event(
                event_type='FALLBACK',
                route_name='route-A',
                timestamp=datetime.datetime(
                    2025, 10, 13, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=0),
            ),
            db_mock.get_sample_event(
                event_type='FALLBACK',
                route_name='route-A',
                timestamp=datetime.datetime(
                    2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=0),
                target='gpt-4.1',
                fallback='llama3.1',
            ),
            db_mock.get_sample_event(
                event_type='FALLBACK',
                route_name='route-B',
                timestamp=datetime.datetime(
                    2025, 10, 12, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=0),
            ),
            db_mock.get_sample_event(
                event_type='RATE_LIMIT',
                route_name='route-A',
                timestamp=datetime.datetime(
                    2025, 10, 13, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=0),
            ),
            db_mock.get_sample_event(
                event_type='RATE_LIMIT',
                route_name='route-B',
                timestamp=datetime.datetime(
                    2025, 10, 12, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=0),
            ),
            db_mock.get_sample_event(
                event_type='CACHE_HIT',
                route_name='route-A',
                timestamp=datetime.datetime(
                    2025, 10, 13, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                api_key_uuid=uuid.UUID(int=0),
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-A',
                value=100,
                model_id='model-A',
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-A',
                value=150,
                model_id='model-A',
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-B',
                value=150,
                model_id='model-A',
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-A',
                value=75,
                model_id='model-B',
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-A',
                value=75,
                model_id='model-B',
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-B',
                value=75,
                model_id='model-B',
            ),
            db_mock.get_sample_event(
                route_name='route-A',
                event_type='CACHE_INPUT_TOKENS',
                value=2,
                model_id='model-A',
            ),
            db_mock.get_sample_event(
                route_name='route-A',
                event_type='CACHE_INPUT_TOKENS',
                value=45,
                model_id='model-A',
            ),
            db_mock.get_sample_event(
                route_name='route-A',
                event_type='CACHE_OUTPUT_TOKENS',
                value=60,
                model_id='model-B',
            ),
            db_mock.get_sample_event(
                route_name='route-B',
                event_type='CACHE_INPUT_TOKENS',
                value=2,
                model_id='model-A',
            ),
            db_mock.get_sample_event(
                route_name='route-B',
                event_type='CACHE_INPUT_TOKENS',
                value=45,
                model_id='model-A',
            ),
            db_mock.get_sample_event(
                route_name='route-B',
                event_type='CACHE_OUTPUT_TOKENS',
                value=60,
                model_id='model-B',
            ),
        ]
        self.insert(to_insert)

    def setUp(self):
        self._insert_test_data()

    def tearDown(self) -> None:
        return super().tearDown()

    def test_get_all_counters(self):
        res = self.event_dao.get_all_counters(None, None, None)
        assert res is not None
        assert res == Counters(
            guardrail_value=2,
            fallback_value=3,
            rate_limit_triggered=2,
            token_input_limit_triggered=0,
            token_output_limit_triggered=0,
            cache_triggered=1,
        )

    def test_get_last_event_guardrail(self):
        res = self.event_dao.get_last_event(
            None, event_type='GUARDRAIL', _from=None, _to=None
        )
        assert res is not None
        assert res == LastEventGuardrail(
            route_name='route-A',
            name='PRESIDIO',
            where='INPUT',
            type='READACT',
            behavior='BLOCK',
            timestamp=datetime.datetime(
                2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
            ),
            api_key_uuid=uuid.UUID('00000000-0000-0000-0000-000000000000'),
            api_key_name='fake',
        )

    def test_get_last_event_fallback(self):
        res = self.event_dao.get_last_event(
            None, event_type='FALLBACK', _from=None, _to=None
        )
        assert res is not None
        assert res == LastEventFallback(
            route_name='route-A',
            target='gpt-4.1',
            fallback='llama3.1',
            timestamp=datetime.datetime(
                2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
            ),
            api_key_uuid=uuid.UUID('00000000-0000-0000-0000-000000000000'),
            api_key_name='fake',
        )

    def test_get_tokens_by_model(self):
        res = self.event_dao.get_tokens_by_model(None, None, None)
        expected = [
            TokensCounter(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-A',
                model_id='model-B',
                value=150,
            ),
            TokensCounter(
                event_type='CACHE_INPUT_TOKENS',
                route_name='route-A',
                model_id='model-A',
                value=47,
            ),
            TokensCounter(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-A',
                model_id='model-A',
                value=250,
            ),
            TokensCounter(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-B',
                model_id='model-A',
                value=150,
            ),
            TokensCounter(
                event_type='CACHE_OUTPUT_TOKENS',
                route_name='route-A',
                model_id='model-B',
                value=60,
            ),
            TokensCounter(
                event_type='CACHE_OUTPUT_TOKENS',
                route_name='route-B',
                model_id='model-B',
                value=60,
            ),
            TokensCounter(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-B',
                model_id='model-B',
                value=75,
            ),
            TokensCounter(
                event_type='CACHE_INPUT_TOKENS',
                route_name='route-B',
                model_id='model-A',
                value=47,
            ),
        ]
        assert res is not None
        sort_key = lambda x: (x.event_type, x.route_name, x.model_id, x.value)
        assert sorted(res, key=sort_key) == sorted(expected, key=sort_key)

    def test_get_tokens_by_model_per_route(self):
        res = self.event_dao.get_tokens_by_model_per_route(None, 'route-A', None, None)
        expected = [
            TokensCounter(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-A',
                model_id='model-B',
                value=150,
            ),
            TokensCounter(
                event_type='CACHE_INPUT_TOKENS',
                route_name='route-A',
                model_id='model-A',
                value=47,
            ),
            TokensCounter(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-A',
                model_id='model-A',
                value=250,
            ),
            TokensCounter(
                event_type='CACHE_OUTPUT_TOKENS',
                route_name='route-A',
                model_id='model-B',
                value=60,
            ),
        ]
        sort_key = lambda x: (x.event_type, x.route_name, x.model_id, x.value)
        assert res is not None
        assert sorted(res, key=sort_key) == sorted(expected, key=sort_key)

    def test_get_all_counters_per_route(self):
        res = self.event_dao.get_all_counters_by_route(
            None, route_name='route-A', _from=None, _to=None
        )
        assert res is not None
        assert res == Counters(
            guardrail_value=1,
            fallback_value=2,
            rate_limit_triggered=1,
            token_input_limit_triggered=0,
            token_output_limit_triggered=0,
            cache_triggered=1,
        )

    def test_get_last_event_guardrail_per_route(self):
        res = self.event_dao.get_last_event_route(
            None, event_type='GUARDRAIL', route_name='route-A', _from=None, _to=None
        )
        assert res is not None
        assert res == LastEventGuardrail(
            route_name='route-A',
            timestamp=datetime.datetime(
                2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
            ),
            api_key_uuid=uuid.UUID(int=0),
            name='PRESIDIO',
            type='READACT',
            where='INPUT',
            behavior='BLOCK',
            api_key_name='fake',
        )

    def test_get_last_event_fallback_per_route(self):
        res = self.event_dao.get_last_event_route(
            None, event_type='FALLBACK', route_name='route-A', _from=None, _to=None
        )
        assert res is not None
        assert res == LastEventFallback(
            route_name='route-A',
            timestamp=datetime.datetime(
                2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
            ),
            api_key_uuid=uuid.UUID(int=0),
            target='gpt-4.1',
            fallback='llama3.1',
            api_key_name='fake',
        )

    def test_get_latest_n_per_event_type(self):
        _to = datetime.datetime(
            2025, 10, 14, 13, 58, 36, 931873, tzinfo=datetime.timezone.utc
        )
        _from = datetime.datetime(
            2025, 10, 13, 11, 58, 36, 931873, tzinfo=datetime.timezone.utc
        )
        res = self.event_dao.get_latest_n_per_event_type(
            None, 'route-A', 10, _from, _to
        )
        assert res is not None
        assert len(res) == 5
        assert res == [
            db_mock.get_event_detail(
                timestamp=datetime.datetime(
                    2025, 10, 13, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                route_name='route-A',
                event_type='CACHE_HIT',
                api_key_name='fake',
            ),
            db_mock.get_event_detail(
                timestamp=datetime.datetime(
                    2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                route_name='route-A',
                event_type='FALLBACK',
                target='gpt-4.1',
                fallback='llama3.1',
                api_key_name='fake',
            ),
            db_mock.get_event_detail(
                timestamp=datetime.datetime(
                    2025, 10, 13, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                route_name='route-A',
                event_type='FALLBACK',
                api_key_name='fake',
            ),
            db_mock.get_event_detail(
                timestamp=datetime.datetime(
                    2025, 10, 14, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                route_name='route-A',
                event_type='GUARDRAIL',
                name='PRESIDIO',
                type='READACT',
                where='INPUT',
                parameters='PARAMS',
                behavior='BLOCK',
                api_key_name='fake',
            ),
            db_mock.get_event_detail(
                timestamp=datetime.datetime(
                    2025, 10, 13, 12, 58, 36, 931873, tzinfo=datetime.timezone.utc
                ),
                route_name='route-A',
                event_type='RATE_LIMIT',
                api_key_name='fake',
            ),
        ]

    def test_get_latest_n_per_event_type_empty(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        _from = now + datetime.timedelta(hours=1)
        res = self.event_dao.get_latest_n_per_event_type(
            None, 'route-A', 10, _from, now
        )
        assert res == []

    def test_get_latest_n_per_event_type_wrong_route_name(self):
        _to = datetime.datetime(
            2025, 10, 14, 13, 58, 36, 931873, tzinfo=datetime.timezone.utc
        )
        _from = datetime.datetime(
            2025, 10, 13, 11, 58, 36, 931873, tzinfo=datetime.timezone.utc
        )
        res = self.event_dao.get_latest_n_per_event_type(
            None, 'route-C', 10, _from, _to
        )
        assert res == []

    def test_get_chart_data_hourly_granularity_by_api_key(self):
        api_key_1 = uuid.UUID(int=1)
        api_key_2 = uuid.UUID(int=2)
        base_time = datetime.datetime(
            2025, 1, 8, 10, 30, 45, tzinfo=datetime.timezone.utc
        )

        test_events = [
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,  # 10:30
                api_key_uuid=api_key_1,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.0005,
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(minutes=30),  # 11:00
                api_key_uuid=api_key_1,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.000010,
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=1),  # 11:30
                api_key_uuid=api_key_2,
                api_key_name='key-2',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.0003,
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=1, minutes=15),  # 11:45
                api_key_uuid=api_key_2,
                api_key_name='key-2',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.0000007,
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=3, minutes=30),
                api_key_uuid=api_key_2,
                api_key_name='key-2',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.025,
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=3, minutes=45),
                api_key_uuid=api_key_2,
                api_key_name='key-2',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.000006,
            ),
        ]
        self.insert(test_events)
        _from = base_time - datetime.timedelta(hours=2)
        _to = _from + datetime.timedelta(hours=12)

        res = self.event_dao.get_costs_chart_data(
            None, ['rb-gateway'], _from, _to, 'hours', 'keys'
        )
        assert res is not None
        assert len(res) == 4
        assert res[0].bucket == datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        assert res[0].group_by_value == str(api_key_1)
        assert res[0].total_cost == 0.0005

        assert res[1].bucket == datetime.datetime(
            2025, 1, 8, 11, 0, 0, tzinfo=datetime.timezone.utc
        )
        assert res[1].group_by_value == str(api_key_1)
        assert res[1].total_cost == 0.000010

        assert res[2].bucket == datetime.datetime(
            2025, 1, 8, 11, 0, 0, tzinfo=datetime.timezone.utc
        )
        assert res[2].group_by_value == str(api_key_2)
        assert res[2].total_cost == 0.0003007

        assert res[3].bucket == datetime.datetime(
            2025, 1, 8, 14, 0, 0, tzinfo=datetime.timezone.utc
        )
        assert res[3].group_by_value == str(api_key_2)
        assert res[3].total_cost == 0.025006

    def test_get_chart_data_hourly_granularity_by_group_name(self):
        group_1_uuid = uuid.UUID(int=1)
        group_2_uuid = uuid.UUID(int=2)
        base_time = datetime.datetime(
            2025, 1, 8, 14, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_events = [
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                group_uuid=group_1_uuid,
                group_name='group-1',
                cost=0.20,
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(minutes=45),
                api_key_uuid=uuid.UUID(int=2),
                api_key_name='key-2',
                group_uuid=group_2_uuid,
                group_name='group-2',
                cost=0.15,
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=1),
                api_key_uuid=uuid.UUID(int=3),
                api_key_name='key-3',
                group_uuid=group_1_uuid,
                group_name='group-1',
                cost=0.12,
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=2)

        res = self.event_dao.get_costs_chart_data(
            None, ['rb-gateway'], _from, _to, 'hours', 'groups'
        )

        assert res is not None
        assert len(res) == 3
        assert res[0].bucket == base_time
        assert res[0].group_by_value == str(group_1_uuid)
        assert res[0].total_cost == 0.20

        assert res[1].bucket == base_time
        assert res[1].group_by_value == str(group_2_uuid)
        assert res[1].total_cost == 0.15

        assert res[2].bucket == base_time + datetime.timedelta(hours=1)
        assert res[2].group_by_value == str(group_1_uuid)
        assert res[2].total_cost == 0.12

    def test_get_chart_data_daily_granularity_by_api_key(self):
        api_key_1 = uuid.UUID(int=1)
        api_key_2 = uuid.UUID(int=2)
        base_time = datetime.datetime(2025, 1, 8, 0, 0, 0, tzinfo=datetime.timezone.utc)

        test_events = [
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=5),
                api_key_uuid=api_key_1,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=1.50,
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=18),
                api_key_uuid=api_key_1,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=2.25,
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(days=1, hours=8),
                api_key_uuid=api_key_2,
                api_key_name='key-2',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.80,
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(days=3)

        res = self.event_dao.get_costs_chart_data(
            None, ['rb-gateway'], _from, _to, 'days', 'keys'
        )

        assert res is not None
        assert len(res) == 2
        assert res[0].bucket == base_time
        assert res[0].group_by_value == str(api_key_1)
        assert res[0].total_cost == 3.75

        assert res[1].bucket == base_time + datetime.timedelta(days=1)
        assert res[1].group_by_value == str(api_key_2)
        assert res[1].total_cost == 0.80

    def test_get_chart_data_weekly_granularity_by_group_name(self):
        group_1_uuid = uuid.UUID(int=1)
        group_2_uuid = uuid.UUID(int=2)
        base_time = datetime.datetime(2025, 1, 6, 0, 0, 0, tzinfo=datetime.timezone.utc)

        test_events = [
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(days=1),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                group_uuid=group_1_uuid,
                group_name='group-1',
                cost=10.50,
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(days=3),
                api_key_uuid=uuid.UUID(int=2),
                api_key_name='key-2',
                group_uuid=group_2_uuid,
                group_name='group-2',
                cost=8.75,
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(days=8),
                api_key_uuid=uuid.UUID(int=3),
                api_key_name='key-3',
                group_uuid=group_1_uuid,
                group_name='group-1',
                cost=12.00,
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(days=60)

        res = self.event_dao.get_costs_chart_data(
            None, ['rb-gateway'], _from, _to, 'weeks', 'groups'
        )
        assert res is not None
        assert len(res) == 3
        assert res[0].group_by_value == str(group_1_uuid)
        assert res[0].total_cost == 10.50

        assert res[1].group_by_value == str(group_2_uuid)
        assert res[1].total_cost == 8.75

        assert res[2].group_by_value == str(group_1_uuid)
        assert res[2].total_cost == 12.00

    def test_get_chart_data_monthly_granularity_by_api_key(self):
        base_time = datetime.datetime(
            2025, 1, 15, 0, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_events = [
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=10.50,
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(days=40),
                api_key_uuid=uuid.UUID(int=2),
                api_key_name='key-2',
                group_uuid=uuid.UUID(int=2),
                group_name='group-2',
                cost=8.75,
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(days=70),
                api_key_uuid=uuid.UUID(int=3),
                api_key_name='key-3',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=12.00,
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(days=400)

        res = self.event_dao.get_costs_chart_data(
            None, ['rb-gateway'], _from, _to, 'months', 'keys'
        )
        assert res is not None
        assert len(res) == 3
        assert res[0].group_by_value == str(uuid.UUID(int=1))
        assert res[0].total_cost == 10.50

        assert res[1].group_by_value == str(uuid.UUID(int=2))
        assert res[1].total_cost == 8.75

        assert res[2].group_by_value == str(uuid.UUID(int=3))
        assert res[2].total_cost == 12.00

    def test_get_chart_data_empty_result(self):
        base_time = datetime.datetime(2025, 1, 8, 0, 0, 0, tzinfo=datetime.timezone.utc)

        _from = base_time + datetime.timedelta(days=100)
        _to = base_time + datetime.timedelta(days=101)

        res = self.event_dao.get_costs_chart_data(
            None, ['rb-gateway'], _from, _to, 'hours', 'keys'
        )

        assert res is not None
        assert len(res) == 0

    def test_get_chart_data_filters_by_time_range(self):
        """Test that only data within _from and _to range is returned."""
        api_key_1 = uuid.UUID(int=1)
        base_time = datetime.datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_events = [
            # Event BEFORE the range (should NOT be included)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time - datetime.timedelta(hours=2),  # 10:00
                api_key_uuid=api_key_1,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.10,
            ),
            # Event AT the start of the range (should be included)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,  # 12:00
                api_key_uuid=api_key_1,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.20,
            ),
            # Event INSIDE the range (should be included)
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=1),  # 13:00
                api_key_uuid=api_key_1,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.30,
            ),
            # Event AT the end of the range (should be included)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=2),  # 14:00
                api_key_uuid=api_key_1,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.40,
            ),
            # Event AFTER the range (should NOT be included)
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=3),  # 15:00
                api_key_uuid=api_key_1,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.50,
            ),
        ]
        self.insert(test_events)

        _from = base_time  # 12:00
        _to = base_time + datetime.timedelta(hours=2)  # 14:00

        res = self.event_dao.get_costs_chart_data(
            None, ['rb-gateway'], _from, _to, 'hours', 'keys'
        )

        assert res is not None
        # Should have 3 buckets: 12:00, 13:00, 14:00
        assert len(res) == 3

        for point in res:
            assert point.bucket >= base_time, (
                f'Bucket {point.bucket} is before _from {base_time}'
            )
            assert point.bucket <= _to, f'Bucket {point.bucket} is after _to {_to}'

        total_cost = sum(point.total_cost for point in res)
        assert total_cost == 0.90, f'Expected total cost 0.90, got {total_cost}'

    def test_get_chart_data_no_route_filter(self):
        """route_names=None returns data from all routes, aggregated per bucket and group_by."""
        api_key_1 = uuid.UUID(int=1)
        base_time = datetime.datetime(
            2025, 2, 1, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_events = [
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                api_key_uuid=api_key_1,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=1.0,
                route_name='route-X',
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                api_key_uuid=api_key_1,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=2.0,
                route_name='route-Y',
            ),
        ]
        self.insert(test_events)
        _from = base_time - datetime.timedelta(hours=1)
        _to = base_time + datetime.timedelta(hours=1)

        res = self.event_dao.get_costs_chart_data(
            None, None, _from, _to, 'hours', 'keys'
        )

        assert res is not None
        # Both events share the same bucket and api_key — aggregated into 1 row
        assert len(res) == 1
        assert res[0].group_by_value == str(api_key_1)
        assert res[0].total_cost == 3.0

    def test_get_chart_data_filters_by_multiple_routes(self):
        """route_names=['route-A', 'route-B'] includes both routes and excludes others."""
        api_key_1 = uuid.UUID(int=1)
        base_time = datetime.datetime(
            2025, 2, 2, 10, 0, 0, tzinfo=datetime.timezone.utc
        )

        test_events = [
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                api_key_uuid=api_key_1,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=1.0,
                route_name='route-A',
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                api_key_uuid=api_key_1,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=2.0,
                route_name='route-B',
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                api_key_uuid=api_key_1,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=5.0,
                route_name='route-C',
            ),
        ]
        self.insert(test_events)
        _from = base_time - datetime.timedelta(hours=1)
        _to = base_time + datetime.timedelta(hours=1)

        res = self.event_dao.get_costs_chart_data(
            None, ['route-A', 'route-B'], _from, _to, 'hours', 'keys'
        )

        assert res is not None
        # route-A (1.0) and route-B (2.0) aggregated into 1 row; route-C (5.0) excluded
        assert len(res) == 1
        assert res[0].group_by_value == str(api_key_1)
        assert res[0].total_cost == 3.0

    def test_summary_cost(self):
        base_time = datetime.datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            # Event BEFORE the range (should NOT be included)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time - datetime.timedelta(hours=2),  # 10:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.10,
            ),
            # Event AT the start of the range (should be included)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,  # 12:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.20,
            ),
            # Event INSIDE the range (should be included)
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=1),  # 13:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.30,
            ),
            db_mock.get_sample_event(
                event_type='CACHE_HIT',
                timestamp=base_time + datetime.timedelta(hours=1),  # 14:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
            ),
            db_mock.get_sample_event(
                event_type='CACHE_HIT',
                timestamp=base_time + datetime.timedelta(hours=1),  # 14:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
            ),
            # Event AT the end of the range (should be included)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=2),  # 14:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.40,
            ),
            # Event AFTER the range (should NOT be included)
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=3),  # 15:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.50,
            ),
        ]
        self.insert(test_events)

        _from = base_time  # 12:00
        _to = base_time + datetime.timedelta(hours=2)  # 14:00

        res = self.event_dao.get_summary_costs(
            None, ['rb-gateway'], _from, _to, False, False
        )
        assert res is not None
        assert res.input_cost == 0.60
        assert res.output_cost == 0.30
        assert res.total_cost == 0.90
        assert res.cache_triggered is None
        assert res.cache_saved_tokens_input is None
        assert res.cache_saved_tokens_output is None
        assert res.saved_amount_input is None
        assert res.saved_amount_output is None

    def test_summary_cost_only_semantic(self):
        base_time = datetime.datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=1),
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.50,
                cache_type='semantic',
            ),
        ]
        self.insert(test_events)

        _from = base_time  # 12:00
        _to = base_time + datetime.timedelta(hours=2)  # 14:00

        res = self.event_dao.get_summary_costs(
            None, ['rb-gateway'], _from, _to, False, False
        )
        assert res is not None
        assert res.input_cost == 0
        assert res.output_cost == 0
        assert res.total_cost == 0
        assert res.cache_triggered is None
        assert res.cache_saved_tokens_input is None
        assert res.cache_saved_tokens_output is None
        assert res.saved_amount_input is None
        assert res.saved_amount_output is None

    def test_summary_cost_with_cache_and_tokens(self):
        base_time = datetime.datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            # Event BEFORE the range (should NOT be included)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time - datetime.timedelta(hours=2),  # 10:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.10,
            ),
            db_mock.get_sample_event(
                event_type='CACHE_INPUT_TOKENS',
                timestamp=base_time - datetime.timedelta(hours=2),  # 10:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.10,
            ),
            # Event AT the start of the range (should be included)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,  # 12:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.20,
            ),
            db_mock.get_sample_event(
                event_type='CACHE_INPUT_TOKENS',
                timestamp=base_time,  # 12:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.15,
                value=40,
            ),
            # Event INSIDE the range (should be included)
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=1),  # 13:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.30,
            ),
            db_mock.get_sample_event(
                event_type='CACHE_OUTPUT_TOKENS',
                timestamp=base_time + datetime.timedelta(hours=1),  # 13:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.40,
                value=100,
            ),
            db_mock.get_sample_event(
                event_type='CACHE_HIT',
                timestamp=base_time + datetime.timedelta(hours=1),  # 13:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
            ),
            db_mock.get_sample_event(
                event_type='CACHE_HIT',
                timestamp=base_time + datetime.timedelta(hours=2),  # 14:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
            ),
            # Event AT the end of the range (should be included)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=2),  # 14:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.40,
            ),
            db_mock.get_sample_event(
                event_type='CACHE_INPUT_TOKENS',
                timestamp=base_time + datetime.timedelta(hours=2),  # 14:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.10,
                value=3,
            ),
            # Event AFTER the range (should NOT be included)
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=3),  # 15:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.50,
            ),
            db_mock.get_sample_event(
                event_type='CACHE_OUTPUT_TOKENS',
                timestamp=base_time + datetime.timedelta(hours=3),  # 15:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.50,
                value=1000,
            ),
        ]
        self.insert(test_events)

        _from = base_time  # 12:00
        _to = base_time + datetime.timedelta(hours=2)  # 14:00

        res = self.event_dao.get_summary_costs(
            None, ['rb-gateway'], _from, _to, True, True
        )
        assert res is not None
        assert res.input_cost == 0.60
        assert res.output_cost == 0.30
        assert res.total_cost == 0.90
        assert res.cache_triggered == 2
        assert res.cache_saved_tokens_input == 43
        assert res.cache_saved_tokens_output == 100
        assert res.saved_amount_input == 0.25
        assert res.saved_amount_output == 0.40

    def test_get_semantic_cache_details(self):
        base_time = datetime.datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=1),
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.10,
                value=40,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                event_type='CACHE_HIT',
                timestamp=base_time,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=1),
                event_type='CACHE_INPUT_TOKENS',
                timestamp=base_time,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.10,
                value=40,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=1),
                event_type='CACHE_OUTPUT_TOKENS',
                timestamp=base_time,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.40,
                value=160,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=2),
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=1),  # 13:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.20,
                value=80,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                event_type='CACHE_HIT',
                timestamp=base_time + datetime.timedelta(hours=1),
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=2),
                event_type='CACHE_INPUT_TOKENS',
                timestamp=base_time + datetime.timedelta(hours=1),  # 13:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.20,
                value=80,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=2),
                event_type='CACHE_OUTPUT_TOKENS',
                timestamp=base_time + datetime.timedelta(hours=1),  # 13:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.60,
                value=240,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                event_type='CACHE_HIT',
                timestamp=base_time + datetime.timedelta(hours=2),
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=2),
                event_type='CACHE_INPUT_TOKENS',
                timestamp=base_time + datetime.timedelta(hours=2),  # 14:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.20,
                value=80,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=2),
                event_type='CACHE_OUTPUT_TOKENS',
                timestamp=base_time + datetime.timedelta(hours=2),  # 14:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.60,
                value=240,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=3),
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=3),  # 13:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.20,
                value=80,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=3),
                event_type='CACHE_INPUT_TOKENS',
                timestamp=base_time + datetime.timedelta(hours=3),  # 15:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.20,
                value=80,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=3),
                event_type='CACHE_OUTPUT_TOKENS',
                timestamp=base_time + datetime.timedelta(hours=3),  # 15:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.20,
                value=80,
                cache_type='semantic',
            ),
        ]
        self.insert(test_events)
        _from = base_time  # 12:00
        _to = base_time + datetime.timedelta(hours=2)  # 14:00

        res = self.event_dao.get_semantic_cache_details(
            None, ['rb-gateway'], _from, _to, False
        )
        assert res.cache_triggered == 3
        assert res.llm_input_request_savings == 0.50
        assert res.llm_output_request_savings == 1.60
        assert res.llm_total_request_savings == 2.10
        assert res.embedding_inference_cost == 0.30
        assert res.net_savings == 1.80
        assert res.cache_saved_tokens_input is None
        assert res.cache_saved_tokens_output is None
        assert res.total_cached_tokens is None

    def test_get_semantic_cache_details_with_tokens(self):
        base_time = datetime.datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_event(
                event_type='CACHE_HIT',
                timestamp=base_time + datetime.timedelta(hours=1),
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                event_type='CACHE_HIT',
                timestamp=base_time + datetime.timedelta(hours=2),
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                event_type='CACHE_HIT',
                timestamp=base_time + datetime.timedelta(minutes=2),
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                event_type='CACHE_HIT',
                timestamp=base_time,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=1),
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.10,
                value=40,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=1),
                event_type='CACHE_INPUT_TOKENS',
                timestamp=base_time,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.10,
                value=40,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=1),
                event_type='CACHE_OUTPUT_TOKENS',
                timestamp=base_time,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.10,
                value=30,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=2),
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=1),  # 13:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.20,
                value=80,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=2),
                event_type='CACHE_INPUT_TOKENS',
                timestamp=base_time + datetime.timedelta(hours=1),  # 13:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.20,
                value=80,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=2),
                event_type='CACHE_OUTPUT_TOKENS',
                timestamp=base_time + datetime.timedelta(hours=1),  # 13:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.20,
                value=60,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=2),
                event_type='CACHE_INPUT_TOKENS',
                timestamp=base_time + datetime.timedelta(hours=2),  # 14:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.20,
                value=80,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=3),
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=3),  # 13:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.20,
                value=80,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=3),
                event_type='CACHE_INPUT_TOKENS',
                timestamp=base_time + datetime.timedelta(hours=3),  # 15:00
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.20,
                value=80,
                cache_type='semantic',
            ),
        ]
        self.insert(test_events)
        _from = base_time  # 12:00
        _to = base_time + datetime.timedelta(hours=2)  # 14:00

        res = self.event_dao.get_semantic_cache_details(
            None, ['rb-gateway'], _from, _to, True
        )
        assert res.cache_triggered == 4
        assert res.llm_input_request_savings == 0.50
        assert res.llm_output_request_savings == 0.30
        assert res.llm_total_request_savings == 0.80
        assert res.embedding_inference_cost == 0.30
        assert res.net_savings == 0.50
        assert res.cache_saved_tokens_input == 200
        assert res.cache_saved_tokens_output == 90
        assert res.total_cached_tokens == 290

    def test_get_semantic_cache_details_no_data(self):
        base_time = datetime.datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=1),
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.50,
            ),
        ]
        self.insert(test_events)

        _from = base_time  # 12:00
        _to = base_time + datetime.timedelta(hours=2)  # 14:00

        res = self.event_dao.get_semantic_cache_details(
            None, ['rb-gateway'], _from, _to, False
        )
        assert res is not None
        assert res.embedding_inference_cost == 0
        assert res.llm_total_request_savings == 0
        assert res.net_savings == 0
        assert res.cache_saved_tokens_input is None
        assert res.cache_saved_tokens_output is None

    def test_summary_cost_filters_cache_type(self):
        base_time = datetime.datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            # Events without cache_type - should be included
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=1),
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.10,
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=1),
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.20,
            ),
            # Events with cache_type='exact' - should be included
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=1),
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.15,
                cache_type='exact',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=1),
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.25,
                cache_type='exact',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=1),
                event_type='CACHE_HIT',
                timestamp=base_time,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cache_type='exact',
            ),
            # Events with cache_type='semantic' - should be excluded
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=1),
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=1.00,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=1),
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=2.00,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                request_uuid=uuid.UUID(int=1),
                event_type='CACHE_HIT',
                timestamp=base_time,
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cache_type='semantic',
            ),
        ]
        self.insert(test_events)
        _from = base_time
        _to = base_time + datetime.timedelta(hours=1)

        res = self.event_dao.get_summary_costs(
            None, ['rb-gateway'], _from, _to, False, False
        )
        assert res is not None
        # Should only include events without cache_type (0.10 + 0.15) and with cache_type='exact'
        assert res.input_cost == 0.25  # 0.10 (no cache_type) + 0.15 (exact)
        assert res.output_cost == 0.45  # 0.20 (no cache_type) + 0.25 (exact)
        assert res.total_cost == 0.70  # 0.25 + 0.45
        # Semantic cache events (1.00 + 2.00 = 3.00) should be excluded

    def test_get_chart_data_hourly_granularity_by_model_name(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 30, 45, tzinfo=datetime.timezone.utc
        )

        test_events = [
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,  # 10:30
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.0005,
                model_id='gpt-4',
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(minutes=30),  # 11:00
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.000010,
                model_id='gpt-4',
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=1),  # 11:30
                api_key_uuid=uuid.UUID(int=2),
                api_key_name='key-2',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.0003,
                model_id='gpt-3.5-turbo',
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=1, minutes=15),  # 11:45
                api_key_uuid=uuid.UUID(int=2),
                api_key_name='key-2',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.0000007,
                model_id='gpt-3.5-turbo',
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=3, minutes=30),
                api_key_uuid=uuid.UUID(int=2),
                api_key_name='key-2',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.025,
                model_id='gpt-4',
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=3, minutes=45),
                api_key_uuid=uuid.UUID(int=2),
                api_key_name='key-2',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.000006,
                model_id='gpt-4',
            ),
        ]
        self.insert(test_events)
        _from = base_time - datetime.timedelta(hours=2)
        _to = _from + datetime.timedelta(hours=12)

        res = self.event_dao.get_costs_chart_data(
            None, ['rb-gateway'], _from, _to, 'hours', 'models'
        )
        assert res is not None
        assert len(res) == 4
        assert res[0].bucket == datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        assert res[0].group_by_value == 'gpt-4'
        assert res[0].total_cost == 0.0005

        assert res[1].bucket == datetime.datetime(
            2025, 1, 8, 11, 0, 0, tzinfo=datetime.timezone.utc
        )
        assert res[1].group_by_value == 'gpt-3.5-turbo'
        assert res[1].total_cost == 0.0003007

        assert res[2].bucket == datetime.datetime(
            2025, 1, 8, 11, 0, 0, tzinfo=datetime.timezone.utc
        )
        assert res[2].group_by_value == 'gpt-4'
        assert res[2].total_cost == 0.000010

        assert res[3].bucket == datetime.datetime(
            2025, 1, 8, 14, 0, 0, tzinfo=datetime.timezone.utc
        )
        assert res[3].group_by_value == 'gpt-4'
        assert res[3].total_cost == 0.025006

    def test_get_chart_data_daily_granularity_by_model_name(self):
        base_time = datetime.datetime(2025, 1, 8, 0, 0, 0, tzinfo=datetime.timezone.utc)

        test_events = [
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=5),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=1.50,
                model_id='gpt-4',
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=18),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=2.25,
                model_id='gpt-4',
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(days=1, hours=8),
                api_key_uuid=uuid.UUID(int=2),
                api_key_name='key-2',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=0.80,
                model_id='gpt-3.5-turbo',
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(days=3)

        res = self.event_dao.get_costs_chart_data(
            None, ['rb-gateway'], _from, _to, 'days', 'models'
        )

        assert res is not None
        assert len(res) == 2
        assert res[0].bucket == base_time
        assert res[0].group_by_value == 'gpt-4'
        assert res[0].total_cost == 3.75

        assert res[1].bucket == base_time + datetime.timedelta(days=1)
        assert res[1].group_by_value == 'gpt-3.5-turbo'
        assert res[1].total_cost == 0.80

    def test_get_chart_data_weekly_granularity_by_model_name(self):
        base_time = datetime.datetime(2025, 1, 6, 0, 0, 0, tzinfo=datetime.timezone.utc)

        test_events = [
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(days=1),
                api_key_uuid=uuid.UUID(int=1),
                api_key_name='key-1',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=10.50,
                model_id='gpt-4',
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(days=3),
                api_key_uuid=uuid.UUID(int=2),
                api_key_name='key-2',
                group_uuid=uuid.UUID(int=2),
                group_name='group-2',
                cost=8.75,
                model_id='gpt-3.5-turbo',
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(days=8),
                api_key_uuid=uuid.UUID(int=3),
                api_key_name='key-3',
                group_uuid=uuid.UUID(int=1),
                group_name='group-1',
                cost=12.00,
                model_id='gpt-4',
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(days=60)

        res = self.event_dao.get_costs_chart_data(
            None, ['rb-gateway'], _from, _to, 'weeks', 'models'
        )
        assert res is not None
        assert len(res) == 3
        # Week 1: contains gpt-4 (10.50) and gpt-3.5-turbo (8.75), sorted alphabetically
        assert res[0].bucket == datetime.datetime(2025, 1, 6, 0, 0)
        assert res[0].group_by_value == 'gpt-3.5-turbo'
        assert res[0].total_cost == 8.75

        assert res[1].bucket == datetime.datetime(2025, 1, 6, 0, 0)
        assert res[1].group_by_value == 'gpt-4'
        assert res[1].total_cost == 10.50

        # Week 2: contains only gpt-4 (12.00)
        assert res[2].bucket == datetime.datetime(2025, 1, 13, 0, 0)
        assert res[2].group_by_value == 'gpt-4'
        assert res[2].total_cost == 12.00

    def test_get_token_chart_data(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                route_name='rb-gateway',
                value=100,
                model_id='gpt-4',
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=1),
                route_name='rb-gateway',
                value=150,
                model_id='gpt-4',
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                route_name='rb-gateway',
                value=50,
                model_id='gpt-4',
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time + datetime.timedelta(hours=1),
                route_name='rb-gateway',
                value=75,
                model_id='gpt-4',
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=2)

        res = self.event_dao.get_token_chart_data(
            None, ['rb-gateway'], _from, _to, 'hours', 0
        )
        assert res is not None
        assert len(res) == 4
        assert res[0].bucket == base_time
        assert res[0].event_type == 'INPUT_TOKEN_PROCESSED'
        assert res[0].total_tokens == 100
        assert res[1].bucket == base_time
        assert res[1].event_type == 'OUTPUT_TOKEN_PROCESSED'
        assert res[1].total_tokens == 50
        assert res[2].bucket == base_time + datetime.timedelta(hours=1)
        assert res[2].event_type == 'INPUT_TOKEN_PROCESSED'
        assert res[2].total_tokens == 150
        assert res[3].bucket == base_time + datetime.timedelta(hours=1)
        assert res[3].event_type == 'OUTPUT_TOKEN_PROCESSED'
        assert res[3].total_tokens == 75

    def test_get_token_chart_data_empty(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        _from = base_time
        _to = base_time + datetime.timedelta(hours=2)

        res = self.event_dao.get_token_chart_data(
            None, ['rb-gateway'], _from, _to, 'hours', 0
        )
        assert res is not None
        assert len(res) == 0

    def test_get_all_routes_summary_costs(self):
        base_time = datetime.datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-X',
                timestamp=base_time,
                cost=0.20,
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-X',
                timestamp=base_time + datetime.timedelta(hours=1),
                cost=0.30,
            ),
            db_mock.get_sample_event(
                event_type='CACHE_HIT',
                route_name='route-X',
                timestamp=base_time + datetime.timedelta(hours=1),
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-Y',
                timestamp=base_time,
                cost=0.10,
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-Y',
                timestamp=base_time + datetime.timedelta(hours=1),
                cost=0.15,
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=2)

        res = self.event_dao.get_all_routes_summary_costs(None, _from, _to, False)
        assert res is not None
        by_route = {r.route_name: r for r in res}
        assert 'route-X' in by_route
        assert by_route['route-X'].input_cost == 0.20
        assert by_route['route-X'].output_cost == 0.30
        assert by_route['route-X'].total_cost == 0.50
        assert by_route['route-X'].cache_triggered == 1
        assert by_route['route-X'].saved_amount_input == 0
        assert by_route['route-X'].saved_amount_output == 0
        assert by_route['route-X'].total_saved_amount == 0
        assert 'route-Y' in by_route
        assert by_route['route-Y'].input_cost == 0.10
        assert by_route['route-Y'].output_cost == 0.15
        assert by_route['route-Y'].total_cost == 0.25
        assert by_route['route-Y'].cache_triggered == 0
        assert by_route['route-Y'].saved_amount_input == 0
        assert by_route['route-Y'].saved_amount_output == 0
        assert by_route['route-Y'].total_saved_amount == 0

    def test_get_all_routes_summary_costs_empty(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        _from = now + datetime.timedelta(hours=100)
        _to = _from + datetime.timedelta(hours=1)
        res = self.event_dao.get_all_routes_summary_costs(None, _from, _to, False)
        assert res is not None
        assert len(res) == 0

    def test_get_all_routes_summary_costs_semantic_breakdown(self):
        base_time = datetime.datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            # Regular input (no cache_type)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-Z',
                timestamp=base_time,
                cost=0.10,
            ),
            # Semantic input (embedding inference)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-Z',
                timestamp=base_time,
                cost=1.00,
                cache_type='semantic',
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=1)
        res = self.event_dao.get_all_routes_summary_costs(None, _from, _to, False)
        by_route = {r.route_name: r for r in res}
        assert 'route-Z' in by_route
        # input_cost includes ALL INPUT_TOKEN_PROCESSED (no cache_type filter)
        assert by_route['route-Z'].input_cost == 1.10
        assert by_route['route-Z'].output_cost == 0
        assert by_route['route-Z'].total_cost == 1.10
        # semantic breakdown
        assert by_route['route-Z'].embedding_inference_cost == 1.00
        assert by_route['route-Z'].llm_input_request_savings == 0
        assert by_route['route-Z'].llm_output_request_savings == 0
        assert by_route['route-Z'].llm_total_request_savings == 0

    def test_get_all_routes_summary_costs_with_exact_and_semantic_cache(self):
        base_time = datetime.datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            # Regular tokens
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-W',
                timestamp=base_time,
                cost=0.50,
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-W',
                timestamp=base_time,
                cost=0.30,
            ),
            # Exact cache savings
            db_mock.get_sample_event(
                event_type='CACHE_INPUT_TOKENS',
                route_name='route-W',
                timestamp=base_time,
                cost=0.10,
                value=20,
                cache_type='exact',
            ),
            db_mock.get_sample_event(
                event_type='CACHE_OUTPUT_TOKENS',
                route_name='route-W',
                timestamp=base_time,
                cost=0.05,
                value=10,
                cache_type='exact',
            ),
            db_mock.get_sample_event(
                event_type='CACHE_HIT',
                route_name='route-W',
                timestamp=base_time,
                cache_type='exact',
            ),
            # Semantic cache savings
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-W',
                timestamp=base_time,
                cost=0.20,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                event_type='CACHE_INPUT_TOKENS',
                route_name='route-W',
                timestamp=base_time,
                cost=0.15,
                value=30,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                event_type='CACHE_OUTPUT_TOKENS',
                route_name='route-W',
                timestamp=base_time,
                cost=0.25,
                value=50,
                cache_type='semantic',
            ),
            db_mock.get_sample_event(
                event_type='CACHE_HIT',
                route_name='route-W',
                timestamp=base_time,
                cache_type='semantic',
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=1)
        res = self.event_dao.get_all_routes_summary_costs(None, _from, _to, False)
        by_route = {r.route_name: r for r in res}
        assert 'route-W' in by_route
        r = by_route['route-W']
        # input_cost includes all INPUT_TOKEN_PROCESSED (regular + semantic)
        assert r.input_cost == 0.70  # 0.50 + 0.20
        assert r.output_cost == 0.30
        assert r.total_cost == 1.00  # 0.70 + 0.30
        assert r.cache_triggered == 2  # exact + semantic
        # exact cache breakdown
        assert r.partial_saved_amount_input == 0.10
        assert r.partial_saved_amount_output == 0.05
        assert r.partial_saved_amount == 0.15
        # semantic cache breakdown
        assert r.llm_input_request_savings == 0.15
        assert r.llm_output_request_savings == 0.25
        assert r.llm_total_request_savings == 0.40
        assert r.embedding_inference_cost == 0.20
        # combined saved amounts
        assert r.saved_amount_input == 0.25  # 0.10 (exact) + 0.15 (semantic)
        assert r.saved_amount_output == 0.30  # 0.05 (exact) + 0.25 (semantic)
        # total_saved = partial_saved + (llm_total - embedding_cost)
        assert r.total_saved_amount == 0.35  # 0.15 + (0.40 - 0.20)

    def test_get_all_routes_summary_costs_with_saved_tokens(self):
        base_time = datetime.datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-T',
                timestamp=base_time,
                cost=0.50,
            ),
            db_mock.get_sample_event(
                event_type='CACHE_INPUT_TOKENS',
                route_name='route-T',
                timestamp=base_time,
                cost=0.10,
                value=40,
            ),
            db_mock.get_sample_event(
                event_type='CACHE_OUTPUT_TOKENS',
                route_name='route-T',
                timestamp=base_time,
                cost=0.05,
                value=60,
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=1)

        res = self.event_dao.get_all_routes_summary_costs(None, _from, _to, True)
        by_route = {r.route_name: r for r in res}
        assert 'route-T' in by_route
        r = by_route['route-T']
        assert r.cache_saved_tokens_input == 40
        assert r.cache_saved_tokens_output == 60
        assert r.total_cached_tokens == 100

    def test_detailed_cost_breakdown(self):
        base_time = datetime.datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            # Chat model - standard input (non-cached, non-judge)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                cost=1.0,
                model_type='chat-model',
                is_cached_tokens=False,
                is_judge=False,
            ),
            # Chat model - cached input (non-judge)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                cost=0.5,
                model_type='chat-model',
                is_cached_tokens=True,
                is_judge=False,
            ),
            # Chat model - judge input (standard)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                cost=0.3,
                model_type='chat-model',
                is_cached_tokens=False,
                is_judge=True,
            ),
            # Chat model - judge input (cached)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                cost=0.2,
                model_type='chat-model',
                is_cached_tokens=True,
                is_judge=True,
            ),
            # Chat model - output (non-judge)
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                cost=2.0,
                model_type='chat-model',
                is_judge=False,
            ),
            # Chat model - output (judge)
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                cost=0.8,
                model_type='chat-model',
                is_judge=True,
            ),
            # Embedding model - direct input
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                cost=0.4,
                model_type='embeddings',
                cache_type='',
            ),
            # Embedding model - semantic cache input
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                cost=0.6,
                model_type='embeddings',
                cache_type='semantic',
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=1)

        res = self.event_dao.get_detailed_cost_breakdown(
            None, ['rb-gateway'], _from, _to
        )
        assert res is not None
        # Chat input standard (non-cached, non-judge): 1.0
        assert res.chat_input_direct == 1.0
        # Chat input cached (cached non-judge): 0.5
        assert res.chat_input_cached == 0.5
        # Chat input judges (not cached, judge): 0.3
        assert res.chat_input_judges == 0.3
        # Chat input judges cached: 0.2
        assert res.chat_input_judges_cached == 0.2
        # Chat output (non-judge): 2.0
        assert res.chat_output_direct == 2.0
        # Chat output judges: 0.8
        assert res.chat_output_judges == 0.8
        # Embedding input: 0.4 + 0.6 = 1.0
        assert res.embedding_input_total == 1.0
        # Embedding input direct: 0.4
        assert res.embedding_input_direct == 0.4
        # Embedding input semantic cache: 0.6
        assert res.embedding_input_semantic_cache == 0.6

    def test_get_all_routes_detailed_cost_breakdown(self):
        base_time = datetime.datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            # route-A: chat model events
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-A',
                timestamp=base_time,
                cost=1.0,
                model_type='chat-model',
                is_cached_tokens=False,
                is_judge=False,
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-A',
                timestamp=base_time,
                cost=2.0,
                model_type='chat-model',
                is_judge=False,
            ),
            # route-B: chat model with judges
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-B',
                timestamp=base_time,
                cost=0.3,
                model_type='chat-model',
                is_cached_tokens=False,
                is_judge=True,
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-B',
                timestamp=base_time,
                cost=0.8,
                model_type='chat-model',
                is_judge=True,
            ),
            # route-C: embeddings
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-C',
                timestamp=base_time,
                cost=0.4,
                model_type='embeddings',
                cache_type='',
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-C',
                timestamp=base_time,
                cost=0.6,
                model_type='embeddings',
                cache_type='semantic',
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=1)

        res = self.event_dao.get_all_routes_detailed_cost_breakdown(None, _from, _to)
        assert res is not None
        by_route = {r.route_name: r for r in res}

        # route-A: chat only
        assert 'route-A' in by_route
        assert by_route['route-A'].chat_input_direct == 1.0
        assert by_route['route-A'].chat_input_cached == 0.0
        assert by_route['route-A'].chat_input_judges == 0.0
        assert by_route['route-A'].chat_input_judges_cached == 0.0
        assert by_route['route-A'].chat_output_direct == 2.0
        assert by_route['route-A'].chat_output_judges == 0.0
        assert by_route['route-A'].embedding_input_total == 0.0
        assert by_route['route-A'].embedding_input_direct == 0.0
        assert by_route['route-A'].embedding_input_semantic_cache == 0.0

        # route-B: chat with judges
        assert 'route-B' in by_route
        # chat_input_direct excludes judge events (non-judge only): 0.0
        assert by_route['route-B'].chat_input_direct == 0.0
        assert by_route['route-B'].chat_input_cached == 0.0
        assert by_route['route-B'].chat_input_judges == 0.3
        assert by_route['route-B'].chat_input_judges_cached == 0.0
        # chat_output_direct excludes judge outputs (non-judge only): 0.0
        assert by_route['route-B'].chat_output_direct == 0.0
        assert by_route['route-B'].chat_output_judges == 0.8
        assert by_route['route-B'].embedding_input_total == 0.0
        assert by_route['route-B'].embedding_input_direct == 0.0
        assert by_route['route-B'].embedding_input_semantic_cache == 0.0

        # route-C: embeddings
        assert 'route-C' in by_route
        assert by_route['route-C'].chat_input_direct == 0.0
        assert by_route['route-C'].chat_input_cached == 0.0
        assert by_route['route-C'].chat_input_judges == 0.0
        assert by_route['route-C'].chat_input_judges_cached == 0.0
        assert by_route['route-C'].chat_output_direct == 0.0
        assert by_route['route-C'].chat_output_judges == 0.0
        assert by_route['route-C'].embedding_input_total == 1.0
        assert by_route['route-C'].embedding_input_direct == 0.4
        assert by_route['route-C'].embedding_input_semantic_cache == 0.6

    def test_get_all_routes_detailed_cost_breakdown_empty(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        _from = now + datetime.timedelta(hours=100)
        _to = _from + datetime.timedelta(hours=1)
        res = self.event_dao.get_all_routes_detailed_cost_breakdown(None, _from, _to)
        assert res is not None
        assert len(res) == 0

    def test_get_all_routes_detailed_cost_breakdown_complex(self):
        base_time = datetime.datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            # Chat model - standard input (non-cached, non-judge)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-complex',
                timestamp=base_time,
                cost=1.0,
                model_type='chat-model',
                is_cached_tokens=False,
                is_judge=False,
            ),
            # Chat model - cached input (non-judge)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-complex',
                timestamp=base_time,
                cost=0.5,
                model_type='chat-model',
                is_cached_tokens=True,
                is_judge=False,
            ),
            # Chat model - judge input (standard)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-complex',
                timestamp=base_time,
                cost=0.3,
                model_type='chat-model',
                is_cached_tokens=False,
                is_judge=True,
            ),
            # Chat model - judge input (cached)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-complex',
                timestamp=base_time,
                cost=0.2,
                model_type='chat-model',
                is_cached_tokens=True,
                is_judge=True,
            ),
            # Chat model - output (non-judge)
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-complex',
                timestamp=base_time,
                cost=2.0,
                model_type='chat-model',
                is_judge=False,
            ),
            # Chat model - output (judge)
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-complex',
                timestamp=base_time,
                cost=0.8,
                model_type='chat-model',
                is_judge=True,
            ),
            # Embedding model - direct input
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-complex',
                timestamp=base_time,
                cost=0.4,
                model_type='embeddings',
                cache_type='',
            ),
            # Embedding model - semantic cache input
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-complex',
                timestamp=base_time,
                cost=0.6,
                model_type='embeddings',
                cache_type='semantic',
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=1)

        res = self.event_dao.get_all_routes_detailed_cost_breakdown(None, _from, _to)
        assert res is not None
        assert len(res) == 1
        by_route = {r.route_name: r for r in res}
        assert 'route-complex' in by_route
        # Chat input standard (non-cached, non-judge): 1.0
        assert by_route['route-complex'].chat_input_direct == 1.0
        # Chat input cached (non-judge): 0.5
        assert by_route['route-complex'].chat_input_cached == 0.5
        # Chat input judges (not cached): 0.3
        assert by_route['route-complex'].chat_input_judges == 0.3
        # Chat input judges cached: 0.2
        assert by_route['route-complex'].chat_input_judges_cached == 0.2
        # Chat output (non-judge): 2.0
        assert by_route['route-complex'].chat_output_direct == 2.0
        # Chat output judges: 0.8
        assert by_route['route-complex'].chat_output_judges == 0.8
        # Embedding input: 0.4 + 0.6 = 1.0
        assert by_route['route-complex'].embedding_input_total == 1.0
        # Embedding input direct: 0.4
        assert by_route['route-complex'].embedding_input_direct == 0.4
        # Embedding input semantic cache: 0.6
        assert by_route['route-complex'].embedding_input_semantic_cache == 0.6

    def test_get_all_routes_detailed_cost_breakdown_time_filtering(self):
        base_time = datetime.datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            # Event in range
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-time',
                timestamp=base_time,
                cost=1.0,
                model_type='chat-model',
                is_cached_tokens=False,
                is_judge=False,
            ),
            # Event outside range (too early)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-time',
                timestamp=base_time - datetime.timedelta(hours=2),
                cost=2.0,
                model_type='chat-model',
                is_cached_tokens=False,
                is_judge=False,
            ),
            # Event outside range (too late)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-time',
                timestamp=base_time + datetime.timedelta(hours=2),
                cost=3.0,
                model_type='chat-model',
                is_cached_tokens=False,
                is_judge=False,
            ),
        ]
        self.insert(test_events)

        _from = base_time - datetime.timedelta(hours=1)
        _to = base_time + datetime.timedelta(hours=1)

        res = self.event_dao.get_all_routes_detailed_cost_breakdown(None, _from, _to)
        assert res is not None
        assert len(res) == 1
        # Only the event at base_time (1.0) should be included
        assert res[0].chat_input_direct == 1.0

    def test_get_all_routes_detailed_cost_breakdown_no_time_filter(self):
        base_time = datetime.datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-all',
                timestamp=base_time,
                cost=1.0,
                model_type='chat-model',
                is_cached_tokens=False,
                is_judge=False,
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-all',
                timestamp=base_time + datetime.timedelta(hours=2),
                cost=2.0,
                model_type='chat-model',
                is_judge=False,
            ),
        ]
        self.insert(test_events)

        # Use None for time parameters - returns all data
        res = self.event_dao.get_all_routes_detailed_cost_breakdown(None, None, None)
        assert res is not None
        by_route = {r.route_name: r for r in res}
        # Should have route-all plus the common test data routes (route-A, route-B)
        assert 'route-all' in by_route
        assert by_route['route-all'].chat_input_direct == 1.0
        assert by_route['route-all'].chat_output_direct == 2.0

    def test_get_invocation_chart_data_hourly(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_event(
                event_type='MODEL_INVOCATION',
                timestamp=base_time,
                route_name='inv-route',
                value=1,
                model_id='gpt-4',
            ),
            db_mock.get_sample_event(
                event_type='MODEL_INVOCATION',
                timestamp=base_time + datetime.timedelta(minutes=30),
                route_name='inv-route',
                value=1,
                model_id='gpt-4',
            ),
            db_mock.get_sample_event(
                event_type='MODEL_INVOCATION',
                timestamp=base_time + datetime.timedelta(hours=1),
                route_name='inv-route',
                value=1,
                model_id='gpt-3.5-turbo',
            ),
            db_mock.get_sample_event(
                event_type='MODEL_INVOCATION',
                timestamp=base_time + datetime.timedelta(hours=1, minutes=15),
                route_name='inv-route',
                value=1,
                model_id='gpt-4',
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=2)

        res = self.event_dao.get_invocation_chart_data(
            None, ['inv-route'], _from, _to, 'hours', include_models=True
        )
        assert res is not None
        assert len(res) == 3
        # 10:00 bucket: gpt-4 has 2 invocations
        assert res[0].bucket == base_time
        assert res[0].group_by_value == 'gpt-4'
        assert res[0].value == 2
        # 11:00 bucket: gpt-3.5-turbo has 1 invocation
        assert res[1].bucket == base_time + datetime.timedelta(hours=1)
        assert res[1].group_by_value == 'gpt-3.5-turbo'
        assert res[1].value == 1
        # 11:00 bucket: gpt-4 has 1 invocation
        assert res[2].bucket == base_time + datetime.timedelta(hours=1)
        assert res[2].group_by_value == 'gpt-4'
        assert res[2].value == 1

    def test_get_invocation_chart_data_daily(self):
        base_time = datetime.datetime(2025, 1, 8, 0, 0, 0, tzinfo=datetime.timezone.utc)
        test_events = [
            db_mock.get_sample_event(
                event_type='MODEL_INVOCATION',
                timestamp=base_time + datetime.timedelta(hours=5),
                route_name='inv-route-d',
                value=1,
                model_id='gpt-4',
            ),
            db_mock.get_sample_event(
                event_type='MODEL_INVOCATION',
                timestamp=base_time + datetime.timedelta(hours=18),
                route_name='inv-route-d',
                value=1,
                model_id='gpt-4',
            ),
            db_mock.get_sample_event(
                event_type='MODEL_INVOCATION',
                timestamp=base_time + datetime.timedelta(days=1, hours=8),
                route_name='inv-route-d',
                value=1,
                model_id='gpt-3.5-turbo',
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(days=3)

        res = self.event_dao.get_invocation_chart_data(
            None, ['inv-route-d'], _from, _to, 'days', include_models=True
        )
        assert res is not None
        assert len(res) == 2
        assert res[0].bucket == base_time
        assert res[0].group_by_value == 'gpt-4'
        assert res[0].value == 2
        assert res[1].bucket == base_time + datetime.timedelta(days=1)
        assert res[1].group_by_value == 'gpt-3.5-turbo'
        assert res[1].value == 1

    def test_get_invocation_chart_data_filters_by_route(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_event(
                event_type='MODEL_INVOCATION',
                timestamp=base_time,
                route_name='inv-route-1',
                value=1,
                model_id='gpt-4',
            ),
            db_mock.get_sample_event(
                event_type='MODEL_INVOCATION',
                timestamp=base_time,
                route_name='inv-route-2',
                value=1,
                model_id='gpt-4',
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=1)

        res = self.event_dao.get_invocation_chart_data(
            None, ['inv-route-1'], _from, _to, 'hours', include_models=True
        )
        assert res is not None
        assert len(res) == 1
        assert res[0].value == 1

    def test_get_invocation_chart_data_filters_by_time_range(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            # Before range
            db_mock.get_sample_event(
                event_type='MODEL_INVOCATION',
                timestamp=base_time - datetime.timedelta(hours=2),
                route_name='inv-route-t',
                value=1,
                model_id='gpt-4',
            ),
            # In range
            db_mock.get_sample_event(
                event_type='MODEL_INVOCATION',
                timestamp=base_time,
                route_name='inv-route-t',
                value=1,
                model_id='gpt-4',
            ),
            # After range
            db_mock.get_sample_event(
                event_type='MODEL_INVOCATION',
                timestamp=base_time + datetime.timedelta(hours=3),
                route_name='inv-route-t',
                value=1,
                model_id='gpt-4',
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=1)

        res = self.event_dao.get_invocation_chart_data(
            None, ['inv-route-t'], _from, _to, 'hours', include_models=True
        )
        assert res is not None
        assert len(res) == 1
        assert res[0].value == 1

    def test_get_invocation_chart_data_empty(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        _from = base_time + datetime.timedelta(days=100)
        _to = _from + datetime.timedelta(hours=1)

        res = self.event_dao.get_invocation_chart_data(
            None, ['inv-route-empty'], _from, _to, 'hours', include_models=True
        )
        assert res is not None
        assert len(res) == 0

    def test_get_invocation_chart_data_ignores_other_event_types(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_event(
                event_type='MODEL_INVOCATION',
                timestamp=base_time,
                route_name='inv-route-f',
                value=1,
                model_id='gpt-4',
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                route_name='inv-route-f',
                value=100,
                model_id='gpt-4',
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                timestamp=base_time,
                route_name='inv-route-f',
                value=50,
                model_id='gpt-4',
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=1)

        res = self.event_dao.get_invocation_chart_data(
            None, ['inv-route-f'], _from, _to, 'hours', include_models=True
        )
        assert res is not None
        assert len(res) == 1
        assert res[0].value == 1

    def test_get_invocation_chart_data_without_models(self):
        base_time = datetime.datetime(
            2025, 1, 8, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_event(
                event_type='MODEL_INVOCATION',
                timestamp=base_time,
                route_name='inv-route-no-model',
                value=1,
                model_id='gpt-4',
            ),
            db_mock.get_sample_event(
                event_type='MODEL_INVOCATION',
                timestamp=base_time + datetime.timedelta(minutes=30),
                route_name='inv-route-no-model',
                value=1,
                model_id='gpt-4',
            ),
            db_mock.get_sample_event(
                event_type='MODEL_INVOCATION',
                timestamp=base_time + datetime.timedelta(minutes=45),
                route_name='inv-route-no-model',
                value=1,
                model_id='gpt-3.5-turbo',
            ),
            db_mock.get_sample_event(
                event_type='MODEL_INVOCATION',
                timestamp=base_time + datetime.timedelta(hours=1),
                route_name='inv-route-no-model',
                value=1,
                model_id='gpt-4',
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=2)

        res = self.event_dao.get_invocation_chart_data(
            None, ['inv-route-no-model'], _from, _to, 'hours', include_models=False
        )
        assert res is not None
        # Without model grouping, all models in same bucket are summed together
        assert len(res) == 2
        # 10:00 bucket: 3 total invocations (2 gpt-4 + 1 gpt-3.5-turbo)
        assert res[0].bucket == base_time
        assert res[0].group_by_value == 'all'
        assert res[0].value == 3
        # 11:00 bucket: 1 invocation
        assert res[1].bucket == base_time + datetime.timedelta(hours=1)
        assert res[1].group_by_value == 'all'
        assert res[1].value == 1

    def test_get_most_expensive_route(self):
        base_time = datetime.datetime(
            2025, 1, 10, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            # route-exp-A: total cost = 3.0
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-exp-A',
                timestamp=base_time,
                cost=1.0,
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-exp-A',
                timestamp=base_time,
                cost=2.0,
            ),
            # route-exp-B: total cost = 5.0 (highest)
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-exp-B',
                timestamp=base_time,
                cost=2.5,
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-exp-B',
                timestamp=base_time,
                cost=2.5,
            ),
            # route-exp-C: total cost = 1.0
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-exp-C',
                timestamp=base_time,
                cost=1.0,
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=1)

        res = self.event_dao.get_most_expensive_route(
            None, ['route-exp-A', 'route-exp-B', 'route-exp-C'], _from, _to
        )
        assert res is not None
        assert isinstance(res, MostExpensiveRoute)
        assert res.route_name == 'route-exp-B'
        assert res.total_cost == 5.0

    def test_get_most_expensive_route_with_time_filter(self):
        base_time = datetime.datetime(
            2025, 1, 11, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            # In range: route-exp-tf-A cost=1.0
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-exp-tf-A',
                timestamp=base_time,
                cost=1.0,
            ),
            # Out of range (before): route-exp-tf-A cost=10.0
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-exp-tf-A',
                timestamp=base_time - datetime.timedelta(hours=5),
                cost=10.0,
            ),
            # In range: route-exp-tf-B cost=2.0
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-exp-tf-B',
                timestamp=base_time,
                cost=2.0,
            ),
            # Out of range (after): route-exp-tf-B cost=20.0
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-exp-tf-B',
                timestamp=base_time + datetime.timedelta(hours=5),
                cost=20.0,
            ),
        ]
        self.insert(test_events)

        _from = base_time - datetime.timedelta(hours=1)
        _to = base_time + datetime.timedelta(hours=1)

        res = self.event_dao.get_most_expensive_route(
            None, ['route-exp-tf-A', 'route-exp-tf-B'], _from, _to
        )
        assert res is not None
        # Only in-range events: route-exp-tf-B has 2.0 > route-exp-tf-A has 1.0
        assert res.route_name == 'route-exp-tf-B'
        assert res.total_cost == 2.0

    def test_get_most_expensive_route_empty(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        _from = now + datetime.timedelta(days=200)
        _to = _from + datetime.timedelta(hours=1)

        res = self.event_dao.get_most_expensive_route(None, ['route-x'], _from, _to)
        assert res is None

    def test_get_most_expensive_route_no_filter(self):
        base_time = datetime.datetime(
            2025, 1, 12, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-exp-nf',
                timestamp=base_time,
                cost=3.0,
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-exp-nf',
                timestamp=base_time + datetime.timedelta(days=30),
                cost=4.0,
            ),
        ]
        self.insert(test_events)

        res = self.event_dao.get_most_expensive_route(
            None, ['route-exp-nf'], None, None
        )
        assert res is not None
        assert res.route_name == 'route-exp-nf'
        assert res.total_cost > 0

    def test_get_cost_chart_data_hourly(self):
        base_time = datetime.datetime(
            2025, 2, 1, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-chart-cost',
                timestamp=base_time,
                cost=1.0,
            ),
            db_mock.get_sample_event(
                event_type='OUTPUT_TOKEN_PROCESSED',
                route_name='route-chart-cost',
                timestamp=base_time + datetime.timedelta(minutes=30),
                cost=2.0,
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-chart-cost',
                timestamp=base_time + datetime.timedelta(hours=1),
                cost=3.0,
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=2)

        res = self.event_dao.get_cost_chart_data(
            None, 'route-chart-cost', _from, _to, 'hours'
        )
        assert res is not None
        assert len(res) == 2
        assert all(isinstance(r, MostExpensiveChartData) for r in res)
        # First bucket: 10:00 — cost = 1.0 + 2.0 = 3.0
        assert res[0].bucket == base_time
        assert res[0].cost == 3.0
        # Second bucket: 11:00 — cost = 3.0
        assert res[1].bucket == base_time + datetime.timedelta(hours=1)
        assert res[1].cost == 3.0

    def test_get_cost_chart_data_filters_by_route(self):
        base_time = datetime.datetime(
            2025, 2, 2, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-chart-r1',
                timestamp=base_time,
                cost=5.0,
            ),
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-chart-r2',
                timestamp=base_time,
                cost=10.0,
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=1)

        res = self.event_dao.get_cost_chart_data(
            None, 'route-chart-r1', _from, _to, 'hours'
        )
        assert res is not None
        assert len(res) == 1
        assert res[0].cost == 5.0

    def test_get_cost_chart_data_filters_by_time(self):
        base_time = datetime.datetime(
            2025, 2, 3, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            # In range
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-chart-time',
                timestamp=base_time,
                cost=1.0,
            ),
            # Before range
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-chart-time',
                timestamp=base_time - datetime.timedelta(hours=5),
                cost=100.0,
            ),
            # After range
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-chart-time',
                timestamp=base_time + datetime.timedelta(hours=5),
                cost=100.0,
            ),
        ]
        self.insert(test_events)

        _from = base_time - datetime.timedelta(hours=1)
        _to = base_time + datetime.timedelta(hours=1)

        res = self.event_dao.get_cost_chart_data(
            None, 'route-chart-time', _from, _to, 'hours'
        )
        assert res is not None
        assert len(res) == 1
        assert res[0].cost == 1.0

    def test_get_cost_chart_data_empty(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        _from = now + datetime.timedelta(days=200)
        _to = _from + datetime.timedelta(hours=1)

        res = self.event_dao.get_cost_chart_data(
            None, 'route-chart-empty', _from, _to, 'hours'
        )
        assert res is not None
        assert len(res) == 0

    def test_get_cost_chart_data_ignores_non_token_events(self):
        base_time = datetime.datetime(
            2025, 2, 4, 10, 0, 0, tzinfo=datetime.timezone.utc
        )
        test_events = [
            db_mock.get_sample_event(
                event_type='INPUT_TOKEN_PROCESSED',
                route_name='route-chart-evt',
                timestamp=base_time,
                cost=1.0,
            ),
            # Non-token events should be excluded
            db_mock.get_sample_event(
                event_type='RATE_LIMIT',
                route_name='route-chart-evt',
                timestamp=base_time,
                cost=50.0,
            ),
            db_mock.get_sample_event(
                event_type='MODEL_INVOCATION',
                route_name='route-chart-evt',
                timestamp=base_time,
                cost=50.0,
            ),
        ]
        self.insert(test_events)

        _from = base_time
        _to = base_time + datetime.timedelta(hours=1)

        res = self.event_dao.get_cost_chart_data(
            None, 'route-chart-evt', _from, _to, 'hours'
        )
        assert res is not None
        assert len(res) == 1
        assert res[0].cost == 1.0
