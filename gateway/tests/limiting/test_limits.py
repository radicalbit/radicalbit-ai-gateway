import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from freezegun import freeze_time
import pytest

from radicalbit_ai_gateway.db.dao.project_budget_limit_dao import ProjectBudgetLimitDAO
from radicalbit_ai_gateway.db.tables.project_budget_limit_table import (
    ProjectBudgetLimit,
)
from radicalbit_ai_gateway.limiter import InMemoryStorage
from radicalbit_ai_gateway.limiting.limits import (
    Demand,
    InputEstimate,
    Limits,
    RouteLimits,
    Usage,
    load_project_limits,
)
from radicalbit_ai_gateway.limiting.windows import (
    Category,
    credential_window,
    project_window,
)
from radicalbit_ai_gateway.models.credential_limiting import (
    CredentialLimitCategory,
    CredentialLimitOut,
)
from radicalbit_ai_gateway.models.event_dto import WindowStatus
from radicalbit_ai_gateway.models.event_payload import LimitScope
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.limiting import LimitingAlgorithmType
from radicalbit_ai_gateway.models.project_budget_limiting import ProjectBudgetLimitOut
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.utils.exceptions import (
    AudioDurationLimitExceeded,
    BudgetLimitExceededError,
    InputTokenLimitExceeded,
    OutputTokenLimitExceeded,
    RequestRateLimitExceeded,
)
from radicalbit_ai_gateway.utils.trace_attributes import OperationCategory

P = '2f1c6d4e-0000-4000-8000-0000000000aa'
C = '7a3b9e10-0000-4000-8000-0000000000bb'
MODEL = 'openai/gpt-4o'

IDENTITY = RequestIdentity(
    request_uuid='req-1',
    route_name='my-route',
    api_key_uuid=C,
    api_key_name='my-cred',
    group_uuid='grp-1',
    group_name='my-group',
    project_uuid=P,
    project_name='my-project',
)


@pytest.fixture(autouse=True)
def events():
    emitted = []
    with (
        patch(
            'radicalbit_ai_gateway.limiting.limits.emit_event',
            side_effect=emitted.append,
        ),
        patch(
            'radicalbit_ai_gateway.limiting.limit_event.emit_event',
            side_effect=emitted.append,
        ),
    ):
        yield emitted


def _route(**limits) -> RouteLimits:
    config = GatewayRouteConfig.model_validate(
        {'route_name': 'my-route', 'chat_models': ['m'], **limits}
    )
    return RouteLimits.from_config(config, P)


def _credential_limit(
    category, value, window_size='1 minute', algorithm='FIXED_WINDOW'
):
    return CredentialLimitOut(
        uuid=uuid4(),
        category=category,
        algorithm=algorithm,
        window_size=window_size,
        value=value,
        created_at='2026-01-01 00:00:00',
        updated_at='2026-01-01 00:00:00',
    )


def _project_limit(value, window_size='1 minute'):
    return ProjectBudgetLimitOut(
        uuid=uuid4(),
        algorithm=LimitingAlgorithmType.FIXED_WINDOW,
        window_size=window_size,
        value=value,
        created_at='2026-01-01 00:00:00',
        updated_at='2026-01-01 00:00:00',
    )


def _model(input_price=None, output_price=None, **prices):
    return SimpleNamespace(
        input_cost_per_token=input_price,
        output_cost_per_token=output_price,
        input_cost_per_second=prices.get('per_second'),
        input_cost_per_audio_token=prices.get('per_audio_token'),
    )


@pytest.fixture
def limits():
    return Limits(InMemoryStorage())


def _scope(limits, route=None, credential=(), project=(), identity=IDENTITY):
    return limits.resolve(identity, route or RouteLimits(), credential, project)


async def _consumed(limits, window) -> int:
    stats = await window.limiter(limits.storage).get_window_stats(window.config)
    return stats.consumed


RATE = {'rate_limiting': {'max_requests': 2, 'window_size': '1 minute'}}
INPUT = {'token_limiting': {'input': {'max_token': 10, 'window_size': '1 minute'}}}
OUTPUT = {'token_limiting': {'output': {'max_token': 10, 'window_size': '1 minute'}}}
BUDGET = {'budget_limiting': {'max_budget': 1.0, 'window_size': '1 minute'}}
AUDIO = {'duration_limiting': {'max_duration_seconds': 10, 'window_size': '1 minute'}}


