from unittest.mock import patch

from freezegun import freeze_time
import pytest

from tests.common.mocked_gateway_config_openai import (
    get_gateway_routing_context_length,
    get_gateway_routing_keyword,
    get_gateway_routing_time,
    get_gateway_routing_token_length,
)

from radicalbit_ai_gateway.limiter import ScenarioType, WindowConfig
from radicalbit_ai_gateway.limiting.limits import shared_limits
from radicalbit_ai_gateway.limiting.windows import Category, Window
from radicalbit_ai_gateway.llm.messages import HumanMessage, SystemMessage
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.models.event_payload import LimitScope
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.routing import (
    BudgetConditions,
    DeterministicRoutingConfig,
    OutputMappingEntry,
    RoutingRuleType,
    TokenLengthConditions,
)
from radicalbit_ai_gateway.routing.deterministic_router import DeterministicRouter


@pytest.fixture
def keyword_router():
    config = get_gateway_routing_keyword()
    routing_config = config.routing_by_name['keyword_routing']
    route = config.routes['support_route']
    models_by_id = {mid: config.chat_models_by_id[mid] for mid in route.chat_models}
    return DeterministicRouter(
        config=routing_config, models_by_id=models_by_id, budget=None
    )


@pytest.fixture
def time_router():
    config = get_gateway_routing_time()
    routing_config = config.routing_by_name['time_routing']
    route = config.routes['time_route']
    models_by_id = {mid: config.chat_models_by_id[mid] for mid in route.chat_models}
    return DeterministicRouter(
        config=routing_config, models_by_id=models_by_id, budget=None
    )


@pytest.fixture
def token_length_router():
    config = get_gateway_routing_token_length()
    routing_config = config.routing_by_name['token_routing']
    route = config.routes['smart_route']
    models_by_id = {mid: config.chat_models_by_id[mid] for mid in route.chat_models}
    return DeterministicRouter(
        config=routing_config, models_by_id=models_by_id, budget=None
    )


@pytest.fixture
def context_length_router():
    config = get_gateway_routing_context_length()
    routing_config = config.routing_by_name['context_routing']
    route = config.routes['smart_route']
    models_by_id = {mid: config.chat_models_by_id[mid] for mid in route.chat_models}
    return DeterministicRouter(
        config=routing_config, models_by_id=models_by_id, budget=None
    )


def _count_tokens_patched(token_length_router, token_count):
    return patch(
        'radicalbit_ai_gateway.routing.deterministic_router.count_tokens',
        return_value=token_count,
    )


def _make_budget_router(thresholds: dict[str, float], default_model_id: str, budget):
    """Build a DeterministicRouter with budget rule from a {model_id: threshold} mapping."""
    models_by_id = {
        mid: Model(
            model_id=mid,
            model='openai/gpt-4o',
            credentials=Credentials(api_key='sk-dummy'),
        )
        for mid in [*thresholds.keys(), default_model_id]
    }
    output_mapping = [
        OutputMappingEntry(model_id=mid, conditions=BudgetConditions(threshold=thr))
        for mid, thr in thresholds.items()
    ]
    routing_config = DeterministicRoutingConfig(
        name='budget_test',
        default_model_id=default_model_id,
        rule=RoutingRuleType.BUDGET,
        output_mapping=output_mapping,
    )
    return DeterministicRouter(
        config=routing_config, models_by_id=models_by_id, budget=budget
    )


async def _budget_window(remaining: int, limit: int = 0) -> Window:
    """Return a route budget window of ``limit`` with ``remaining`` left."""
    window = Window(
        scope=LimitScope.ROUTE,
        category=Category.COST,
        config=WindowConfig.from_parts(
            limit=limit,
            window='1 hour',
            project_uuid='project',
            route_name='route',
            scenario_type=ScenarioType.BUDGET,
        ),
        aligned=False,
        shown_value=limit,
        shown_window='1 hour',
    )
    if limit - remaining:
        limiter = window.limiter(shared_limits.storage)
        await limiter.consume(window.config, cost=limit - remaining)
    return window


