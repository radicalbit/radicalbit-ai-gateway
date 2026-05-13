from unittest.mock import AsyncMock, MagicMock, patch

from freezegun import freeze_time
from langchain_core.messages import HumanMessage, SystemMessage
import pytest

from tests.common.mocked_gateway_config_openai import (
    get_gateway_routing_context_length,
    get_gateway_routing_keyword,
    get_gateway_routing_time,
    get_gateway_routing_token_length,
)

from radicalbit_ai_gateway.models.credentials import Credentials
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
        config=routing_config, models_by_id=models_by_id, budget_limiter=None
    )


@pytest.fixture
def time_router():
    config = get_gateway_routing_time()
    routing_config = config.routing_by_name['time_routing']
    route = config.routes['time_route']
    models_by_id = {mid: config.chat_models_by_id[mid] for mid in route.chat_models}
    return DeterministicRouter(
        config=routing_config, models_by_id=models_by_id, budget_limiter=None
    )


@pytest.fixture
def token_length_router():
    config = get_gateway_routing_token_length()
    routing_config = config.routing_by_name['token_routing']
    route = config.routes['smart_route']
    models_by_id = {mid: config.chat_models_by_id[mid] for mid in route.chat_models}
    return DeterministicRouter(
        config=routing_config, models_by_id=models_by_id, budget_limiter=None
    )


@pytest.fixture
def context_length_router():
    config = get_gateway_routing_context_length()
    routing_config = config.routing_by_name['context_routing']
    route = config.routes['smart_route']
    models_by_id = {mid: config.chat_models_by_id[mid] for mid in route.chat_models}
    return DeterministicRouter(
        config=routing_config, models_by_id=models_by_id, budget_limiter=None
    )


def _count_tokens_patched(token_length_router, token_count):
    return patch(
        'radicalbit_ai_gateway.routing.deterministic_router.count_tokens',
        return_value=token_count,
    )


def _make_budget_router(
    thresholds: dict[str, float], default_model_id: str, budget_limiter
):
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
        config=routing_config, models_by_id=models_by_id, budget_limiter=budget_limiter
    )


def _mock_budget_limiter(remaining: float, limit: float = 0):
    """Create a mock BudgetLimiter with given remaining budget and limit."""
    limiter = MagicMock()
    limiter.get_total_current_usage = AsyncMock(return_value=remaining)
    limiter.item = MagicMock(limit=limit) if limit else None
    return limiter


