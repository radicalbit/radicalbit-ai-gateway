from radicalbit_ai_gateway.limiting.route_limit_consistency import (
    LimitMax,
    route_limit_warnings,
)
from radicalbit_ai_gateway.models.credential_limiting import (
    CredentialLimitCategory,
    RouteLimitConsistencyWarning,
)
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.limiting import (
    BudgetLimiting,
    Limiting,
    LimitingAlgorithmType,
    RateLimiting,
    TokenLimiting,
)

RATE = CredentialLimitCategory.RATE
FIXED = LimitingAlgorithmType.FIXED_WINDOW


def _route(**limiting) -> GatewayRouteConfig:
    return GatewayRouteConfig(route_name='chat', **limiting)


def _rate_route(max_requests: int, window_size: int | str = '1 minute'):
    return _route(
        rate_limiting=RateLimiting(max_requests=max_requests, window_size=window_size)
    )


def test_a_credential_limit_looser_than_a_route_warns_with_both_values():
    warnings = route_limit_warnings(
        [LimitMax(RATE, FIXED, '1 minute', 100)], {'proj/chat': _rate_route(50)}
    )

    assert warnings == [
        RouteLimitConsistencyWarning(
            category=RATE,
            algorithm=FIXED,
            route_name='proj/chat',
            credential_value=100,
            credential_window_size='1 minute',
            route_value=50,
            route_window_size='1 minute',
        )
    ]


def test_an_equal_or_stricter_credential_limit_does_not_warn():
    routes = {'proj/chat': _rate_route(50)}

    assert route_limit_warnings([LimitMax(RATE, FIXED, '1 minute', 50)], routes) == []
    assert route_limit_warnings([LimitMax(RATE, FIXED, '1 minute', 10)], routes) == []


def test_windows_of_different_sizes_compare_by_rate():
    """50 / minute is 3000 / hour: 3000 / hour is not looser, 3001 / hour is."""
    routes = {'proj/chat': _rate_route(50)}

    assert route_limit_warnings([LimitMax(RATE, FIXED, '1 hour', 3000)], routes) == []
    assert (
        len(route_limit_warnings([LimitMax(RATE, FIXED, '1 hour', 3001)], routes)) == 1
    )


def test_a_route_window_in_seconds_is_named_in_its_largest_unit():
    warnings = route_limit_warnings(
        [LimitMax(RATE, FIXED, '1 minute', 100)], {'proj/chat': _rate_route(50, 3600)}
    )

    assert warnings[0].route_window_size == '1 hour'


def test_a_route_without_a_limit_of_that_category_does_not_warn():
    routes = {'proj/chat': _route(budget_limiting=BudgetLimiting(max_budget=1))}

    assert route_limit_warnings([LimitMax(RATE, FIXED, '1 minute', 100)], routes) == []


def test_input_and_output_tokens_are_compared_with_their_own_side():
    routes = {
        'proj/chat': _route(
            token_limiting=TokenLimiting(input=Limiting(max_tokens=100))
        )
    }

    warnings = route_limit_warnings(
        [
            LimitMax(CredentialLimitCategory.TOKEN_INPUT, FIXED, '1 minute', 200),
            LimitMax(CredentialLimitCategory.TOKEN_OUTPUT, FIXED, '1 minute', 200),
        ],
        routes,
    )

    assert [w.category for w in warnings] == [CredentialLimitCategory.TOKEN_INPUT]


def test_a_budget_is_compared_with_the_route_budget():
    routes = {
        'proj/chat': _route(
            budget_limiting=BudgetLimiting(max_budget=10, window_size='1 day')
        )
    }

    warnings = route_limit_warnings(
        [LimitMax(CredentialLimitCategory.BUDGET, FIXED, '1 day', 25.5)], routes
    )

    assert warnings[0].credential_value == 25.5
    assert warnings[0].route_value == 10


def test_a_zero_route_budget_makes_any_credential_budget_looser():
    routes = {'proj/chat': _route(budget_limiting=BudgetLimiting(max_budget=0))}

    warnings = route_limit_warnings(
        [LimitMax(CredentialLimitCategory.BUDGET, FIXED, '1 day', 1)], routes
    )

    assert len(warnings) == 1


def test_each_route_gets_its_own_warning():
    routes = {
        'proj/strict': _rate_route(10),
        'proj/lenient': _rate_route(1000),
        'other/strict': _rate_route(20),
    }

    warnings = route_limit_warnings([LimitMax(RATE, FIXED, '1 minute', 100)], routes)

    assert [w.route_name for w in warnings] == ['proj/strict', 'other/strict']


def test_no_routes_no_warnings():
    assert route_limit_warnings([LimitMax(RATE, FIXED, '1 minute', 100)], {}) == []


def test_a_saved_window_without_a_unit_is_skipped_not_an_error():
    routes = {'proj/chat': _rate_route(50)}

    assert route_limit_warnings([LimitMax(RATE, FIXED, '60', 100)], routes) == []