def _make_token_router(conditions: dict[str, TokenLengthConditions]):
    """Build a token_length DeterministicRouter from a {model_id: conditions} mapping."""
    models_by_id = {
        mid: Model(
            model_id=mid,
            model='openai/gpt-4o',
            credentials=Credentials(api_key='sk-dummy'),
        )
        for mid in ['default', *conditions]
    }
    config = _token_length_config(conditions)
    return DeterministicRouter(config=config, models_by_id=models_by_id, budget=None)


def _token_length_config(conditions: dict[str, TokenLengthConditions]):
    return DeterministicRoutingConfig(
        name='test',
        default_model_id='default',
        rule=RoutingRuleType.TOKEN_LENGTH,
        output_mapping=[
            OutputMappingEntry(model_id=mid, conditions=cond)
            for mid, cond in conditions.items()
        ],
    )


_MULTIPART_BILLING = HumanMessage(
    content=[
        {
            'role': 'user',
            'content': [
                {'type': 'text', 'text': 'im carlo'},
                {'type': 'text', 'text': 'I have a billing question'},
            ],
        }
    ]
)

_MIXED = {
    'small': TokenLengthConditions(lte=999),
    'mid': TokenLengthConditions(between=[1000, 4999]),
    'large': TokenLengthConditions(gte=5000),
}


