import datetime
import uuid

from tests.common import db_mock
from tests.common.db_integration_ch import DatabaseIntegrationClickhouse

from radicalbit_ai_gateway.db.dao.event_dao import EventDAO
from radicalbit_ai_gateway.db.models.event import (
    CostData,
    Counters,
    DetailedCostBreakdown,
    EventDetails,
    LastEventFallback,
    LastEventGuardrail,
    MostExpensiveRoute,
    RouteCostData,
    RouteDetailedCostBreakdown,
    SemanticCacheCostData,
    TokensCounter,
)

UTC = datetime.timezone.utc
H = datetime.timedelta(hours=1)
D = datetime.timedelta(days=1)
KEY_0 = uuid.UUID(int=0)
KEY_1 = uuid.UUID(int=1)
# Base-data timestamps: the 14th is also get_sample_event's default timestamp.
OCT_14 = datetime.datetime(2025, 10, 14, 12, 58, 36, 931873, tzinfo=UTC)
OCT_13 = OCT_14 - D
OCT_12 = OCT_14 - 2 * D
# Most cost scenarios happen at noon on 2025-01-10.
NOON = datetime.datetime(2025, 1, 10, 12, 0, 0, tzinfo=UTC)
FUTURE = datetime.datetime.now(UTC) + 200 * D
INPUT = 'INPUT_TOKEN_PROCESSED'
OUTPUT = 'OUTPUT_TOKEN_PROCESSED'
CACHE_IN = 'CACHE_INPUT_TOKENS'
CACHE_OUT = 'CACHE_OUTPUT_TOKENS'
HIT = 'CACHE_HIT'
INVOCATION = 'MODEL_INVOCATION'


def _ev(event_type, route='rb-gateway', at=NOON, cost=0.0, **kwargs):
    return db_mock.get_sample_event(
        event_type=event_type, route_name=route, timestamp=at, cost=cost, **kwargs
    )