class TestNoLimits:
    @pytest.mark.asyncio
    async def test_nothing_is_checked_or_counted(self, limits, events):
        scope = _scope(limits)
        demand = Demand(
            request=True,
            input=InputEstimate('hello', MODEL),
            output_room=True,
            cost_room=True,
            audio_seconds=3,
        )
        assert not scope.applies(demand)
        await scope.check(demand)
        await scope.count(Usage(10, 10, (10,)))
        assert events == []

    @pytest.mark.asyncio
    async def test_a_limit_only_applies_to_its_category(self, limits):
        scope = _scope(limits, _route(**OUTPUT))
        assert not scope.applies(Demand(request=True, cost_room=True))
        assert scope.applies(Demand(output_room=True))


class TestOperationCategory:
    """A check that tests a limit is visible in the trace; one that tests none is not."""

    @pytest.mark.asyncio
    async def test_a_check_that_tests_a_limit_marks_the_operation(self, limits):
        with patch(
            'radicalbit_ai_gateway.limiting.limits.set_operation_category'
        ) as mark:
            await _scope(limits, _route(**RATE)).check(Demand(request=True))
        mark.assert_called_once_with(OperationCategory.LIMITING)

    @pytest.mark.asyncio
    async def test_a_check_that_tests_no_limit_does_not(self, limits):
        with patch(
            'radicalbit_ai_gateway.limiting.limits.set_operation_category'
        ) as mark:
            await _scope(limits, _route(**OUTPUT)).check(Demand(request=True))
        mark.assert_not_called()


class TestRequests:
    @pytest.mark.asyncio
    async def test_counted_when_checked_and_blocked_past_the_maximum(self, limits):
        route = _route(**RATE)
        for _ in range(2):
            await _scope(limits, route).check(Demand(request=True))
        with pytest.raises(RequestRateLimitExceeded):
            await _scope(limits, route).check(Demand(request=True))
        assert await _consumed(limits, route.windows[0]) == 2

    @pytest.mark.asyncio
    async def test_a_blocked_window_consumes_nothing_on_its_scope(self, limits):
        """Two credential rate limits: the tighter blocks, neither is counted."""
        credential = [
            _credential_limit(CredentialLimitCategory.RATE, 1, '1 minute'),
            _credential_limit(CredentialLimitCategory.RATE, 100, '1 hour'),
        ]
        await _scope(limits, credential=credential).check(Demand(request=True))
        scope = _scope(limits, credential=credential)
        with pytest.raises(RequestRateLimitExceeded):
            await scope.check(Demand(request=True))
        hourly = credential_window(C, 'request_rate', 'FIXED_WINDOW', '1 hour')
        assert await _consumed(limits, hourly) == 1

    @pytest.mark.asyncio
    async def test_the_credential_is_counted_before_the_route_is_checked(self, limits):
        """As before the limits were one module: a request the route blocks
        still counts on the credential.
        """
        route = _route(rate_limiting={'max_requests': 1, 'window_size': '1 minute'})
        credential = [_credential_limit(CredentialLimitCategory.RATE, 10)]
        await _scope(limits, route, credential).check(Demand(request=True))
        with pytest.raises(RequestRateLimitExceeded) as error:
            await _scope(limits, route, credential).check(Demand(request=True))
        assert 'Credential' not in error.value.client_message
        window = credential_window(C, 'request_rate', 'FIXED_WINDOW', '1 minute')
        assert await _consumed(limits, window) == 2

    @pytest.mark.asyncio
    async def test_the_credential_is_checked_first(self, limits):
        route = _route(rate_limiting={'max_requests': 1, 'window_size': '1 minute'})
        credential = [_credential_limit(CredentialLimitCategory.RATE, 1)]
        await _scope(limits, route, credential).check(Demand(request=True))
        with pytest.raises(RequestRateLimitExceeded) as error:
            await _scope(limits, route, credential).check(Demand(request=True))
        assert error.value.client_message.startswith('Credential rate limit')