class TestDeterministicRouting:
    @pytest.mark.parametrize(
        ('messages', 'expected'),
        [
            pytest.param(
                [HumanMessage(content='I have a billing question')],
                'billing_model',
                id='first-keyword-entry',
            ),
            pytest.param(
                [HumanMessage(content='I found a bug in the system')],
                'tech_support_model',
                id='second-keyword-entry',
            ),
            pytest.param(
                [HumanMessage(content='Hello, how are you?')],
                'general_queue',
                id='default-when-no-match',
            ),
            pytest.param(
                [HumanMessage(content='BILLING issue')],
                'billing_model',
                id='case-insensitive',
            ),
            pytest.param(
                [
                    HumanMessage(content='I need help with my invoice'),
                    HumanMessage(content='Hello'),
                ],
                'general_queue',
                id='only-last-human-message-checked',
            ),
            pytest.param(
                [
                    HumanMessage(content='Hello'),
                    HumanMessage(content='I need help with my invoice'),
                ],
                'billing_model',
                id='keyword-in-last-message',
            ),
            pytest.param(
                [
                    SystemMessage(content='You handle billing questions'),
                    HumanMessage(content='Hello, general question'),
                ],
                'general_queue',
                id='ignores-non-human-messages',
            ),
            pytest.param(
                [HumanMessage(content='billing error')],
                'billing_model',
                id='first-mapping-entry-wins',
            ),
            pytest.param(
                [HumanMessage(content='billing error'), _MULTIPART_BILLING],
                'billing_model',
                id='multipart-last-message',
            ),
        ],
    )
    async def test_keyword_routing_selects_model(
        self, keyword_router, messages, expected
    ):
        result = await keyword_router.select_model(messages)
        assert result.model_id == expected

    # token_length config: gpt-4o-mini lte:199, gpt-4.1 between:[200,799], default gpt-4o
    @pytest.mark.parametrize(
        ('token_count', 'messages', 'expected'),
        [
            pytest.param(
                100, [HumanMessage(content='short')], 'gpt-4o-mini', id='lte-low'
            ),
            pytest.param(
                300, [HumanMessage(content='medium')], 'gpt-4.1', id='between-mid'
            ),
            pytest.param(
                900, [HumanMessage(content='long')], 'gpt-4o', id='default-above-all'
            ),
            pytest.param(
                199,
                [HumanMessage(content='prompt')],
                'gpt-4o-mini',
                id='lte-upper-bound',
            ),
            pytest.param(
                200,
                [HumanMessage(content='prompt')],
                'gpt-4.1',
                id='between-lower-bound',
            ),
            pytest.param(
                799,
                [HumanMessage(content='prompt')],
                'gpt-4.1',
                id='between-upper-bound',
            ),
            pytest.param(
                800,
                [HumanMessage(content='prompt')],
                'gpt-4o',
                id='default-just-above-between',
            ),
            pytest.param(0, [], 'gpt-4o', id='default-on-empty-messages'),
        ],
    )
    async def test_token_length_routing_selects_model(
        self, token_length_router, token_count, messages, expected
    ):
        with _count_tokens_patched(token_length_router, token_count):
            result = await token_length_router.select_model(messages)
        assert result.model_id == expected

    # context_length config: gpt-4o-mini between:[200,399], gpt-4.1 gte:400, default gpt-4o
    @pytest.mark.parametrize(
        ('token_count', 'messages', 'expected'),
        [
            pytest.param(
                100, [HumanMessage(content='short')], 'gpt-4o', id='default-below-all'
            ),
            pytest.param(
                300, [HumanMessage(content='medium')], 'gpt-4o-mini', id='between-range'
            ),
            pytest.param(
                500, [HumanMessage(content='long')], 'gpt-4.1', id='above-gte'
            ),
            pytest.param(
                200,
                [HumanMessage(content='prompt')],
                'gpt-4o-mini',
                id='between-lower-bound',
            ),
            pytest.param(
                400, [HumanMessage(content='prompt')], 'gpt-4.1', id='exact-gte'
            ),
            pytest.param(0, [], 'gpt-4o', id='default-on-empty-messages'),
        ],
    )
    async def test_context_length_routing_selects_model(
        self, context_length_router, token_count, messages, expected
    ):
        with _count_tokens_patched(context_length_router, token_count):
            result = await context_length_router.select_model(messages)
        assert result.model_id == expected

    async def test_context_length_calls_build_user_content_with_all_messages(
        self, context_length_router
    ):
        """Verify context_length uses build_user_content (all messages), not _last_human_text."""
        messages = [
            SystemMessage(content='system'),
            HumanMessage(content='first'),
            HumanMessage(content='second'),
        ]
        with (
            patch(
                'radicalbit_ai_gateway.routing.deterministic_router.build_user_content',
                return_value='all messages',
            ) as mock_build,
            _count_tokens_patched(context_length_router, 100),
        ):
            await context_length_router.select_model(messages)
        mock_build.assert_called_once_with(messages)

    @pytest.mark.parametrize(
        ('conditions', 'match'),
        [
            pytest.param(
                {'m1': TokenLengthConditions()},
                'exactly one of gte, lte, or between',
                id='no-condition-set',
            ),
            pytest.param(
                {'m1': TokenLengthConditions(gte=100, lte=200)},
                'exactly one of gte, lte, or between',
                id='multiple-conditions-set',
            ),
            pytest.param(
                {'m1': TokenLengthConditions(between=[500, 100])},
                'between\\[0\\] <= between\\[1\\]',
                id='between-wrong-order',
            ),
            pytest.param(
                {
                    'm1': TokenLengthConditions(between=[100, 500]),
                    'm2': TokenLengthConditions(gte=300),
                },
                'overlapping conditions',
                id='overlapping-between-and-gte',
            ),
            pytest.param(
                {
                    'm1': TokenLengthConditions(between=[100, 500]),
                    'm2': TokenLengthConditions(between=[400, 800]),
                },
                'overlapping conditions',
                id='overlapping-between-ranges',
            ),
            pytest.param(
                {
                    'm1': TokenLengthConditions(lte=500),
                    'm2': TokenLengthConditions(between=[300, 800]),
                },
                'overlapping conditions',
                id='overlapping-lte-and-between',
            ),
        ],
    )
    def test_token_length_config_rejects_invalid_conditions(self, conditions, match):
        with pytest.raises(ValueError, match=match):
            _token_length_config(conditions)

    def test_token_length_config_accepts_two_gte_entries(self):
        """Two gte entries are fine: the router sorts them deterministically.

        Mixed condition types are accepted too: the routing cases build _MIXED.
        """
        config = _token_length_config(
            {'m1': TokenLengthConditions(gte=200), 'm2': TokenLengthConditions(gte=400)}
        )
        assert [e.model_id for e in config.output_mapping] == ['m1', 'm2']

    @pytest.mark.parametrize(
        ('conditions', 'token_count', 'expected'),
        [
            pytest.param(
                {'small': TokenLengthConditions(lte=500)}, 200, 'small', id='lte-match'
            ),
            pytest.param(
                {'small': TokenLengthConditions(lte=500)},
                600,
                'default',
                id='lte-no-match',
            ),
            pytest.param(
                {'mid': TokenLengthConditions(between=[100, 500])},
                300,
                'mid',
                id='between-match',
            ),
            pytest.param(
                {'mid': TokenLengthConditions(between=[100, 500])},
                600,
                'default',
                id='between-no-match',
            ),
            pytest.param(_MIXED, 500, 'small', id='mixed-lte'),
            pytest.param(_MIXED, 2500, 'mid', id='mixed-between'),
            pytest.param(_MIXED, 6000, 'large', id='mixed-gte'),
        ],
    )
    async def test_token_length_condition_routing(
        self, conditions, token_count, expected
    ):
        router = _make_token_router(conditions)
        with patch(
            'radicalbit_ai_gateway.routing.deterministic_router.count_tokens',
            return_value=token_count,
        ):
            result = await router.select_model([HumanMessage(content='hi')])
        assert result.model_id == expected

    @pytest.mark.parametrize(
        ('now', 'expected'),
        [
            pytest.param(
                '2026-02-23 10:00:00', 'weekday_model', id='monday-10am-first-entry'
            ),
            pytest.param(
                '2026-02-23 03:00:00', 'night_model', id='monday-3am-second-entry'
            ),
            pytest.param('2026-02-21 10:00:00', 'default_model', id='saturday-default'),
            # night_model has two cron conditions; the evening one matches.
            pytest.param(
                '2026-02-23 20:00:00', 'night_model', id='monday-8pm-any-condition'
            ),
        ],
    )
    async def test_time_routing_selects_model(self, time_router, now, expected):
        with freeze_time(now, tz_offset=0):
            result = await time_router.select_model([HumanMessage(content='hello')])
        assert result.model_id == expected

    @freeze_time('2026-02-23 10:00:00', tz_offset=0)  # Monday 10am UTC
    async def test_sequential_evaluation_first_wins(self):
        """When multiple entries could match, the first one wins."""
        config = get_gateway_routing_time()
        routing_config = config.routing_by_name['time_routing']

        routing_config.output_mapping.insert(
            0,
            OutputMappingEntry(model_id='night_model', conditions=['0 9-17 * * 1-5']),
        )
        route = config.routes['time_route']
        models_by_id = {mid: config.chat_models_by_id[mid] for mid in route.chat_models}
        router = DeterministicRouter(
            config=routing_config, models_by_id=models_by_id, budget=None
        )
        result = await router.select_model([HumanMessage(content='hello')])
        assert result.model_id == 'night_model'

    # usage_ratio = 1 - remaining / limit; the highest matching threshold wins.
    @pytest.mark.parametrize(
        ('window', 'thresholds', 'expected'),
        [
            pytest.param(
                None,
                {'cheap': 0.6, 'cheaper': 0.8},
                'default',
                id='route-has-no-budget',
            ),
            pytest.param((0, 0), {'cheap': 0.6}, 'default', id='max-budget-zero'),
            pytest.param(
                (90, 100),
                {'cheap': 0.6, 'cheaper': 0.8},
                'default',
                id='usage-0.10-below-all',
            ),
            pytest.param(
                (30, 100),
                {'cheap': 0.6, 'cheaper': 0.8},
                'cheap',
                id='usage-0.70-lower-threshold',
            ),
            pytest.param(
                (10, 100),
                {'cheap': 0.6, 'cheaper': 0.8},
                'cheaper',
                id='usage-0.90-higher-threshold',
            ),
            pytest.param(
                (40, 100), {'cheap': 0.6}, 'cheap', id='usage-0.60-exact-threshold'
            ),
            pytest.param(
                (20, 100),
                {'cheap': 0.6, 'cheaper': 0.8},
                'cheaper',
                id='usage-0.80-combined-limits',
            ),
            pytest.param(
                (0, 100),
                {'cheap': 0.6, 'cheaper': 0.8},
                'cheaper',
                id='fully-exhausted',
            ),
        ],
    )
    async def test_budget_routing_selects_model(self, window, thresholds, expected):
        budget = None
        if window is not None:
            remaining, limit = window
            budget = await _budget_window(remaining=remaining, limit=limit)
        router = _make_budget_router(
            thresholds=thresholds, default_model_id='default', budget=budget
        )
        result = await router.select_model([HumanMessage(content='hello')])
        assert result.model_id == expected
