"""The limits a request is subject to: checked before it spends, counted after.

A request meets the limits of its route, of its credential and of its
project. ``Limits.resolve`` gathers them into the request's ``RequestLimits``;
the gateway then calls ``check`` with what the request is about to demand and
``count`` with what it used. Requests and audio seconds are counted when
checked; tokens and cost only when known, after the call. Each reads, then
writes, every counter it touches in one round trip to the storage. Check and
count are two steps, not one atomic operation: concurrent requests can all
pass a check and then overshoot together.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from traceloop.sdk.decorators import task

from radicalbit_ai_gateway.events.events_processor import emit_event
from radicalbit_ai_gateway.limiter import Consumption, Storage
from radicalbit_ai_gateway.limiter.storage.shared import get_limit_storage
from radicalbit_ai_gateway.limiting.limit_event import emit_thresholds, limit_fields
from radicalbit_ai_gateway.limiting.messages import (
    BLOCKS,
    log_allowed,
    log_unknown_audio_duration,
)
from radicalbit_ai_gateway.limiting.window_progress import window_progress_bar
from radicalbit_ai_gateway.limiting.windows import (
    Category,
    Window,
    credential_windows,
    project_windows,
    route_windows,
)
from radicalbit_ai_gateway.models.event_dto import WindowProgressBarDTO
from radicalbit_ai_gateway.models.event_payload import LimitEventPayload, LimitScope
from radicalbit_ai_gateway.models.project_budget_limiting import ProjectBudgetLimitOut
from radicalbit_ai_gateway.models.request_identity import RequestIdentity
from radicalbit_ai_gateway.utils import BUDGET_MULTIPLIER
from radicalbit_ai_gateway.utils.token_encoding import count_tokens
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
)

if TYPE_CHECKING:
    from radicalbit_ai_gateway.db.dao.project_budget_limit_dao import (
        ProjectBudgetLimitDAO,
    )
    from radicalbit_ai_gateway.models.credential_limiting import CredentialLimitOut
    from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
    from radicalbit_ai_gateway.models.model import Model

ROUTE = LimitScope.ROUTE
CREDENTIAL = LimitScope.CREDENTIAL
PROJECT = LimitScope.PROJECT

# The order ``check`` tests the limits in, which decides the error reported
# when several would block: the credential's before the route's and the
# project's. When the input size is unknown until the call (the decision
# endpoint: Demand.input is 'room'), the budgets come before the input room.
CHECK_ORDER = {
    'estimate': (
        (CREDENTIAL, Category.REQUESTS),
        (ROUTE, Category.REQUESTS),
        (CREDENTIAL, Category.INPUT_TOKENS),
        (CREDENTIAL, Category.OUTPUT_TOKENS),
        (CREDENTIAL, Category.COST),
        (PROJECT, Category.COST),
        (ROUTE, Category.INPUT_TOKENS),
        (ROUTE, Category.OUTPUT_TOKENS),
        (ROUTE, Category.COST),
        (ROUTE, Category.AUDIO_SECONDS),
    ),
    'room': (
        (CREDENTIAL, Category.REQUESTS),
        (ROUTE, Category.REQUESTS),
        (CREDENTIAL, Category.COST),
        (PROJECT, Category.COST),
        (ROUTE, Category.COST),
        (CREDENTIAL, Category.INPUT_TOKENS),
        (ROUTE, Category.INPUT_TOKENS),
        (CREDENTIAL, Category.OUTPUT_TOKENS),
        (ROUTE, Category.OUTPUT_TOKENS),
        (ROUTE, Category.AUDIO_SECONDS),
    ),
}

# The order ``count`` adds usage in, which is the order threshold events go out.
COUNT_ORDER = (
    (ROUTE, Category.INPUT_TOKENS),
    (ROUTE, Category.OUTPUT_TOKENS),
    (ROUTE, Category.COST),
    (CREDENTIAL, Category.INPUT_TOKENS),
    (CREDENTIAL, Category.OUTPUT_TOKENS),
    (CREDENTIAL, Category.COST),
    (PROJECT, Category.COST),
)

# Counted when checked: the request is known whole before the call.
_COUNTED_ON_CHECK = (Category.REQUESTS, Category.AUDIO_SECONDS)


@dataclass(frozen=True)
class RouteLimits:
    """A route's own limits, built once when its configuration is loaded."""

    windows: tuple[Window, ...] = ()

    @classmethod
    def from_config(cls, config: GatewayRouteConfig, project_uuid: str) -> RouteLimits:
        return cls(route_windows(config, project_uuid))

    def window(self, category: Category) -> Window | None:
        return next((w for w in self.windows if w.category is category), None)