class TestInputTokens:
    @pytest.mark.asyncio
    async def test_the_estimate_blocks_what_would_exceed(self, limits):
        scope = _scope(limits, _route(**INPUT))
        with (
            patch(
                'radicalbit_ai_gateway.limiting.limits.count_tokens', return_value=11
            ),
            pytest.raises(InputTokenLimitExceeded),
        ):
            await scope.check(Demand(input=InputEstimate('long', MODEL)))

    @pytest.mark.asyncio
    async def test_a_check_consumes_nothing(self, limits):
        route = _route(**INPUT)
        await _scope(limits, route).check(Demand(input=InputEstimate('hi', MODEL)))
        assert await _consumed(limits, route.windows[0]) == 0

    @pytest.mark.asyncio
    async def test_the_text_is_tokenized_once_for_every_limit(self, limits):
        credential = [_credential_limit(CredentialLimitCategory.TOKEN_INPUT, 100)]
        scope = _scope(limits, _route(**INPUT), credential)
        with patch(
            'radicalbit_ai_gateway.limiting.limits.count_tokens', return_value=3
        ) as count_tokens:
            await scope.check(Demand(input=InputEstimate('hello', MODEL)))
        count_tokens.assert_called_once_with('hello', MODEL)

    @pytest.mark.asyncio
    async def test_nothing_is_tokenized_without_an_input_limit(self, limits):
        scope = _scope(limits, _route(**BUDGET))
        with patch('radicalbit_ai_gateway.limiting.limits.count_tokens') as count:
            await scope.check(
                Demand(input=InputEstimate('hello', MODEL), cost_room=True)
            )
        count.assert_not_called()

    @pytest.mark.asyncio
    async def test_room_blocks_only_a_full_counter(self, limits):
        route = _route(**INPUT)
        scope = _scope(limits, route)
        await scope.count(Usage(input_tokens=9))
        await scope.check(Demand(input='room'))
        await scope.count(Usage(input_tokens=1))
        with pytest.raises(InputTokenLimitExceeded) as error:
            await scope.check(Demand(input='room'))
        assert '[attempted=1]' in error.value.log_message


class TestOutputTokensAndCost:
    @pytest.mark.asyncio
    async def test_output_room_blocks_only_a_full_counter(self, limits):
        scope = _scope(limits, _route(**OUTPUT))
        await scope.count(Usage(input_tokens=5, output_tokens=10))
        with pytest.raises(OutputTokenLimitExceeded):
            await scope.check(Demand(output_room=True))

    @pytest.mark.asyncio
    async def test_cost_room_blocks_a_spent_budget(self, limits):
        scope = _scope(limits, _route(**BUDGET))
        await scope.count(Usage.priced(_model(0.5), 2))
        with pytest.raises(BudgetLimitExceededError):
            await scope.check(Demand(cost_room=True))

    @pytest.mark.asyncio
    async def test_a_zero_budget_blocks_every_request(self, limits):
        scope = _scope(
            limits, _route(budget_limiting={'max_budget': 0, 'window_size': '1 day'})
        )
        with pytest.raises(BudgetLimitExceededError):
            await scope.check(Demand(cost_room=True))

    @pytest.mark.asyncio
    async def test_count_goes_past_the_maximum_without_raising(self, limits):
        route = _route(**OUTPUT)
        await _scope(limits, route).count(Usage(output_tokens=25))
        assert await _consumed(limits, route.windows[0]) == 25


