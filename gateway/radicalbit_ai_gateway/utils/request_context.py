"""Request-scoped route context.

A ``logging.Filter`` only sees the ``LogRecord``, not the FastAPI request. The
handler publishes the resolved route config here right after route resolution so
per-route consumers (e.g. plugins) can read it; ``reset_route_context`` clears it
when the request finishes. The core never interprets the config.

The client-supplied tags live here too: ``emit_event`` is called from deep
inside invokers, guardrails and limiters, none of which hold the request.
"""

from collections.abc import Awaitable
from contextvars import ContextVar
from functools import wraps
import logging
from typing import Any, Protocol

from radicalbit_ai_gateway.utils.app_config import get_app_config

logger = logging.getLogger(get_app_config().log_config.logger_name)

# Route config of the current request, or None when none is resolved. Typed as
# Any to avoid an import cycle with the model.
current_route_config_ctx: ContextVar[Any] = ContextVar(
    'current_route_config', default=None
)


def set_current_route_config(config: Any) -> None:
    current_route_config_ctx.set(config)


def reset_route_context(func):
    """Clear the route context when the handler finishes, including on error."""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        finally:
            current_route_config_ctx.set(None)
            current_credential_limiter_ctx.set(None)
            current_project_budget_limiter_ctx.set(None)
            current_request_identity_ctx.set(None)
            routing_spend_recorder_ctx.set(None)

    return wrapper


# ``key=value`` tags of the current request, or an empty tuple.
current_request_tags_ctx: ContextVar[tuple[str, ...]] = ContextVar(
    'current_request_tags', default=()
)


def set_current_request_tags(tags: tuple[str, ...]) -> None:
    current_request_tags_ctx.set(tags)


def get_current_request_tags() -> tuple[str, ...]:
    return current_request_tags_ctx.get()


# The calling credential's own CredentialLimiter, or None when it has no
# limits configured. Same problem as the tags above: a GatewayRoute instance
# is a shared singleton, so a per-credential limiter can't live on `self`.
current_credential_limiter_ctx: ContextVar[Any] = ContextVar(
    'current_credential_limiter', default=None
)


def set_current_credential_limiter(limiter: Any) -> None:
    current_credential_limiter_ctx.set(limiter)


def get_current_credential_limiter() -> Any:
    return current_credential_limiter_ctx.get()


# The calling project's own ProjectBudgetLimiter, or None when it has no
# budget limits configured. Same problem as the credential limiter above:
# a GatewayRoute instance is a shared singleton, so a limiter built from
# DB rows that can change independently of the route config can't live on
# `self`.
current_project_budget_limiter_ctx: ContextVar[Any] = ContextVar(
    'current_project_budget_limiter', default=None
)


def set_current_project_budget_limiter(limiter: Any) -> None:
    current_project_budget_limiter_ctx.set(limiter)


def get_current_project_budget_limiter() -> Any:
    return current_project_budget_limiter_ctx.get()


# Who sent the current request (a RequestIdentity), or None. Routing needs it
# to charge its own calls, but the router interface only takes the messages.
current_request_identity_ctx: ContextVar[Any] = ContextVar(
    'current_request_identity', default=None
)


def set_current_request_identity(identity: Any) -> None:
    current_request_identity_ctx.set(identity)


def get_current_request_identity() -> Any:
    return current_request_identity_ctx.get()


class RoutingSpendRecorder(Protocol):
    """Charge one routing call to the current request.

    It emits the cost event (flagged as routing) at the model's input price
    and counts the input tokens on the route, credential and project limits.
    ``model_type`` is ``'embeddings'`` or ``'decision_model'``. Pass
    ``target_model_id`` when a fallback model answered instead of it.
    """

    def __call__(
        self,
        model: Any,
        input_tokens: int,
        latency_ms: float,
        *,
        model_type: str,
        target_model_id: str | None = None,
    ) -> Awaitable[None]: ...


# Set by the route only while its router picks a model. Routers are shared
# by every request, so they read the recorder here instead of holding it.
routing_spend_recorder_ctx: ContextVar[RoutingSpendRecorder | None] = ContextVar(
    'routing_spend_recorder', default=None
)


def set_routing_spend_recorder(recorder: RoutingSpendRecorder | None) -> None:
    routing_spend_recorder_ctx.set(recorder)


def get_routing_spend_recorder() -> RoutingSpendRecorder | None:
    return routing_spend_recorder_ctx.get()


async def record_routing_spend(
    model: Any,
    input_tokens: int,
    latency_ms: float,
    *,
    model_type: str,
    target_model_id: str | None = None,
) -> None:
    """Charge one routing call to the current request, if a recorder is set.

    Routing never fails a request: a failure here is logged, not raised.
    """
    record = get_routing_spend_recorder()
    if record is None:
        return
    try:
        await record(
            model,
            input_tokens,
            latency_ms,
            model_type=model_type,
            target_model_id=target_model_id,
        )
    except Exception:
        logger.exception('Routing spend on model %s was not recorded', model.model_id)