@dataclass(frozen=True)
class InputEstimate:
    """The input to estimate: tokenized only if an input limit applies."""

    text: str
    model: str


@dataclass(frozen=True)
class Demand:
    """What a request is about to consume.

    ``input`` is the text to estimate, or 'room' when its size is known only
    after the call: then, as for output and cost, the check only asks that
    the counter is not already full. ``audio_seconds`` is 'unknown' for an
    audio file whose length can't be read: it is let through uncounted.
    """

    request: bool = False
    input: InputEstimate | Literal['room'] | None = None
    output_room: bool = False
    cost_room: bool = False
    audio_seconds: float | Literal['unknown'] | None = None


# What every request demands as it arrives, before anything else is checked.
ADMISSION = Demand(request=True)


@dataclass(frozen=True)
class Usage:
    """What a call used. ``costs`` holds one cost, in counter units, per
    priced part of the usage (input, output...): each is added on its own.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    costs: tuple[int, ...] = ()

    @staticmethod
    def priced(
        model: Model, input_tokens: int, output_tokens: int | None = None
    ) -> Usage:
        """Return token usage, costed at the model's prices; an unpriced
        part costs nothing and is not added.
        """
        costs = []
        if model.input_cost_per_token:
            costs.append(
                int(input_tokens * model.input_cost_per_token * BUDGET_MULTIPLIER)
            )
        if output_tokens is not None and model.output_cost_per_token:
            costs.append(
                int(output_tokens * model.output_cost_per_token * BUDGET_MULTIPLIER)
            )
        return Usage(input_tokens, output_tokens, tuple(costs))

    @staticmethod
    def transcription(model: Model, usage: Any) -> Usage:
        """Return a transcription's cost: by audio seconds, or by audio, text
        and output tokens. Its tokens count on no token limit.
        """
        if usage is None:
            return Usage()
        if usage.type == 'duration':
            if not model.input_cost_per_second:
                return Usage()
            cost_per_second = float(model.input_cost_per_second)
            return Usage(
                costs=(int(usage.seconds * cost_per_second * BUDGET_MULTIPLIER),)
            )

        details = getattr(usage, 'input_token_details', None)
        audio_tokens = getattr(details, 'audio_tokens', None) or 0
        text_tokens = getattr(details, 'text_tokens', None)
        if text_tokens is None:
            text_tokens = usage.input_tokens
        parts = (
            (audio_tokens, model.input_cost_per_audio_token),
            (text_tokens, model.input_cost_per_token),
            (usage.output_tokens, model.output_cost_per_token),
        )
        return Usage(
            costs=tuple(
                int(tokens * price * BUDGET_MULTIPLIER)
                for tokens, price in parts
                if tokens > 0 and price
            )
        )

    def amounts(self, category: Category) -> tuple[int, ...]:
        if category is Category.INPUT_TOKENS:
            return () if self.input_tokens is None else (self.input_tokens,)
        if category is Category.OUTPUT_TOKENS:
            return () if self.output_tokens is None else (self.output_tokens,)
        return self.costs


class RequestLimits:
    """The limits one request is subject to, at route, credential and
    project scope.
    """

    def __init__(
        self, storage: Storage, identity: RequestIdentity, windows: Sequence[Window]
    ) -> None:
        self.identity = identity
        self._storage = storage
        self._windows = tuple(windows)

    def _windows_of(self, scope: LimitScope, category: Category) -> list[Window]:
        return [w for w in self._windows if (w.scope, w.category) == (scope, category)]

    def applies(self, demand: Demand) -> bool:
        """Return whether ``check`` would test any limit for ``demand``."""
        return any(_demands(demand, w.category) for w in self._windows)

    async def check(self, demand: Demand, count: bool = True) -> None:
        """Raise the limit error of the first limit ``demand`` would exceed.

        A check that tests any limit marks the request's operation as LIMITING.

        Requests and audio seconds are counted here, a scope only once all
        its windows let the demand through. Every counter is read in one
        round trip, and the counted ones written in another. With ``count``
        False nothing is counted: ``count_checked`` counts it later, once the
        request is known to spend (a transcription the cache does not serve).
        """
        groups = self._demanded_groups(demand)
        if not groups:
            return
        set_operation_category(OperationCategory.LIMITING)
        values = iter(
            await self._storage.get_many(
                [window.key for _, windows, _ in groups for window in windows]
            )
        )
        to_count: list[tuple[Window, int]] | None = [] if count else None
        for span, windows, cost in groups:
            counters = [next(values) for _ in windows]
            check = _ROUTE_CHECKS[span] if span else RequestLimits._check_windows
            await check(self, windows, counters, cost, to_count)
        if to_count:
            await self._add(to_count)

    def _demanded_groups(
        self, demand: Demand
    ) -> list[tuple[str | None, list[Window], int]]:
        """Return the windows ``demand`` is checked against, a scope's windows
        of a category together, in check order, each with its route span
        name and the cost demanded.
        """
        order = 'room' if demand.input == 'room' else 'estimate'
        tokens = None
        groups = []
        for scope, category in CHECK_ORDER[order]:
            windows = self._windows_of(scope, category)
            if not windows or not _demands(demand, category):
                continue
            if isinstance(demand.input, InputEstimate) and (
                category is Category.INPUT_TOKENS
            ):
                if tokens is None:
                    tokens = count_tokens(demand.input.text, demand.input.model)
                cost = tokens
            elif category is Category.AUDIO_SECONDS:
                if demand.audio_seconds == 'unknown':
                    log_unknown_audio_duration(self.identity)
                    continue
                cost = round(demand.audio_seconds)
            else:
                cost = 1
            span = _span_name(category, demand) if scope is ROUTE else None
            groups.append((span, windows, cost))
        return groups

    async def _check_windows(
        self,
        windows: list[Window],
        counters: list[int | None],
        cost: int,
        to_count: list[tuple[Window, int]] | None,
    ) -> None:
        """Check one scope's windows of a category against their counters.

        A window it lets through and that counts on check joins ``to_count``,
        unless it is None: then nothing is counted.
        """
        for window, counter in zip(windows, counters, strict=True):
            if (counter or 0) + cost > window.config.limit:
                # What the scopes before this one let through still counts.
                if to_count:
                    await self._add(to_count)
                    to_count.clear()
                limiter = window.limiter(self._storage)
                stats = await limiter.get_window_stats(window.config)
                block = BLOCKS[(window.scope, window.category)]
                emit_event(
                    LimitEventPayload(
                        **self.identity.event_fields(),
                        event_type=block.event_type,
                        value=1.0,
                        **limit_fields(window.scope, window.config, stats),
                    )
                )
                if block.metric is not None:
                    block.metric.add(1, {'route_name': self.identity.route_name})
                raise block.error(window, cost, stats, self.identity)
        for window in windows:
            log_allowed(window, cost, self.identity)
            if to_count is not None and window.category in _COUNTED_ON_CHECK:
                to_count.append((window, cost))

    async def count_checked(self, demand: Demand) -> None:
        """Count what ``check(demand, count=False)`` let through without
        counting: its requests and audio seconds. Never blocks.
        """
        to_count = []
        for scope, category in CHECK_ORDER['estimate']:
            if category not in _COUNTED_ON_CHECK or not _demands(demand, category):
                continue
            if category is Category.AUDIO_SECONDS:
                if demand.audio_seconds == 'unknown':
                    continue
                amount = round(demand.audio_seconds)
            else:
                amount = 1
            to_count.extend(
                (window, amount) for window in self._windows_of(scope, category)
            )
        await self._add(to_count)

    async def count(self, usage: Usage) -> None:
        """Add what a call used to every limit it counts on, in one round
        trip. Never blocks.
        """
        to_count = []
        for scope, category in COUNT_ORDER:
            windows = self._windows_of(scope, category)
            if not windows:
                continue
            for amount in usage.amounts(category):
                to_count.extend((window, amount) for window in windows)
        await self._add(to_count)

    async def charge_call(
        self, model: Model, input_tokens: int, output_tokens: int | None = None
    ) -> None:
        """Count a call made on the request's behalf at the called model's
        price (ADR 0006): a judge's, for one. An embedding call has no
        ``output_tokens``.
        """
        await self.count(Usage.priced(model, input_tokens, output_tokens))

    async def _add(self, to_count: list[tuple[Window, int]]) -> None:
        """Add each amount to its window, then emit the thresholds crossed."""
        if not to_count:
            return
        limiters = [window.limiter(self._storage) for window, _ in to_count]
        consumptions = await self._storage.increment_many(
            [
                limiter.increment_args(window.config, amount)
                for limiter, (window, amount) in zip(limiters, to_count, strict=True)
            ]
        )
        for limiter, (window, amount), (value, window_id) in zip(
            limiters, to_count, consumptions, strict=True
        ):
            await emit_thresholds(
                limiter,
                window.config,
                amount,
                Consumption(value=value, window_id=window_id),
                window.scope,
                self.identity,
            )


def _demands(demand: Demand, category: Category) -> bool:
    return {
        Category.REQUESTS: demand.request,
        Category.INPUT_TOKENS: demand.input is not None,
        Category.OUTPUT_TOKENS: demand.output_room,
        Category.COST: demand.cost_room,
        Category.AUDIO_SECONDS: demand.audio_seconds is not None,
    }[category]


def _span_name(category: Category, demand: Demand) -> str:
    if category is Category.INPUT_TOKENS and demand.input == 'room':
        return 'check_token_input_room'
    return _ROUTE_SPANS[category]


# A route check runs in the trace span it has always had.
_ROUTE_SPANS = {
    Category.REQUESTS: 'check_request_rate',
    Category.INPUT_TOKENS: 'check_token_input_limit',
    Category.OUTPUT_TOKENS: 'check_token_output_limit',
    Category.COST: 'check_budget_limit',
    Category.AUDIO_SECONDS: 'check_audio_duration_limit',
}
_ROUTE_CHECKS = {
    name: task(name=name)(RequestLimits._check_windows)
    for name in (*_ROUTE_SPANS.values(), 'check_token_input_room')
}


class Limits:
    """The process's limits. Its storage is the process's limit storage
    unless one is given.
    """

    def __init__(self, storage: Storage | None = None) -> None:
        self._storage = storage

    @property
    def storage(self) -> Storage:
        return self._storage or get_limit_storage()

    def resolve(
        self,
        identity: RequestIdentity,
        route: RouteLimits,
        credential_limits: Sequence[CredentialLimitOut] = (),
        project_limits: Sequence[ProjectBudgetLimitOut] = (),
    ) -> RequestLimits:
        """Return the limits of a request: its route's, its credential's
        (``identity.api_key_uuid``) and its project's
        (``identity.project_uuid``).
        """
        return RequestLimits(
            self.storage,
            identity,
            route.windows
            + credential_windows(identity.api_key_uuid, list(credential_limits))
            + project_windows(identity.project_uuid, list(project_limits)),
        )

    async def usage_ratio(self, window: Window) -> float:
        """Return how much of ``window`` is used, 0 for none and 1 for all."""
        stats = await window.limiter(self.storage).get_window_stats(window.config)
        return 1 - (stats.remaining / window.config.limit)

    async def progress(self, window: Window) -> WindowProgressBarDTO:
        """Return how much of ``window`` is used, and when it resets."""
        return await window_progress_bar(
            window.limiter(self.storage),
            window.config,
            is_budget=window.category is Category.COST,
        )

    async def consumption(
        self, windows: Mapping[str, Window]
    ) -> dict[str, WindowProgressBarDTO]:
        """Return each window's progress under its key (a limit's uuid).

        Reads the counters requests write, without consuming them.
        """
        return {key: await self.progress(window) for key, window in windows.items()}

    async def clear(self, window: Window) -> None:
        """Reset ``window``'s counter, as when its limit is deleted."""
        await self.storage.delete(window.key)


shared_limits = Limits()


async def load_project_limits(
    project_uuid: str, dao: ProjectBudgetLimitDAO
) -> list[ProjectBudgetLimitOut]:
    """Return a project's budget limits as they are now.

    Read on every request, so a change applies at once. The query blocks: it
    runs on a worker thread, not the event loop.
    """
    if not project_uuid:
        return []
    rows = await asyncio.to_thread(dao.get_by_project_uuid, UUID(project_uuid))
    return [ProjectBudgetLimitOut.from_project_budget_limit(row) for row in rows]