class TestAudioSeconds:
    @pytest.mark.asyncio
    async def test_counted_when_checked_rounded(self, limits):
        route = _route(**AUDIO)
        await _scope(limits, route).check(Demand(audio_seconds=4.6))
        assert await _consumed(limits, route.windows[0]) == 5

    @pytest.mark.asyncio
    async def test_blocks_what_would_exceed(self, limits):
        route = _route(**AUDIO)
        await _scope(limits, route).check(Demand(audio_seconds=8))
        with pytest.raises(AudioDurationLimitExceeded):
            await _scope(limits, route).check(Demand(audio_seconds=3))
        assert await _consumed(limits, route.windows[0]) == 8

    @pytest.mark.asyncio
    async def test_an_unknown_duration_passes_uncounted(self, limits, caplog):
        route = _route(**AUDIO)
        await _scope(limits, route).check(Demand(audio_seconds='unknown'))
        assert await _consumed(limits, route.windows[0]) == 0
        assert 'duration_not_determinable' in caplog.text

    @pytest.mark.asyncio
    async def test_requests_that_passed_one_test_are_tested_again_as_counted(
        self, limits
    ):
        """Two transcriptions test the limit before the cache lookup, both
        pass, then both miss: the second one counted would exceed the limit,
        so it gets the limit's error instead of being counted.
        """
        route = _route(**AUDIO)
        first, second = _scope(limits, route), _scope(limits, route)
        demand = Demand(audio_seconds=6)
        await first.check(demand, count=False)
        await second.check(demand, count=False)

        await first.count_checked(demand)
        with pytest.raises(AudioDurationLimitExceeded):
            await second.count_checked(demand)
        assert await _consumed(limits, route.windows[0]) == 6


class TestUsage:
    def test_priced_costs_each_priced_part(self):
        usage = Usage.priced(_model(0.001, 0.002), 10, 20)
        assert usage == Usage(10, 20, (10_000_000, 40_000_000))

    def test_an_unpriced_part_costs_nothing(self):
        assert Usage.priced(_model(None, 0.002), 10, 20).costs == (40_000_000,)
        assert Usage.priced(_model(0.001), 10).costs == (10_000_000,)

    def test_transcription_by_duration(self):
        usage = SimpleNamespace(type='duration', seconds=12.5)
        assert Usage.transcription(_model(per_second='0.0001'), usage) == Usage(
            costs=(1_250_000,)
        )
        assert Usage.transcription(_model(), usage) == Usage()

    def test_transcription_by_tokens(self):
        usage = SimpleNamespace(
            type='tokens',
            input_tokens=30,
            output_tokens=5,
            input_token_details=SimpleNamespace(audio_tokens=20, text_tokens=10),
        )
        model = _model(0.001, 0.002, per_audio_token=0.003)
        assert Usage.transcription(model, usage) == Usage(
            costs=(60_000_000, 10_000_000, 10_000_000)
        )

    def test_transcription_without_usage(self):
        assert Usage.transcription(_model(0.1), None) == Usage()


class TestCount:
    @pytest.mark.asyncio
    async def test_every_scope_counts_its_categories(self, limits):
        route = _route(**INPUT, **BUDGET)
        credential = [
            _credential_limit(CredentialLimitCategory.TOKEN_OUTPUT, 100),
            _credential_limit(CredentialLimitCategory.BUDGET, 1),
        ]
        project = [_project_limit(1)]
        scope = _scope(limits, route, credential, project)
        await scope.count(Usage.priced(_model(0.001, 0.002), 3, 4))

        assert [await _consumed(limits, w) for w in route.windows] == [3, 11_000_000]
        assert [
            await _consumed(
                limits, credential_window(C, 'token_output', 'FIXED_WINDOW', '1 minute')
            ),
            await _consumed(
                limits, credential_window(C, 'budget', 'FIXED_WINDOW', '1 minute')
            ),
            await _consumed(limits, project_window(P, 'FIXED_WINDOW', '1 minute')),
        ] == [4, 11_000_000, 11_000_000]

    @pytest.mark.asyncio
    async def test_charge_call_counts_like_the_request(self, limits):
        route = _route(**INPUT, **BUDGET)
        await _scope(limits, route).charge_call(_model(0.001, 0.002), 3, 4)
        assert [await _consumed(limits, w) for w in route.windows] == [3, 11_000_000]

    @pytest.mark.asyncio
    async def test_threshold_events_carry_the_scope(self, limits, events):
        credential = [_credential_limit(CredentialLimitCategory.TOKEN_INPUT, 10)]
        await _scope(limits, credential=credential).count(Usage(input_tokens=10))
        assert events
        assert {(e.event_type, e.limit_scope, e.category) for e in events} == {
            (EventType.LIMIT_THRESHOLD, LimitScope.CREDENTIAL, 'token_input')
        }