class TestDeterministicRouting:
    async def test_matches_first_keyword_entry(self, keyword_router):
        messages = [HumanMessage(content='I have a billing question')]
        result = await keyword_router.select_model(messages)
        assert result.model_id == 'billing_model'

    async def test_matches_second_keyword_entry(self, keyword_router):
        messages = [HumanMessage(content='I found a bug in the system')]
        result = await keyword_router.select_model(messages)
        assert result.model_id == 'tech_support_model'

    async def test_returns_default_when_no_match(self, keyword_router):
        messages = [HumanMessage(content='Hello, how are you?')]
        result = await keyword_router.select_model(messages)
        assert result.model_id == 'general_queue'

    async def test_case_insensitive_matching(self, keyword_router):
        messages = [HumanMessage(content='BILLING issue')]
        result = await keyword_router.select_model(messages)
        assert result.model_id == 'billing_model'

    async def test_only_last_human_message_is_checked(self, keyword_router):
        messages = [
            HumanMessage(content='I need help with my invoice'),
            HumanMessage(content='Hello'),
        ]
        result = await keyword_router.select_model(messages)
        assert result.model_id == 'general_queue'

    async def test_keyword_in_last_message_matches(self, keyword_router):
        messages = [
            HumanMessage(content='Hello'),
            HumanMessage(content='I need help with my invoice'),
        ]
        result = await keyword_router.select_model(messages)
        assert result.model_id == 'billing_model'

    async def test_ignores_non_human_messages(self, keyword_router):
        messages = [
            SystemMessage(content='You handle billing questions'),
            HumanMessage(content='Hello, general question'),
        ]
        result = await keyword_router.select_model(messages)
        assert result.model_id == 'general_queue'

    async def test_first_mapping_entry_wins(self, keyword_router):
        messages = [HumanMessage(content='billing error')]
        result = await keyword_router.select_model(messages)
        assert result.model_id == 'billing_model'

    async def test_multipart_last_message_matches(self, keyword_router):
        messages = [
            HumanMessage(content='billing error'),
            HumanMessage(
                content=[
                    {
                        'role': 'user',
                        'content': [
                            {'type': 'text', 'text': 'im carlo'},
                            {'type': 'text', 'text': 'I have a billing question'},
                        ],
                    }
                ]
            ),
        ]
        result = await keyword_router.select_model(messages)
        assert result.model_id == 'billing_model'

    # --- token_length routing tests (config: gpt-4o-mini lte:199, gpt-4.1 between:[200,799]) ---
    # 0-199 → gpt-4o-mini, 200-799 → gpt-4.1, 800+ → default (gpt-4o)

    async def test_lte_matches_low_value(self, token_length_router):
        with _count_tokens_patched(token_length_router, 100):
            result = await token_length_router.select_model(
                [HumanMessage(content='short')]
            )
        assert result.model_id == 'gpt-4o-mini'

    async def test_between_matches_mid_value(self, token_length_router):
        with _count_tokens_patched(token_length_router, 300):
            result = await token_length_router.select_model(
                [HumanMessage(content='medium')]
            )
        assert result.model_id == 'gpt-4.1'

    async def test_default_when_above_all(self, token_length_router):
        with _count_tokens_patched(token_length_router, 900):
            result = await token_length_router.select_model(
                [HumanMessage(content='long')]
            )
        assert result.model_id == 'gpt-4o'

    async def test_lte_exact_upper_bound(self, token_length_router):
        with _count_tokens_patched(token_length_router, 199):
            result = await token_length_router.select_model(
                [HumanMessage(content='prompt')]
            )
        assert result.model_id == 'gpt-4o-mini'

    async def test_between_exact_lower_bound(self, token_length_router):
        with _count_tokens_patched(token_length_router, 200):
            result = await token_length_router.select_model(
                [HumanMessage(content='prompt')]
            )
        assert result.model_id == 'gpt-4.1'

    async def test_between_exact_upper_bound(self, token_length_router):
        with _count_tokens_patched(token_length_router, 799):
            result = await token_length_router.select_model(
                [HumanMessage(content='prompt')]
            )
        assert result.model_id == 'gpt-4.1'

    async def test_default_just_above_between(self, token_length_router):
        with _count_tokens_patched(token_length_router, 800):
            result = await token_length_router.select_model(
                [HumanMessage(content='prompt')]
            )
        assert result.model_id == 'gpt-4o'

    async def test_default_on_empty_messages(self, token_length_router):
        with _count_tokens_patched(token_length_router, 0):
            result = await token_length_router.select_model([])
        assert result.model_id == 'gpt-4o'

    async def test_lte_checked_before_between(self, token_length_router):
        # lte:199 matches before between:[200,799] for low values
        with _count_tokens_patched(token_length_router, 50):
            result = await token_length_router.select_model(
                [HumanMessage(content='prompt')]
            )
        assert result.model_id == 'gpt-4o-mini'

    # --- context_length routing tests (config: gpt-4o-mini between:[200,399], gpt-4.1 gte:400) ---

    async def test_context_length_routes_to_default_when_below_all_conditions(
        self, context_length_router
    ):
        with _count_tokens_patched(context_length_router, 100):
            result = await context_length_router.select_model(
                [HumanMessage(content='short')]
            )
        assert result.model_id == 'gpt-4o'

    async def test_context_length_routes_to_mid_model_when_in_between_range(
        self, context_length_router
    ):
        with _count_tokens_patched(context_length_router, 300):
            result = await context_length_router.select_model(
                [HumanMessage(content='medium')]
            )
        assert result.model_id == 'gpt-4o-mini'

    async def test_context_length_routes_to_top_model_when_above_gte(
        self, context_length_router
    ):
        with _count_tokens_patched(context_length_router, 500):
            result = await context_length_router.select_model(
                [HumanMessage(content='long')]
            )
        assert result.model_id == 'gpt-4.1'

    async def test_context_length_exact_lower_bound(self, context_length_router):
        with _count_tokens_patched(context_length_router, 200):
            result = await context_length_router.select_model(
                [HumanMessage(content='prompt')]
            )
        assert result.model_id == 'gpt-4o-mini'

    async def test_context_length_exact_gte(self, context_length_router):
        with _count_tokens_patched(context_length_router, 400):
            result = await context_length_router.select_model(
                [HumanMessage(content='prompt')]
            )
        assert result.model_id == 'gpt-4.1'

    async def test_context_length_default_on_empty_messages(
        self, context_length_router
    ):
        with _count_tokens_patched(context_length_router, 0):
            result = await context_length_router.select_model([])
        assert result.model_id == 'gpt-4o'

    async def test_context_length_considers_all_messages(self, context_length_router):
        """Key difference from token_length: multiple messages are concatenated."""
        with _count_tokens_patched(context_length_router, 300):
            result = await context_length_router.select_model(
                [
                    SystemMessage(content='You are a helpful assistant.'),
                    HumanMessage(content='First question'),
                    HumanMessage(content='Follow-up question'),
                ]
            )
        assert result.model_id == 'gpt-4o-mini'

    async def test_context_length_includes_system_messages(self, context_length_router):
        """System messages contribute to the total context length."""
        with _count_tokens_patched(context_length_router, 500):
            result = await context_length_router.select_model(
                [
                    SystemMessage(content='Long system prompt'),
                    HumanMessage(content='Short user message'),
                ]
            )
        assert result.model_id == 'gpt-4.1'

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

    # --- token_length condition validation tests ---

    def test_rejects_entry_with_no_condition_set(self):
        with pytest.raises(ValueError, match='exactly one of gte, lte, or between'):
            DeterministicRoutingConfig(
                name='test',
                default_model_id='default',
                rule=RoutingRuleType.TOKEN_LENGTH,
                output_mapping=[
                    OutputMappingEntry(
                        model_id='m1',
                        conditions=TokenLengthConditions(),
                    )
                ],
            )

    def test_rejects_entry_with_multiple_conditions_set(self):
        with pytest.raises(ValueError, match='exactly one of gte, lte, or between'):
            DeterministicRoutingConfig(
                name='test',
                default_model_id='default',
                rule=RoutingRuleType.TOKEN_LENGTH,
                output_mapping=[
                    OutputMappingEntry(
                        model_id='m1',
                        conditions=TokenLengthConditions(gte=100, lte=200),
                    )
                ],
            )

    def test_rejects_between_with_wrong_order(self):
        with pytest.raises(ValueError, match='between\\[0\\] <= between\\[1\\]'):
            DeterministicRoutingConfig(
                name='test',
                default_model_id='default',
                rule=RoutingRuleType.TOKEN_LENGTH,
                output_mapping=[
                    OutputMappingEntry(
                        model_id='m1',
                        conditions=TokenLengthConditions(between=[500, 100]),
                    )
                ],
            )

    def test_accepts_overlapping_gte_conditions(self):
        """Two gte entries are fine — router sorts them deterministically."""
        DeterministicRoutingConfig(
            name='test',
            default_model_id='default',
            rule=RoutingRuleType.TOKEN_LENGTH,
            output_mapping=[
                OutputMappingEntry(
                    model_id='m1',
                    conditions=TokenLengthConditions(gte=200),
                ),
                OutputMappingEntry(
                    model_id='m2',
                    conditions=TokenLengthConditions(gte=400),
                ),
            ],
        )

    def test_rejects_overlapping_between_and_gte(self):
        with pytest.raises(ValueError, match='overlapping conditions'):
            DeterministicRoutingConfig(
                name='test',
                default_model_id='default',
                rule=RoutingRuleType.TOKEN_LENGTH,
                output_mapping=[
                    OutputMappingEntry(
                        model_id='m1',
                        conditions=TokenLengthConditions(between=[100, 500]),
                    ),
                    OutputMappingEntry(
                        model_id='m2',
                        conditions=TokenLengthConditions(gte=300),
                    ),
                ],
            )

    def test_rejects_overlapping_between_ranges(self):
        with pytest.raises(ValueError, match='overlapping conditions'):
            DeterministicRoutingConfig(
                name='test',
                default_model_id='default',
                rule=RoutingRuleType.TOKEN_LENGTH,
                output_mapping=[
                    OutputMappingEntry(
                        model_id='m1',
                        conditions=TokenLengthConditions(between=[100, 500]),
                    ),
                    OutputMappingEntry(
                        model_id='m2',
                        conditions=TokenLengthConditions(between=[400, 800]),
                    ),
                ],
            )

    def test_rejects_overlapping_lte_and_between(self):
        with pytest.raises(ValueError, match='overlapping conditions'):
            DeterministicRoutingConfig(
                name='test',
                default_model_id='default',
                rule=RoutingRuleType.TOKEN_LENGTH,
                output_mapping=[
                    OutputMappingEntry(
                        model_id='m1',
                        conditions=TokenLengthConditions(lte=500),
                    ),
                    OutputMappingEntry(
                        model_id='m2',
                        conditions=TokenLengthConditions(between=[300, 800]),
                    ),
                ],
            )

    def test_accepts_mixed_condition_types(self):
        DeterministicRoutingConfig(
            name='test',
            default_model_id='default',
            rule=RoutingRuleType.TOKEN_LENGTH,
            output_mapping=[
                OutputMappingEntry(
                    model_id='m1',
                    conditions=TokenLengthConditions(lte=999),
                ),
                OutputMappingEntry(
                    model_id='m2',
                    conditions=TokenLengthConditions(between=[1000, 4999]),
                ),
                OutputMappingEntry(
                    model_id='m3',
                    conditions=TokenLengthConditions(gte=5000),
                ),
            ],
        )

    # --- lte condition routing tests ---

    async def test_lte_condition_matches(self):
        models_by_id = {
            mid: Model(
                model_id=mid,
                model='openai/gpt-4o',
                credentials=Credentials(api_key='sk-dummy'),
            )
            for mid in ['default', 'small']
        }
        config = DeterministicRoutingConfig(
            name='test',
            default_model_id='default',
            rule=RoutingRuleType.TOKEN_LENGTH,
            output_mapping=[
                OutputMappingEntry(
                    model_id='small',
                    conditions=TokenLengthConditions(lte=500),
                ),
            ],
        )
        router = DeterministicRouter(
            config=config, models_by_id=models_by_id, budget_limiter=None
        )
        with patch(
            'radicalbit_ai_gateway.routing.deterministic_router.count_tokens',
            return_value=200,
        ):
            result = await router.select_model([HumanMessage(content='hi')])
        assert result.model_id == 'small'

    async def test_lte_condition_no_match(self):
        models_by_id = {
            mid: Model(
                model_id=mid,
                model='openai/gpt-4o',
                credentials=Credentials(api_key='sk-dummy'),
            )
            for mid in ['default', 'small']
        }
        config = DeterministicRoutingConfig(
            name='test',
            default_model_id='default',
            rule=RoutingRuleType.TOKEN_LENGTH,
            output_mapping=[
                OutputMappingEntry(
                    model_id='small',
                    conditions=TokenLengthConditions(lte=500),
                ),
            ],
        )
        router = DeterministicRouter(
            config=config, models_by_id=models_by_id, budget_limiter=None
        )
        with patch(
            'radicalbit_ai_gateway.routing.deterministic_router.count_tokens',
            return_value=600,
        ):
            result = await router.select_model([HumanMessage(content='hi')])
        assert result.model_id == 'default'

    # --- between condition routing tests ---

    async def test_between_condition_matches(self):
        models_by_id = {
            mid: Model(
                model_id=mid,
                model='openai/gpt-4o',
                credentials=Credentials(api_key='sk-dummy'),
            )
            for mid in ['default', 'mid']
        }
        config = DeterministicRoutingConfig(
            name='test',
            default_model_id='default',
            rule=RoutingRuleType.TOKEN_LENGTH,
            output_mapping=[
                OutputMappingEntry(
                    model_id='mid',
                    conditions=TokenLengthConditions(between=[100, 500]),
                ),
            ],
        )
        router = DeterministicRouter(
            config=config, models_by_id=models_by_id, budget_limiter=None
        )
        with patch(
            'radicalbit_ai_gateway.routing.deterministic_router.count_tokens',
            return_value=300,
        ):
            result = await router.select_model([HumanMessage(content='hi')])
        assert result.model_id == 'mid'

    async def test_between_condition_no_match(self):
        models_by_id = {
            mid: Model(
                model_id=mid,
                model='openai/gpt-4o',
                credentials=Credentials(api_key='sk-dummy'),
            )
            for mid in ['default', 'mid']
        }
        config = DeterministicRoutingConfig(
            name='test',
            default_model_id='default',
            rule=RoutingRuleType.TOKEN_LENGTH,
            output_mapping=[
                OutputMappingEntry(
                    model_id='mid',
                    conditions=TokenLengthConditions(between=[100, 500]),
                ),
            ],
        )
        router = DeterministicRouter(
            config=config, models_by_id=models_by_id, budget_limiter=None
        )
        with patch(
            'radicalbit_ai_gateway.routing.deterministic_router.count_tokens',
            return_value=600,
        ):
            result = await router.select_model([HumanMessage(content='hi')])
        assert result.model_id == 'default'

    # --- mixed condition routing tests ---

    async def test_mixed_conditions_routing(self):
        """Verify correct model selection with lte, between, and gte conditions."""
        model_ids = ['default', 'small', 'mid', 'large']
        models_by_id = {
            mid: Model(
                model_id=mid,
                model='openai/gpt-4o',
                credentials=Credentials(api_key='sk-dummy'),
            )
            for mid in model_ids
        }
        config = DeterministicRoutingConfig(
            name='test',
            default_model_id='default',
            rule=RoutingRuleType.TOKEN_LENGTH,
            output_mapping=[
                OutputMappingEntry(
                    model_id='small',
                    conditions=TokenLengthConditions(lte=999),
                ),
                OutputMappingEntry(
                    model_id='mid',
                    conditions=TokenLengthConditions(between=[1000, 4999]),
                ),
                OutputMappingEntry(
                    model_id='large',
                    conditions=TokenLengthConditions(gte=5000),
                ),
            ],
        )
        router = DeterministicRouter(
            config=config, models_by_id=models_by_id, budget_limiter=None
        )
        # token_count=500 → lte:999 matches
        with patch(
            'radicalbit_ai_gateway.routing.deterministic_router.count_tokens',
            return_value=500,
        ):
            result = await router.select_model([HumanMessage(content='hi')])
        assert result.model_id == 'small'

        # token_count=2500 → between:[1000,4999] matches
        with patch(
            'radicalbit_ai_gateway.routing.deterministic_router.count_tokens',
            return_value=2500,
        ):
            result = await router.select_model([HumanMessage(content='hi')])
        assert result.model_id == 'mid'

        # token_count=6000 → gte:5000 matches
        with patch(
            'radicalbit_ai_gateway.routing.deterministic_router.count_tokens',
            return_value=6000,
        ):
            result = await router.select_model([HumanMessage(content='hi')])
        assert result.model_id == 'large'

    @freeze_time('2026-02-23 10:00:00', tz_offset=0)  # Monday 10am UTC
    async def test_matches_first_time_entry(self, time_router):
        result = await time_router.select_model([HumanMessage(content='hello')])
        assert result.model_id == 'weekday_model'

    @freeze_time('2026-02-23 03:00:00', tz_offset=0)  # Monday 3am UTC
    async def test_matches_second_time_entry(self, time_router):
        result = await time_router.select_model([HumanMessage(content='hello')])
        assert result.model_id == 'night_model'

    @freeze_time('2026-02-21 10:00:00', tz_offset=0)  # Saturday 10am UTC
    async def test_returns_default_when_no_time_match(self, time_router):
        result = await time_router.select_model([HumanMessage(content='hello')])
        assert result.model_id == 'default_model'

    @freeze_time('2026-02-23 10:00:00', tz_offset=0)  # Monday 10am UTC
    async def test_sequential_evaluation_first_wins(self, time_router):
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
            config=routing_config, models_by_id=models_by_id, budget_limiter=None
        )
        result = await router.select_model([HumanMessage(content='hello')])
        assert result.model_id == 'night_model'

    @freeze_time('2026-02-23 20:00:00', tz_offset=0)  # Monday 8pm UTC
    async def test_multiple_conditions_any_matches(self, time_router):
        """night_model has two cron conditions; the evening one should match."""
        result = await time_router.select_model([HumanMessage(content='hello')])
        assert result.model_id == 'night_model'

    async def test_returns_default_when_no_budget_limiter(self):
        router = _make_budget_router(
            thresholds={'cheap': 0.6, 'cheaper': 0.8},
            default_model_id='default',
            budget_limiter=None,
        )
        result = await router.select_model([HumanMessage(content='hello')])
        assert result.model_id == 'default'

    async def test_returns_default_when_max_budget_is_zero(self):
        limiter = _mock_budget_limiter(remaining=0, limit=0)
        router = _make_budget_router(
            thresholds={'cheap': 0.6},
            default_model_id='default',
            budget_limiter=limiter,
        )
        result = await router.select_model([HumanMessage(content='hello')])
        assert result.model_id == 'default'

    async def test_returns_default_when_usage_below_all_thresholds(self):
        # remaining=90, max_budget=100 → usage_ratio = 1 - 90/100 = 0.10
        limiter = _mock_budget_limiter(remaining=90, limit=100)
        router = _make_budget_router(
            thresholds={'cheap': 0.6, 'cheaper': 0.8},
            default_model_id='default',
            budget_limiter=limiter,
        )
        result = await router.select_model([HumanMessage(content='hello')])
        assert result.model_id == 'default'

    async def test_matches_lower_threshold(self):
        # remaining=30, max_budget=100 → usage_ratio = 1 - 30/100 = 0.70
        # 0.70 >= 0.6 (cheap) but < 0.8 (cheaper)
        limiter = _mock_budget_limiter(remaining=30, limit=100)
        router = _make_budget_router(
            thresholds={'cheap': 0.6, 'cheaper': 0.8},
            default_model_id='default',
            budget_limiter=limiter,
        )
        result = await router.select_model([HumanMessage(content='hello')])
        assert result.model_id == 'cheap'

    async def test_matches_higher_threshold(self):
        # remaining=10, max_budget=100 → usage_ratio = 1 - 10/100 = 0.90
        # 0.90 >= 0.8 (cheaper) — highest threshold wins
        limiter = _mock_budget_limiter(remaining=10, limit=100)
        router = _make_budget_router(
            thresholds={'cheap': 0.6, 'cheaper': 0.8},
            default_model_id='default',
            budget_limiter=limiter,
        )
        result = await router.select_model([HumanMessage(content='hello')])
        assert result.model_id == 'cheaper'

    async def test_matches_at_exact_threshold(self):
        # remaining=40, max_budget=100 → usage_ratio = 1 - 40/100 = 0.60
        limiter = _mock_budget_limiter(remaining=40, limit=100)
        router = _make_budget_router(
            thresholds={'cheap': 0.6},
            default_model_id='default',
            budget_limiter=limiter,
        )
        result = await router.select_model([HumanMessage(content='hello')])
        assert result.model_id == 'cheap'

    async def test_uses_combined_input_and_output_limits(self):
        # remaining=20, max_budget=50+50=100 → usage_ratio = 1 - 20/100 = 0.80
        limiter = _mock_budget_limiter(remaining=20, limit=100)
        router = _make_budget_router(
            thresholds={'cheap': 0.6, 'cheaper': 0.8},
            default_model_id='default',
            budget_limiter=limiter,
        )
        result = await router.select_model([HumanMessage(content='hello')])
        assert result.model_id == 'cheaper'

    async def test_highest_threshold_checked_first_regardless_of_config_order(self):
        # remaining=5, max_budget=100 → usage_ratio = 0.95
        # Both thresholds match, but 0.8 is checked first (sorted desc) → cheaper wins
        limiter = _mock_budget_limiter(remaining=5, limit=100)
        router = _make_budget_router(
            thresholds={'cheap': 0.6, 'cheaper': 0.8},
            default_model_id='default',
            budget_limiter=limiter,
        )
        result = await router.select_model([HumanMessage(content='hello')])
        assert result.model_id == 'cheaper'

    async def test_fully_exhausted_budget(self):
        # remaining=0, max_budget=100 → usage_ratio = 1.0
        limiter = _mock_budget_limiter(remaining=0, limit=100)
        router = _make_budget_router(
            thresholds={'cheap': 0.6, 'cheaper': 0.8},
            default_model_id='default',
            budget_limiter=limiter,
        )
        result = await router.select_model([HumanMessage(content='hello')])
        assert result.model_id == 'cheaper'