class EventDAOCountersTest(DatabaseIntegrationClickhouse):
    """Read-only queries over one data set, seeded once for the class."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.event_dao = EventDAO(cls.db)
        DatabaseIntegrationClickhouse.clean(cls)
        key = {'api_key_uuid': KEY_0}
        tokens = [
            (INPUT, 'route-A', 100, 'model-A'),
            (INPUT, 'route-A', 150, 'model-A'),
            (INPUT, 'route-B', 150, 'model-A'),
            (OUTPUT, 'route-A', 75, 'model-B'),
            (OUTPUT, 'route-A', 75, 'model-B'),
            (OUTPUT, 'route-B', 75, 'model-B'),
            (CACHE_IN, 'route-A', 2, 'model-A'),
            (CACHE_IN, 'route-A', 45, 'model-A'),
            (CACHE_OUT, 'route-A', 60, 'model-B'),
            (CACHE_IN, 'route-B', 2, 'model-A'),
            (CACHE_IN, 'route-B', 45, 'model-A'),
            (CACHE_OUT, 'route-B', 60, 'model-B'),
        ]
        DatabaseIntegrationClickhouse.insert(
            cls,
            [
                _ev(
                    'GUARDRAIL',
                    'route-A',
                    OCT_14,
                    name='PRESIDIO',
                    type='READACT',
                    where='INPUT',
                    parameters='PARAMS',
                    behavior='BLOCK',
                    **key,
                ),
                _ev('GUARDRAIL', 'route-B', OCT_12, **key),
                _ev('FALLBACK', 'route-A', OCT_13, **key),
                _ev(
                    'FALLBACK',
                    'route-A',
                    OCT_14,
                    target='gpt-4.1',
                    fallback='llama3.1',
                    **key,
                ),
                _ev('FALLBACK', 'route-B', OCT_12, **key),
                _ev('RATE_LIMIT', 'route-A', OCT_13, **key),
                _ev('RATE_LIMIT', 'route-B', OCT_12, **key),
                _ev(HIT, 'route-A', OCT_13, **key),
                *[
                    _ev(kind, route, OCT_14, value=value, model_id=model)
                    for kind, route, value, model in tokens
                ],
            ],
        )

    def tearDown(self) -> None:
        pass  # read-only tests share the class seed

    @classmethod
    def tearDownClass(cls):
        DatabaseIntegrationClickhouse.clean(cls)
        super().tearDownClass()

    def test_counters_and_last_events(self):
        dao = self.event_dao
        assert dao.get_all_counters(None, None, None) == Counters(
            guardrail_value=2,
            fallback_value=3,
            rate_limit_triggered=2,
            cache_triggered=1,
        )
        assert dao.get_all_counters_by_route(
            None, route_name='route-A', _from=None, _to=None
        ) == Counters(
            guardrail_value=1,
            fallback_value=2,
            rate_limit_triggered=1,
            cache_triggered=1,
        )
        guardrail = LastEventGuardrail(
            route_name='route-A',
            name='PRESIDIO',
            where='INPUT',
            type='READACT',
            behavior='BLOCK',
            timestamp=OCT_14,
            api_key_uuid=KEY_0,
            api_key_name='fake',
        )
        fallback = LastEventFallback(
            route_name='route-A',
            target='gpt-4.1',
            fallback='llama3.1',
            timestamp=OCT_14,
            api_key_uuid=KEY_0,
            api_key_name='fake',
        )
        for event_type, expected in (('GUARDRAIL', guardrail), ('FALLBACK', fallback)):
            assert (
                dao.get_last_event(None, event_type=event_type, _from=None, _to=None)
                == expected
            )
            assert (
                dao.get_last_event_route(
                    None,
                    event_type=event_type,
                    route_name='route-A',
                    _from=None,
                    _to=None,
                )
                == expected
            )

    def test_get_tokens_by_model(self):
        def counter(event_type, route, model, value):
            return TokensCounter(
                event_type=event_type, route_name=route, model_id=model, value=value
            )

        route_a = [
            counter(OUTPUT, 'route-A', 'model-B', 150),
            counter(CACHE_IN, 'route-A', 'model-A', 47),
            counter(INPUT, 'route-A', 'model-A', 250),
            counter(CACHE_OUT, 'route-A', 'model-B', 60),
        ]
        route_b = [
            counter(INPUT, 'route-B', 'model-A', 150),
            counter(CACHE_OUT, 'route-B', 'model-B', 60),
            counter(OUTPUT, 'route-B', 'model-B', 75),
            counter(CACHE_IN, 'route-B', 'model-A', 47),
        ]

        def ordered(counters):
            return sorted(
                counters, key=lambda x: (x.event_type, x.route_name, x.model_id)
            )

        assert ordered(self.event_dao.get_tokens_by_model(None, None, None)) == (
            ordered(route_a + route_b)
        )
        assert ordered(
            self.event_dao.get_tokens_by_model_per_route(None, 'route-A', None, None)
        ) == ordered(route_a)

    def test_get_latest_n_per_event_type(self):
        _from = OCT_13 - H
        _to = OCT_14 + H

        def detail(at, event_type, **kwargs):
            return db_mock.get_event_detail(
                timestamp=at,
                route_name='route-A',
                event_type=event_type,
                api_key_name='fake',
                **kwargs,
            )

        cache_hit = detail(OCT_13, HIT)
        latest_fallback = detail(
            OCT_14, 'FALLBACK', target='gpt-4.1', fallback='llama3.1'
        )
        guardrail = detail(
            OCT_14,
            'GUARDRAIL',
            name='PRESIDIO',
            type='READACT',
            where='INPUT',
            parameters='PARAMS',
            behavior='BLOCK',
        )
        rate_limit = detail(OCT_13, 'RATE_LIMIT')
        latest_n = self.event_dao.get_latest_n_per_event_type
        assert latest_n(None, 'route-A', 10, _from, _to) == [
            cache_hit,
            latest_fallback,
            detail(OCT_13, 'FALLBACK'),
            guardrail,
            rate_limit,
        ]
        # n caps the rows per event type, keeping the most recent.
        assert latest_n(None, 'route-A', 1, _from, _to) == [
            cache_hit,
            latest_fallback,
            guardrail,
            rate_limit,
        ]
        assert latest_n(None, 'route-C', 10, _from, _to) == []
        assert latest_n(None, 'route-A', 10, FUTURE + H, FUTURE) == []


class EventDAOTest(DatabaseIntegrationClickhouse):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.event_dao = EventDAO(cls.db)

    def test_get_latest_n_per_event_type_reads_limit_blocks(self):
        """A limit block carries the scope and category that blocked it; a
        warning (LIMIT_THRESHOLD) is no block. A row recorded before blocks
        carried their attributes reads as before.
        """
        route = 'route-limits'

        def at(hour):
            return datetime.datetime(2025, 10, 13, hour, tzinfo=UTC)

        def limit(scope, category):
            return {
                'limit_scope': scope,
                'category': category,
                'window_seconds': '3600',
                'maximum': '10.0',
                'consumption': '10.5',
            }

        self.insert(
            [
                _ev(
                    'BUDGET_LIMIT',
                    route,
                    at(10),
                    api_key_uuid=KEY_1,
                    **limit('route', 'budget'),
                ),
                _ev(
                    'CREDENTIAL_RATE_LIMIT',
                    route,
                    at(11),
                    api_key_uuid=KEY_1,
                    **limit('credential', 'request_rate'),
                ),
                _ev(
                    'PROJECT_BUDGET_LIMIT',
                    route,
                    at(12),
                    api_key_uuid=KEY_1,
                    **limit('project', 'budget'),
                ),
                _ev(
                    'LIMIT_THRESHOLD',
                    route,
                    at(13),
                    api_key_uuid=KEY_1,
                    threshold_percentage='80',
                    **limit('credential', 'budget'),
                ),
                _ev('RATE_LIMIT', route, at(14), api_key_uuid=KEY_1),
            ]
        )

        def block(event_type, hour, scope, category):
            return EventDetails(
                timestamp=at(hour),
                api_key_uuid=KEY_1,
                route_name=route,
                event_type=event_type,
                target='',
                fallback='',
                name='',
                type='',
                where='',
                parameters='',
                behavior='',
                api_key_name='fake',
                limit_scope=scope,
                category=category,
                window_seconds=3600,
                maximum=10.0,
                consumption=10.5,
            )

        assert self.event_dao.get_latest_n_per_event_type(
            None, route, 10, at(0), at(23)
        ) == [
            block('BUDGET_LIMIT', 10, 'route', 'budget'),
            block('CREDENTIAL_RATE_LIMIT', 11, 'credential', 'request_rate'),
            block('PROJECT_BUDGET_LIMIT', 12, 'project', 'budget'),
            db_mock.get_event_detail(
                timestamp=at(14),
                api_key_uuid=KEY_1,
                route_name=route,
                event_type='RATE_LIMIT',
                api_key_name='fake',
            ),
        ]

    def test_get_costs_chart_data_by_granularity_and_group_by(self):
        """Token costs are summed per (bucket, entity), ordered by both."""
        key_1, key_2 = uuid.UUID(int=1), uuid.UUID(int=2)
        group_1, group_2 = uuid.UUID(int=11), uuid.UUID(int=12)
        k1, k2, g1, g2 = str(key_1), str(key_2), str(group_1), str(group_2)
        # Powers of two keep the float sums exact.
        events = [
            # (timestamp, event_type, api key, group, model, cost)
            ((2025, 1, 6, 10, 30), 'INPUT', key_1, group_1, 'gpt-4', 1.0),
            ((2025, 1, 6, 10, 45), 'OUTPUT', key_2, group_2, 'gpt-3.5', 2.0),
            ((2025, 1, 6, 11, 15), 'OUTPUT', key_1, group_1, 'gpt-4', 4.0),
            ((2025, 1, 7, 9, 0), 'INPUT', key_2, group_1, 'gpt-4', 8.0),
            ((2025, 1, 14, 9, 0), 'INPUT', key_1, group_2, 'gpt-3.5', 16.0),
            ((2025, 2, 3, 9, 0), 'OUTPUT', key_2, group_2, 'gpt-4', 32.0),
        ]
        self.insert(
            [
                db_mock.get_sample_event(
                    event_type=f'{kind}_TOKEN_PROCESSED',
                    timestamp=datetime.datetime(*ts, tzinfo=UTC),
                    api_key_uuid=key,
                    group_uuid=group,
                    model_id=model,
                    cost=cost,
                )
                for ts, kind, key, group, model, cost in events
            ]
        )
        _from = datetime.datetime(2025, 1, 6, tzinfo=UTC)
        _to = datetime.datetime(2025, 3, 1, tzinfo=UTC)

        cases = {
            ('hours', 'keys'): [
                ((2025, 1, 6, 10), k1, 1.0),
                ((2025, 1, 6, 10), k2, 2.0),
                ((2025, 1, 6, 11), k1, 4.0),
                ((2025, 1, 7, 9), k2, 8.0),
                ((2025, 1, 14, 9), k1, 16.0),
                ((2025, 2, 3, 9), k2, 32.0),
            ],
            ('hours', 'groups'): [
                ((2025, 1, 6, 10), g1, 1.0),
                ((2025, 1, 6, 10), g2, 2.0),
                ((2025, 1, 6, 11), g1, 4.0),
                ((2025, 1, 7, 9), g1, 8.0),
                ((2025, 1, 14, 9), g2, 16.0),
                ((2025, 2, 3, 9), g2, 32.0),
            ],
            ('hours', 'models'): [
                ((2025, 1, 6, 10), 'gpt-3.5', 2.0),
                ((2025, 1, 6, 10), 'gpt-4', 1.0),
                ((2025, 1, 6, 11), 'gpt-4', 4.0),
                ((2025, 1, 7, 9), 'gpt-4', 8.0),
                ((2025, 1, 14, 9), 'gpt-3.5', 16.0),
                ((2025, 2, 3, 9), 'gpt-4', 32.0),
            ],
            ('days', 'keys'): [
                ((2025, 1, 6), k1, 5.0),
                ((2025, 1, 6), k2, 2.0),
                ((2025, 1, 7), k2, 8.0),
                ((2025, 1, 14), k1, 16.0),
                ((2025, 2, 3), k2, 32.0),
            ],
            ('days', 'models'): [
                ((2025, 1, 6), 'gpt-3.5', 2.0),
                ((2025, 1, 6), 'gpt-4', 5.0),
                ((2025, 1, 7), 'gpt-4', 8.0),
                ((2025, 1, 14), 'gpt-3.5', 16.0),
                ((2025, 2, 3), 'gpt-4', 32.0),
            ],
            ('weeks', 'groups'): [
                ((2025, 1, 6), g1, 13.0),
                ((2025, 1, 6), g2, 2.0),
                ((2025, 1, 13), g2, 16.0),
                ((2025, 2, 3), g2, 32.0),
            ],
            ('weeks', 'models'): [
                ((2025, 1, 6), 'gpt-3.5', 2.0),
                ((2025, 1, 6), 'gpt-4', 13.0),
                ((2025, 1, 13), 'gpt-3.5', 16.0),
                ((2025, 2, 3), 'gpt-4', 32.0),
            ],
            ('months', 'keys'): [
                ((2025, 1, 1), k1, 21.0),
                ((2025, 1, 1), k2, 10.0),
                ((2025, 2, 1), k2, 32.0),
            ],
        }
        for (granularity, group_by), expected in cases.items():
            with self.subTest(granularity=granularity, group_by=group_by):
                res = self.event_dao.get_costs_chart_data(
                    None, ['rb-gateway'], _from, _to, granularity, group_by
                )
                # Week and month buckets come back as naive dates.
                tz = None if granularity in ('weeks', 'months') else UTC
                assert [(r.bucket, r.group_by_value, r.total_cost) for r in res] == [
                    (datetime.datetime(*bucket, tzinfo=tz), value, cost)
                    for bucket, value, cost in expected
                ]

    def test_get_costs_chart_data_filters(self):
        k1 = str(KEY_1)
        feb_2 = datetime.datetime(2025, 2, 2, 10, 0, 0, tzinfo=UTC)
        jan_20 = NOON + 10 * D
        key = {'api_key_uuid': KEY_1}
        self.insert(
            [
                # Time range: 10:00 and 15:00 fall outside [12:00, 14:00].
                _ev(INPUT, at=NOON - 2 * H, cost=0.10, **key),
                _ev(INPUT, at=NOON, cost=0.20, **key),
                _ev(OUTPUT, at=NOON + H, cost=0.30, **key),
                _ev(INPUT, at=NOON + 2 * H, cost=0.40, **key),
                _ev(OUTPUT, at=NOON + 3 * H, cost=0.50, **key),
                # Route filters.
                _ev(INPUT, 'route-A', feb_2, 1.0, **key),
                _ev(INPUT, 'route-B', feb_2, 2.0, **key),
                _ev(INPUT, 'route-C', feb_2, 5.0, **key),
                # Decision calls are costed per model like chat calls.
                _ev(
                    INPUT,
                    at=jan_20,
                    cost=0.25,
                    model_id='jev',
                    model_type='decision_model',
                ),
                _ev(
                    INPUT, at=jan_20, cost=1.0, model_id='gpt', model_type='chat-model'
                ),
            ]
        )

        def chart(routes, _from, _to, group_by='keys'):
            res = self.event_dao.get_costs_chart_data(
                None, routes, _from, _to, 'hours', group_by
            )
            return [(r.bucket, r.group_by_value, r.total_cost) for r in res]

        assert chart(['rb-gateway'], NOON, NOON + 2 * H) == [
            (NOON, k1, 0.20),
            (NOON + H, k1, 0.30),
            (NOON + 2 * H, k1, 0.40),
        ]
        assert chart(['route-A', 'route-B'], feb_2 - H, feb_2 + H) == [(feb_2, k1, 3.0)]
        assert chart(None, feb_2 - H, feb_2 + H) == [(feb_2, k1, 8.0)]
        assert chart(['rb-gateway'], jan_20, jan_20 + H, 'models') == [
            (jan_20, 'gpt', 1.0),
            (jan_20, 'jev', 0.25),
        ]
        assert chart(['rb-gateway'], FUTURE, FUTURE + D) == []

    def test_get_summary_costs(self):
        self.insert(
            [
                # sum-plain: only [12:00, 14:00] counts; cache hits need cache_enabled.
                _ev(INPUT, 'sum-plain', NOON - 2 * H, 0.10),
                _ev(INPUT, 'sum-plain', NOON, 0.20),
                _ev(OUTPUT, 'sum-plain', NOON + H, 0.30),
                _ev(HIT, 'sum-plain', NOON + H),
                _ev(HIT, 'sum-plain', NOON + H),
                _ev(INPUT, 'sum-plain', NOON + 2 * H, 0.40),
                _ev(OUTPUT, 'sum-plain', NOON + 3 * H, 0.50),
                # sum-semantic: semantic-cache costs are not request costs.
                _ev(OUTPUT, 'sum-semantic', NOON + H, 0.50, cache_type='semantic'),
                # sum-cache: cache savings and saved tokens.
                _ev(INPUT, 'sum-cache', NOON - 2 * H, 0.10),
                _ev(CACHE_IN, 'sum-cache', NOON - 2 * H, 0.10),
                _ev(INPUT, 'sum-cache', NOON, 0.20),
                _ev(CACHE_IN, 'sum-cache', NOON, 0.15, value=40),
                _ev(OUTPUT, 'sum-cache', NOON + H, 0.30),
                _ev(CACHE_OUT, 'sum-cache', NOON + H, 0.40, value=100),
                _ev(HIT, 'sum-cache', NOON + H),
                _ev(HIT, 'sum-cache', NOON + 2 * H),
                _ev(INPUT, 'sum-cache', NOON + 2 * H, 0.40),
                _ev(CACHE_IN, 'sum-cache', NOON + 2 * H, 0.10, value=3),
                _ev(OUTPUT, 'sum-cache', NOON + 3 * H, 0.50),
                _ev(CACHE_OUT, 'sum-cache', NOON + 3 * H, 0.50, value=1000),
                # sum-cache-type: no cache type and 'exact' count, 'semantic' not.
                _ev(INPUT, 'sum-cache-type', cost=0.10),
                _ev(OUTPUT, 'sum-cache-type', cost=0.20),
                _ev(INPUT, 'sum-cache-type', cost=0.15, cache_type='exact'),
                _ev(OUTPUT, 'sum-cache-type', cost=0.25, cache_type='exact'),
                _ev(HIT, 'sum-cache-type', cache_type='exact'),
                _ev(INPUT, 'sum-cache-type', cost=1.00, cache_type='semantic'),
                _ev(OUTPUT, 'sum-cache-type', cost=2.00, cache_type='semantic'),
                _ev(HIT, 'sum-cache-type', cache_type='semantic'),
            ]
        )

        def summary(route, cache_enabled=False, with_tokens=False):
            return self.event_dao.get_summary_costs(
                None, [route], NOON, NOON + 2 * H, cache_enabled, with_tokens
            )

        assert summary('sum-plain') == CostData(
            input_cost=0.60, output_cost=0.30, total_cost=0.90
        )
        assert summary('sum-semantic') == CostData()
        assert summary('sum-cache', True, True) == CostData(
            input_cost=0.60,
            output_cost=0.30,
            total_cost=0.90,
            cache_triggered=2,
            saved_amount_input=0.25,
            saved_amount_output=0.40,
            total_saved_amount=0.65,
            cache_saved_tokens_input=43,
            cache_saved_tokens_output=100,
            total_cached_tokens=143,
        )
        assert summary('sum-cache-type') == CostData(
            input_cost=0.25, output_cost=0.45, total_cost=0.70
        )

    def test_get_semantic_cache_details(self):
        sem = {'cache_type': 'semantic'}
        self.insert(
            [
                # sem-costs: [12:00, 14:00] counts, 15:00 does not.
                _ev(INPUT, 'sem-costs', NOON, 0.10, value=40, **sem),
                _ev(HIT, 'sem-costs', NOON, **sem),
                _ev(CACHE_IN, 'sem-costs', NOON, 0.10, value=40, **sem),
                _ev(CACHE_OUT, 'sem-costs', NOON, 0.40, value=160, **sem),
                _ev(INPUT, 'sem-costs', NOON + H, 0.20, value=80, **sem),
                _ev(HIT, 'sem-costs', NOON + H, **sem),
                _ev(CACHE_IN, 'sem-costs', NOON + H, 0.20, value=80, **sem),
                _ev(CACHE_OUT, 'sem-costs', NOON + H, 0.60, value=240, **sem),
                _ev(HIT, 'sem-costs', NOON + 2 * H, **sem),
                _ev(CACHE_IN, 'sem-costs', NOON + 2 * H, 0.20, value=80, **sem),
                _ev(CACHE_OUT, 'sem-costs', NOON + 2 * H, 0.60, value=240, **sem),
                _ev(INPUT, 'sem-costs', NOON + 3 * H, 0.20, value=80, **sem),
                _ev(CACHE_IN, 'sem-costs', NOON + 3 * H, 0.20, value=80, **sem),
                _ev(CACHE_OUT, 'sem-costs', NOON + 3 * H, 0.20, value=80, **sem),
                # sem-tokens: saved tokens.
                _ev(HIT, 'sem-tokens', NOON + H, **sem),
                _ev(HIT, 'sem-tokens', NOON + 2 * H, **sem),
                _ev(HIT, 'sem-tokens', NOON + datetime.timedelta(minutes=2), **sem),
                _ev(HIT, 'sem-tokens', NOON, **sem),
                _ev(INPUT, 'sem-tokens', NOON, 0.10, value=40, **sem),
                _ev(CACHE_IN, 'sem-tokens', NOON, 0.10, value=40, **sem),
                _ev(CACHE_OUT, 'sem-tokens', NOON, 0.10, value=30, **sem),
                _ev(INPUT, 'sem-tokens', NOON + H, 0.20, value=80, **sem),
                _ev(CACHE_IN, 'sem-tokens', NOON + H, 0.20, value=80, **sem),
                _ev(CACHE_OUT, 'sem-tokens', NOON + H, 0.20, value=60, **sem),
                _ev(CACHE_IN, 'sem-tokens', NOON + 2 * H, 0.20, value=80, **sem),
                _ev(INPUT, 'sem-tokens', NOON + 3 * H, 0.20, value=80, **sem),
                _ev(CACHE_IN, 'sem-tokens', NOON + 3 * H, 0.20, value=80, **sem),
                # sem-none: no semantic-cache event at all.
                _ev(INPUT, 'sem-none', NOON + H, 0.50),
            ]
        )

        def details(route, with_tokens=False):
            return self.event_dao.get_semantic_cache_details(
                None, [route], NOON, NOON + 2 * H, with_tokens
            )

        assert details('sem-costs') == SemanticCacheCostData(
            cache_triggered=3,
            llm_input_request_savings=0.50,
            llm_output_request_savings=1.60,
            llm_total_request_savings=2.10,
            embedding_inference_cost=0.30,
            net_savings=1.80,
        )
        assert details('sem-tokens', True) == SemanticCacheCostData(
            cache_triggered=4,
            llm_input_request_savings=0.50,
            llm_output_request_savings=0.30,
            llm_total_request_savings=0.80,
            embedding_inference_cost=0.30,
            net_savings=0.50,
            cache_saved_tokens_input=200,
            cache_saved_tokens_output=90,
            total_cached_tokens=290,
        )
        assert details('sem-none') == SemanticCacheCostData(
            cache_triggered=0,
            llm_input_request_savings=0,
            llm_output_request_savings=0,
            llm_total_request_savings=0,
            embedding_inference_cost=0,
            net_savings=0,
        )

    def test_get_all_routes_summary_costs(self):
        self.insert(
            [
                _ev(INPUT, 'route-X', NOON, 0.20),
                _ev(OUTPUT, 'route-X', NOON + H, 0.30),
                _ev(HIT, 'route-X', NOON + H),
                _ev(INPUT, 'route-Y', NOON, 0.10),
                _ev(OUTPUT, 'route-Y', NOON + H, 0.15),
                # route-Z: input cost includes semantic (embedding) input.
                _ev(INPUT, 'route-Z', cost=0.10),
                _ev(INPUT, 'route-Z', cost=1.00, cache_type='semantic'),
                # route-W: exact and semantic cache side by side.
                _ev(INPUT, 'route-W', cost=0.50),
                _ev(OUTPUT, 'route-W', cost=0.30),
                _ev(CACHE_IN, 'route-W', cost=0.10, value=20, cache_type='exact'),
                _ev(CACHE_OUT, 'route-W', cost=0.05, value=10, cache_type='exact'),
                _ev(HIT, 'route-W', cache_type='exact'),
                _ev(INPUT, 'route-W', cost=0.20, cache_type='semantic'),
                _ev(CACHE_IN, 'route-W', cost=0.15, value=30, cache_type='semantic'),
                _ev(CACHE_OUT, 'route-W', cost=0.25, value=50, cache_type='semantic'),
                _ev(HIT, 'route-W', cache_type='semantic'),
                # route-T: saved tokens without a cache type.
                _ev(INPUT, 'route-T', cost=0.50),
                _ev(CACHE_IN, 'route-T', cost=0.10, value=40),
                _ev(CACHE_OUT, 'route-T', cost=0.05, value=60),
            ]
        )

        def route(name, **fields):
            zeros = dict.fromkeys(
                [
                    'cache_triggered',
                    'partial_saved_amount_input',
                    'partial_saved_amount_output',
                    'partial_saved_amount',
                    'llm_input_request_savings',
                    'llm_output_request_savings',
                    'llm_total_request_savings',
                    'embedding_inference_cost',
                    'saved_amount_input',
                    'saved_amount_output',
                    'total_saved_amount',
                ],
                0,
            )
            return RouteCostData(route_name=name, **{**zeros, **fields})

        expected = [
            route(
                'route-T',
                input_cost=0.50,
                total_cost=0.50,
                partial_saved_amount_input=0.10,
                partial_saved_amount_output=0.05,
                partial_saved_amount=0.15,
                saved_amount_input=0.10,
                saved_amount_output=0.05,
                total_saved_amount=0.15,
            ),
            route(
                'route-W',
                input_cost=0.70,
                output_cost=0.30,
                total_cost=1.00,
                cache_triggered=2,
                partial_saved_amount_input=0.10,
                partial_saved_amount_output=0.05,
                partial_saved_amount=0.15,
                llm_input_request_savings=0.15,
                llm_output_request_savings=0.25,
                llm_total_request_savings=0.40,
                embedding_inference_cost=0.20,
                saved_amount_input=0.25,
                saved_amount_output=0.30,
                # partial_saved + (llm_total - embedding_cost)
                total_saved_amount=0.35,
            ),
            route(
                'route-X',
                input_cost=0.20,
                output_cost=0.30,
                total_cost=0.50,
                cache_triggered=1,
            ),
            route('route-Y', input_cost=0.10, output_cost=0.15, total_cost=0.25),
            route(
                'route-Z',
                input_cost=1.10,
                total_cost=1.10,
                embedding_inference_cost=1.00,
                total_saved_amount=-1.00,
            ),
        ]

        def summaries(with_tokens, _from=NOON, _to=NOON + 2 * H):
            res = self.event_dao.get_all_routes_summary_costs(
                None, _from, _to, with_tokens
            )
            return sorted(res, key=lambda r: r.route_name)

        assert summaries(False) == expected
        tokens = {
            'route-T': (40, 60, 100),
            'route-W': (50, 60, 110),
            'route-X': (0, 0, 0),
            'route-Y': (0, 0, 0),
            'route-Z': (0, 0, 0),
        }
        assert summaries(True) == [
            r.model_copy(
                update=dict(
                    zip(
                        [
                            'cache_saved_tokens_input',
                            'cache_saved_tokens_output',
                            'total_cached_tokens',
                        ],
                        tokens[r.route_name],
                    )
                )
            )
            for r in expected
        ]
        assert summaries(False, FUTURE, FUTURE + H) == []

    def test_detailed_cost_breakdown(self):
        chat = [
            # (event type, cost, is_cached_tokens, is_judge)
            (INPUT, 1.0, False, False),
            (INPUT, 0.5, True, False),
            (INPUT, 0.3, False, True),
            (INPUT, 0.2, True, True),
            (OUTPUT, 2.0, False, False),
            (OUTPUT, 0.8, False, True),
        ]
        cm = {'model_type': 'chat-model'}
        emb = {'model_type': 'embeddings'}
        tr = {'model_type': 'transcription'}
        dm = {'model_type': 'decision_model'}
        self.insert(
            [
                # det-full: every chat and embedding column at once.
                *[
                    _ev(
                        kind,
                        'det-full',
                        cost=cost,
                        is_cached_tokens=c,
                        is_judge=j,
                        **cm,
                    )
                    for kind, cost, c, j in chat
                ],
                _ev(INPUT, 'det-full', cost=0.4, cache_type='', **emb),
                _ev(INPUT, 'det-full', cost=0.6, cache_type='semantic', **emb),
                # det-transcription: duration, audio, text and output columns.
                _ev(
                    INPUT,
                    'det-transcription',
                    cost=0.000825,
                    cache_type='duration',
                    **tr,
                ),
                _ev(
                    INPUT, 'det-transcription', cost=0.000492, cache_type='audio', **tr
                ),
                _ev(INPUT, 'det-transcription', cost=0.0000125, cache_type='', **tr),
                _ev(OUTPUT, 'det-transcription', cost=0.00038, **tr),
                # det-decision: input only; exact cache hits and chat input
                # must not leak into the decision column.
                _ev(INPUT, 'det-decision', cost=0.0000109, cache_type='', **dm),
                _ev(OUTPUT, 'det-decision', cost=0.0, **dm),
                _ev(
                    CACHE_IN,
                    'det-decision',
                    value=260,
                    model_id='jev',
                    cache_type='exact',
                ),
                _ev(INPUT, 'det-decision', cost=1.0, **cm),
                # One route per column family for the all-routes query.
                _ev(INPUT, 'route-A', cost=1.0, **cm),
                _ev(OUTPUT, 'route-A', cost=2.0, **cm),
                _ev(INPUT, 'route-B', cost=0.3, is_judge=True, **cm),
                _ev(OUTPUT, 'route-B', cost=0.8, is_judge=True, **cm),
                _ev(INPUT, 'route-C', cost=0.4, cache_type='', **emb),
                _ev(INPUT, 'route-C', cost=0.6, cache_type='semantic', **emb),
                _ev(INPUT, 'route-D', cost=0.000825, cache_type='duration', **tr),
                _ev(OUTPUT, 'route-D', cost=0.00038, **tr),
                _ev(INPUT, 'route-E', cost=0.0000109, **dm),
                # route-time: only the noon event is inside [11:00, 13:00].
                _ev(INPUT, 'route-time', NOON - 2 * H, 2.0, **cm),
                _ev(INPUT, 'route-time', NOON, 1.0, **cm),
                _ev(INPUT, 'route-time', NOON + 2 * H, 3.0, **cm),
                # route-all: the output falls outside the window.
                _ev(INPUT, 'route-all', NOON, 1.0, **cm),
                _ev(OUTPUT, 'route-all', NOON + 2 * H, 2.0, **cm),
            ]
        )
        _from, _to = NOON - H, NOON + H
        full = DetailedCostBreakdown(
            chat_input_direct=1.0,
            chat_input_cached=0.5,
            chat_input_judges=0.3,
            chat_input_judges_cached=0.2,
            chat_output_direct=2.0,
            chat_output_judges=0.8,
            embedding_input_total=1.0,
            embedding_input_direct=0.4,
            embedding_input_semantic_cache=0.6,
        )
        transcription = DetailedCostBreakdown(
            transcription_duration=0.000825,
            transcription_audio=0.000492,
            transcription_text=0.0000125,
            transcription_output=0.00038,
        )
        decision = DetailedCostBreakdown(
            decision_input=0.0000109, chat_input_direct=1.0
        )
        assert {
            route: self.event_dao.get_detailed_cost_breakdown(None, [route], _from, _to)
            for route in ('det-full', 'det-transcription', 'det-decision')
        } == {
            'det-full': full,
            'det-transcription': transcription,
            'det-decision': decision,
        }

        def breakdown(name, base=None, **fields):
            base_fields = base.model_dump() if base else {}
            return RouteDetailedCostBreakdown(
                route_name=name, **{**base_fields, **fields}
            )

        in_window = [
            breakdown('det-decision', decision),
            breakdown('det-full', full),
            breakdown('det-transcription', transcription),
            breakdown('route-A', chat_input_direct=1.0, chat_output_direct=2.0),
            breakdown('route-B', chat_input_judges=0.3, chat_output_judges=0.8),
            breakdown(
                'route-C',
                embedding_input_total=1.0,
                embedding_input_direct=0.4,
                embedding_input_semantic_cache=0.6,
            ),
            breakdown(
                'route-D', transcription_duration=0.000825, transcription_output=0.00038
            ),
            breakdown('route-E', decision_input=0.0000109),
        ]

        def all_routes(_from, _to):
            res = self.event_dao.get_all_routes_detailed_cost_breakdown(
                None, _from, _to
            )
            return sorted(res, key=lambda r: r.route_name)

        assert all_routes(_from, _to) == [
            *in_window,
            breakdown('route-all', chat_input_direct=1.0),
            breakdown('route-time', chat_input_direct=1.0),
        ]
        assert all_routes(None, None) == [
            *in_window,
            breakdown('route-all', chat_input_direct=1.0, chat_output_direct=2.0),
            breakdown('route-time', chat_input_direct=6.0),
        ]
        assert all_routes(FUTURE, FUTURE + H) == []

    def test_get_token_chart_data(self):
        t0 = datetime.datetime(2025, 1, 8, 10, 0, 0, tzinfo=UTC)
        self.insert(
            [
                _ev(INPUT, at=t0, value=100, model_id='gpt-4'),
                _ev(INPUT, at=t0 + H, value=150, model_id='gpt-4'),
                _ev(OUTPUT, at=t0, value=50, model_id='gpt-4'),
                _ev(OUTPUT, at=t0 + H, value=75, model_id='gpt-4'),
            ]
        )

        def chart(_from, _to):
            res = self.event_dao.get_token_chart_data(
                None, ['rb-gateway'], _from, _to, 'hours', 0
            )
            return [(r.bucket, r.event_type, r.total_tokens) for r in res]

        assert chart(t0, t0 + 2 * H) == [
            (t0, INPUT, 100),
            (t0, OUTPUT, 50),
            (t0 + H, INPUT, 150),
            (t0 + H, OUTPUT, 75),
        ]
        assert chart(t0 - D, t0 - D + 2 * H) == []

    def test_get_invocation_chart_data(self):
        t0 = datetime.datetime(2025, 1, 8, 10, 0, 0, tzinfo=UTC)
        day = datetime.datetime(2025, 1, 8, tzinfo=UTC)
        m = datetime.timedelta(minutes=1)

        def inv(route, at, model='gpt-4', event_type=INVOCATION, value=1):
            return _ev(event_type, route, at, value=value, model_id=model)

        self.insert(
            [
                inv('inv-route', t0),
                inv('inv-route', t0 + 30 * m),
                inv('inv-route', t0 + H, 'gpt-3.5-turbo'),
                inv('inv-route', t0 + H + 15 * m),
                inv('inv-route-d', day + 5 * H),
                inv('inv-route-d', day + 18 * H),
                inv('inv-route-d', day + D + 8 * H, 'gpt-3.5-turbo'),
                inv('inv-route-1', t0),
                inv('inv-route-2', t0),
                inv('inv-route-t', t0 - 2 * H),
                inv('inv-route-t', t0),
                inv('inv-route-t', t0 + 3 * H),
                # Only MODEL_INVOCATION events count.
                inv('inv-route-f', t0),
                inv('inv-route-f', t0, event_type=INPUT, value=100),
                inv('inv-route-f', t0, event_type=OUTPUT, value=50),
                inv('inv-route-no-model', t0),
                inv('inv-route-no-model', t0 + 30 * m),
                inv('inv-route-no-model', t0 + 45 * m, 'gpt-3.5-turbo'),
                inv('inv-route-no-model', t0 + H),
            ]
        )

        def chart(route, _to, granularity='hours', include_models=True, _from=t0):
            res = self.event_dao.get_invocation_chart_data(
                None, [route], _from, _to, granularity, include_models=include_models
            )
            return [(r.bucket, r.group_by_value, r.value) for r in res]

        assert chart('inv-route', t0 + 2 * H) == [
            (t0, 'gpt-4', 2),
            (t0 + H, 'gpt-3.5-turbo', 1),
            (t0 + H, 'gpt-4', 1),
        ]
        assert chart('inv-route-d', day + 3 * D, 'days', _from=day) == [
            (day, 'gpt-4', 2),
            (day + D, 'gpt-3.5-turbo', 1),
        ]
        assert chart('inv-route-1', t0 + H) == [(t0, 'gpt-4', 1)]
        assert chart('inv-route-t', t0 + H) == [(t0, 'gpt-4', 1)]
        assert chart('inv-route-f', t0 + H) == [(t0, 'gpt-4', 1)]
        # Without model grouping, all models in a bucket are summed together.
        assert chart('inv-route-no-model', t0 + 2 * H, include_models=False) == [
            (t0, 'all', 3),
            (t0 + H, 'all', 1),
        ]
        assert chart('inv-route', FUTURE + H, _from=FUTURE) == []

    def test_get_most_expensive_route(self):
        jan_11 = NOON + D
        jan_12 = NOON + 2 * D
        self.insert(
            [
                # exp: A = 3.0, B = 5.0, C = 1.0.
                _ev(INPUT, 'exp-A', cost=1.0),
                _ev(OUTPUT, 'exp-A', cost=2.0),
                _ev(INPUT, 'exp-B', cost=2.5),
                _ev(OUTPUT, 'exp-B', cost=2.5),
                _ev(INPUT, 'exp-C', cost=1.0),
                # tf: out-of-range events would flip the winner.
                _ev(INPUT, 'tf-A', jan_11, 1.0),
                _ev(INPUT, 'tf-A', jan_11 - 5 * H, 10.0),
                _ev(INPUT, 'tf-B', jan_11, 2.0),
                _ev(INPUT, 'tf-B', jan_11 + 5 * H, 20.0),
                # nf: without a time filter both events count.
                _ev(INPUT, 'nf', jan_12, 3.0),
                _ev(OUTPUT, 'nf', jan_12 + 30 * D, 4.0),
            ]
        )
        most = self.event_dao.get_most_expensive_route
        assert {
            'exp': most(None, ['exp-A', 'exp-B', 'exp-C'], NOON, NOON + H),
            'tf': most(None, ['tf-A', 'tf-B'], jan_11 - H, jan_11 + H),
            'nf': most(None, ['nf'], None, None),
            'empty': most(None, ['route-x'], FUTURE, FUTURE + H),
            'no_routes': most(None, [], None, None),
        } == {
            'exp': MostExpensiveRoute(route_name='exp-B', total_cost=5.0),
            'tf': MostExpensiveRoute(route_name='tf-B', total_cost=2.0),
            'nf': MostExpensiveRoute(route_name='nf', total_cost=7.0),
            'empty': None,
            'no_routes': None,
        }

    def test_get_cost_chart_data(self):
        feb_1 = datetime.datetime(2025, 2, 1, 10, 0, 0, tzinfo=UTC)
        self.insert(
            [
                _ev(INPUT, 'chart-cost', feb_1, 1.0),
                _ev(OUTPUT, 'chart-cost', feb_1 + datetime.timedelta(minutes=30), 2.0),
                _ev(INPUT, 'chart-cost', feb_1 + H, 3.0),
                _ev(INPUT, 'chart-r1', feb_1, 5.0),
                _ev(INPUT, 'chart-r2', feb_1, 10.0),
                _ev(INPUT, 'chart-time', feb_1, 1.0),
                _ev(INPUT, 'chart-time', feb_1 - 5 * H, 100.0),
                _ev(INPUT, 'chart-time', feb_1 + 5 * H, 100.0),
                # Non-token events are excluded.
                _ev(INPUT, 'chart-evt', feb_1, 1.0),
                _ev('RATE_LIMIT', 'chart-evt', feb_1, 50.0),
                _ev(INVOCATION, 'chart-evt', feb_1, 50.0),
            ]
        )

        def chart(route, _from=feb_1, _to=feb_1 + H):
            res = self.event_dao.get_cost_chart_data(None, route, _from, _to, 'hours')
            return [(r.bucket, r.cost) for r in res]

        assert chart('chart-cost', _to=feb_1 + 2 * H) == [
            (feb_1, 3.0),
            (feb_1 + H, 3.0),
        ]
        assert chart('chart-r1') == [(feb_1, 5.0)]
        assert chart('chart-time', feb_1 - H) == [(feb_1, 1.0)]
        assert chart('chart-evt') == [(feb_1, 1.0)]
        assert chart('chart-cost', FUTURE, FUTURE + H) == []