class TestOrder:
    """Which limit is reported when several would block."""

    @staticmethod
    async def _blocking(limits, demand, route, credential=(), project=()):
        scope = _scope(limits, route, credential, project)
        await scope.count(Usage(10, 10, (10_000_000_000,)))
        with pytest.raises(Exception) as error:
            await scope.check(demand)
        return error.value.client_message.split(' limit')[0]

    @pytest.mark.asyncio
    async def test_credential_then_project_then_route(self, limits):
        route = _route(**INPUT, **BUDGET)
        credential = [_credential_limit(CredentialLimitCategory.BUDGET, 1)]
        project = [_project_limit(1)]
        demand = Demand(input=InputEstimate('hi', MODEL), cost_room=True)
        assert await self._blocking(limits, demand, route, credential, project) == (
            'Credential budget'
        )
        assert await self._blocking(limits, demand, route, (), project) == (
            'Project budget'
        )

    @pytest.mark.asyncio
    async def test_input_before_budget_on_a_scope(self, limits):
        route = _route(**INPUT, **BUDGET)
        demand = Demand(input=InputEstimate('hi', MODEL), cost_room=True)
        assert await self._blocking(limits, demand, route) == 'Input token'

    @pytest.mark.asyncio
    async def test_room_checks_the_budgets_before_the_input(self, limits):
        route = _route(**INPUT, **BUDGET)
        credential = [_credential_limit(CredentialLimitCategory.TOKEN_INPUT, 1)]
        demand = Demand(input='room', cost_room=True)
        assert await self._blocking(limits, demand, route, credential) == 'Budget'


class TestLimits:
    def test_resolve_keys_the_credential_and_project_windows(self, limits):
        scope = _scope(
            limits,
            credential=[_credential_limit(CredentialLimitCategory.RATE, 1)],
            project=[_project_limit(1)],
        )
        assert [w.key for w in scope._windows] == [
            f'limiter:{C}:*:request_rate:fixed:60',
            f'limiter:{P}:*:budget:fixed:60',
        ]

    @pytest.mark.asyncio
    async def test_usage_ratio(self, limits):
        route = _route(**BUDGET)
        window = route.window(Category.COST)
        assert await limits.usage_ratio(window) == 0
        await _scope(limits, route).count(Usage.priced(_model(0.25), 1))
        assert await limits.usage_ratio(window) == 0.25

    @pytest.mark.asyncio
    async def test_clear_resets_the_counter(self, limits):
        credential = [_credential_limit(CredentialLimitCategory.BUDGET, 1)]
        await _scope(limits, credential=credential).count(Usage(costs=(5,)))
        window = credential_window(C, 'budget', 'FIXED_WINDOW', '1 minute')
        assert await _consumed(limits, window) == 5
        await limits.clear(window)
        assert await _consumed(limits, window) == 0

    @pytest.mark.asyncio
    async def test_a_new_max_keeps_what_was_consumed_in_the_window(self, limits):
        await _scope(
            limits, credential=[_credential_limit(CredentialLimitCategory.RATE, 1)]
        ).check(Demand(request=True))
        await _scope(
            limits, credential=[_credential_limit(CredentialLimitCategory.RATE, 2)]
        ).check(Demand(request=True))
        with pytest.raises(RequestRateLimitExceeded):
            await _scope(
                limits, credential=[_credential_limit(CredentialLimitCategory.RATE, 2)]
            ).check(Demand(request=True))

    @pytest.mark.asyncio
    async def test_two_projects_do_not_share_a_route_window(self, limits):
        config = GatewayRouteConfig.model_validate(
            {'route_name': 'my-route', 'chat_models': ['m'], **RATE}
        )
        other = RouteLimits.from_config(config, str(uuid4()))
        for _ in range(2):
            await _scope(limits, _route(**RATE)).check(Demand(request=True))
        await _scope(limits, other).check(Demand(request=True))

    @pytest.mark.asyncio
    async def test_window_resets(self, limits):
        route = _route(**RATE)
        with freeze_time('2026-01-01 00:00:00') as frozen:
            for _ in range(2):
                await _scope(limits, route).check(Demand(request=True))
            frozen.tick(61)
            await _scope(limits, route).check(Demand(request=True))


class TestLoadProjectLimits:
    @staticmethod
    def _row():
        return ProjectBudgetLimit(
            uuid=uuid4(),
            project_uuid=uuid4(),
            algorithm=LimitingAlgorithmType.FIXED_WINDOW.value,
            window_size='1 day',
            max_value=10.0,
            created_at='2026-01-01 00:00:00',
            updated_at='2026-01-01 00:00:00',
        )

    @pytest.mark.asyncio
    async def test_no_project_has_no_limits(self):
        dao = MagicMock(spec_set=ProjectBudgetLimitDAO)
        assert await load_project_limits('', dao) == []
        dao.get_by_project_uuid.assert_not_called()

    @pytest.mark.asyncio
    async def test_reads_the_limits_off_the_event_loop_on_every_call(self):
        loop_thread = threading.get_ident()
        query_threads = []

        def get_by_project_uuid(_):
            query_threads.append(threading.get_ident())
            return [self._row()]

        dao = MagicMock(spec_set=ProjectBudgetLimitDAO)
        dao.get_by_project_uuid = get_by_project_uuid
        [limit] = await load_project_limits(P, dao)
        await load_project_limits(P, dao)

        assert limit.value == 10.0
        assert len(query_threads) == 2
        assert loop_thread not in query_threads


class _CountingStorage(InMemoryStorage):
    """Record each call made to the storage: each is a round trip to Redis.

    In memory, a batch call loops over the single ones: only the outer call
    is recorded.
    """

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []
        self._in_call = False


def _recorded(name: str):
    async def call(self, *args, **kwargs):
        outer = not self._in_call
        if outer:
            self.calls.append(name)
            self._in_call = True
        try:
            return await getattr(InMemoryStorage, name)(self, *args, **kwargs)
        finally:
            if outer:
                self._in_call = False

    return call


for _name in ('get', 'get_many', 'get_ttl', 'get_window_id', 'increment'):
    setattr(_CountingStorage, _name, _recorded(_name))
_CountingStorage.increment_many = _recorded('increment_many')


class TestRoundTrips:
    """With a limit on every scope and category, a request still makes one
    round trip per step: 4, 7 and 10 when each counter was its own.
    """

    @pytest.fixture
    def storage(self):
        return _CountingStorage()

    @pytest.fixture
    def scope(self, storage):
        route = _route(
            rate_limiting={'max_requests': 100, 'window_size': '1 hour'},
            token_limiting={
                'input': {'max_token': 10**6, 'window_size': '1 hour'},
                'output': {'max_token': 10**6, 'window_size': '1 hour'},
            },
            budget_limiting={'max_budget': 100, 'window_size': '1 hour'},
        )
        credential = [
            _credential_limit(CredentialLimitCategory.RATE, 100),
            _credential_limit(CredentialLimitCategory.TOKEN_INPUT, 10**6),
            _credential_limit(CredentialLimitCategory.TOKEN_OUTPUT, 10**6),
            _credential_limit(CredentialLimitCategory.BUDGET, 100),
        ]
        return _scope(Limits(storage), route, credential, [_project_limit(100)])

    @pytest.mark.asyncio
    async def test_admission_reads_once_and_counts_once(self, storage, scope):
        await scope.check(Demand(request=True))
        assert storage.calls == ['get_many', 'increment_many']

    @pytest.mark.asyncio
    async def test_a_chat_check_reads_once(self, storage, scope):
        await scope.check(
            Demand(
                input=InputEstimate('hello', MODEL), output_room=True, cost_room=True
            )
        )
        assert storage.calls == ['get_many']

    @pytest.mark.asyncio
    async def test_a_count_writes_once(self, storage, scope):
        await scope.count(Usage.priced(_model(0.000001, 0.000002), 10, 20))
        assert storage.calls == ['increment_many']

    @pytest.mark.asyncio
    async def test_a_block_reads_its_window_state_too(self, storage):
        scope = _scope(
            Limits(storage),
            _route(budget_limiting={'max_budget': 1, 'window_size': '1 day'}),
        )
        await scope.count(Usage(costs=(2_000_000_000,)))
        storage.calls.clear()
        with pytest.raises(BudgetLimitExceededError):
            await scope.check(Demand(cost_room=True))
        # The state of the blocking window goes into its error and event.
        assert storage.calls == ['get_many', 'get', 'get_ttl', 'get_window_id']


class TestConsumption:
    """What the limits lists and modals show (AG-1082): the counters requests
    write, read without consuming them, keyed by limit uuid.
    """

    @pytest.mark.asyncio
    async def test_reports_what_a_credential_consumed(self, limits):
        rate = _credential_limit(CredentialLimitCategory.RATE, 10)
        budget = _credential_limit(
            CredentialLimitCategory.BUDGET,
            2.0,
            window_size='1 hour',
            algorithm=LimitingAlgorithmType.ALIGNED_FIXED_WINDOW,
        )
        scope = _scope(limits, credential=[rate, budget])
        for _ in range(3):
            await scope.check(Demand(request=True))
        await scope.count(Usage.priced(_model(0.0019), 1000, 0))

        consumption = await limits.consumption(
            {
                str(limit.uuid): credential_window(
                    C,
                    limit.category.value,
                    limit.algorithm,
                    limit.window_size,
                    limit.value,
                )
                for limit in (rate, budget)
            }
        )

        assert set(consumption) == {str(rate.uuid), str(budget.uuid)}
        rate_bar = consumption[str(rate.uuid)]
        assert rate_bar.window_size == 10
        assert rate_bar.window_filled_size == 3
        assert rate_bar.window_filled_percentage == pytest.approx(30.0)
        assert rate_bar.window_status == WindowStatus.OK
        budget_bar = consumption[str(budget.uuid)]
        assert budget_bar.window_size == pytest.approx(2.0)
        assert budget_bar.window_filled_size == pytest.approx(1.9)
        assert budget_bar.window_filled_percentage == pytest.approx(95.0)
        assert budget_bar.window_status == WindowStatus.CRITICAL
        assert budget_bar.window_end_time == (int(time.time()) // 3600 + 1) * 3600

    @pytest.mark.asyncio
    async def test_reports_what_a_project_spent(self, limits):
        daily = ProjectBudgetLimitOut(
            uuid=uuid4(),
            algorithm=LimitingAlgorithmType.ALIGNED_FIXED_WINDOW,
            window_size='1 day',
            value=40.0,
            created_at='2026-01-01 00:00:00',
            updated_at='2026-01-01 00:00:00',
        )
        hourly = _project_limit(5.0, window_size='1 hour')
        scope = _scope(limits, project=[daily, hourly])
        await scope.count(Usage.priced(_model(0.002, 0.002), 1000, 1000))

        consumption = await limits.consumption(
            {
                str(limit.uuid): project_window(
                    P, limit.algorithm, limit.window_size, limit.value
                )
                for limit in (daily, hourly)
            }
        )

        assert set(consumption) == {str(daily.uuid), str(hourly.uuid)}
        daily_bar = consumption[str(daily.uuid)]
        assert daily_bar.window_size == pytest.approx(40.0)
        assert daily_bar.window_filled_size == pytest.approx(4.0)
        assert daily_bar.window_filled_percentage == pytest.approx(10.0)
        assert daily_bar.window_status == WindowStatus.OK
        assert daily_bar.window_end_time == (int(time.time()) // 86400 + 1) * 86400
        hourly_bar = consumption[str(hourly.uuid)]
        assert hourly_bar.window_filled_size == pytest.approx(4.0)
        assert hourly_bar.window_filled_percentage == pytest.approx(80.0)
        assert hourly_bar.window_status == WindowStatus.WARNING

    @pytest.mark.asyncio
    async def test_a_limit_never_hit_reports_nothing_consumed(self, limits):
        output = _credential_limit(CredentialLimitCategory.TOKEN_OUTPUT, 1000)
        window = credential_window(
            C, output.category.value, output.algorithm, output.window_size, output.value
        )

        bar = (await limits.consumption({'x': window}))['x']

        assert (bar.window_size, bar.window_filled_size) == (1000, 0)
        assert bar.window_filled_percentage == 0

    @pytest.mark.asyncio
    async def test_no_limits_report_nothing(self, limits):
        assert await limits.consumption({}) == {}
