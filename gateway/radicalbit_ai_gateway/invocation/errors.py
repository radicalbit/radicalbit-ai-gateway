"""The error a client gets when no model answered: the one place for the
error contract of model calls.
"""

from collections.abc import Callable
from enum import Enum
import logging
from typing import NoReturn

from radicalbit_ai_gateway.invocation.fallback_chain import Failure
from radicalbit_ai_gateway.llm.errors import provider_status
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    ModelInvokerBadGateway,
    ModelInvokerError,
    ModelInvokerInternalError,
    ModelInvokerUpstreamError,
)

logger = logging.getLogger(get_app_config().log_config.logger_name)


class Surface(Enum):
    """What the client called."""

    CHAT = 'chat'
    CHAT_STREAM = 'chat_stream'
    RESPONSES = 'responses'
    MESSAGES = 'messages'
    EMBEDDINGS = 'embeddings'
    TRANSCRIPTION = 'transcription'
    TRANSCRIPTION_STREAM = 'transcription_stream'
    DECISION = 'decision'


# The surfaces whose clients get a provider's refusal as the provider sent it.
_PASSES_REFUSALS = frozenset({Surface.CHAT, Surface.CHAT_STREAM, Surface.RESPONSES})


def upstream_refusal(error: BaseException | None) -> ModelInvokerUpstreamError | None:
    """Return the provider's 4xx behind ``error``, as the client gets it: the
    provider's status and body. None when ``error`` is not a 4xx.

    The body is the provider's JSON as it sent it, or ``{'error': {'message':
    ...}}`` when it sent none.
    """
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        refusal = provider_status(error)
        if refusal is not None:
            status, message, body = refusal
            if 400 <= status < 500:
                return ModelInvokerUpstreamError(message, status, body)
            return None
        error = error.__cause__
    return None


# Statuses that refuse the gateway's own access to the provider (its
# configured key, say), not the client's request.
_ACCESS_REFUSALS = frozenset({401, 403})


def messages_refusal(error: BaseException | None) -> ModelInvokerUpstreamError | None:
    """Return the provider's refusal behind ``error`` as a Messages API client
    gets it, or None when it gets the gateway's own error.

    That is a 4xx, but not a 401 or 403: those refuse the gateway's own access
    to the provider, and the client must not read them as a refusal of its
    credential. A body that is not JSON becomes a Messages API ``api_error``.
    """
    refusal = upstream_refusal(error)
    if refusal is None or refusal.status_code in _ACCESS_REFUSALS:
        return None
    if refusal.body == {'error': {'message': refusal.client_message}}:
        refusal.body = {
            'type': 'error',
            'error': {'type': 'api_error', 'message': refusal.client_message},
        }
    return refusal


def final_messages_refusal(
    error: BaseException | None,
) -> ModelInvokerUpstreamError | None:
    """Return the refusal of a Messages request that no model would serve.

    A refused request is wrong, so another model would refuse it too; a rate
    limit (429) is not, and falls back.
    """
    refusal = messages_refusal(error)
    if refusal is None or refusal.status_code == 429:
        return None
    return refusal


def exhausted(
    surface: Surface, route: str, errors: list[BaseException | None]
) -> ModelInvokerError:
    """Return the error of a ``surface`` call on ``route`` no model answered.

    ``errors`` are the candidates' errors, the target's first. A provider's
    refusal (a 4xx) of the target reaches a chat or Responses client as the
    provider sent it; any other failure is the gateway's own error.
    """
    first = errors[0] if errors else None
    if surface is Surface.CHAT:
        logger.error('All chat models failed for route %s', route, exc_info=first)
    if surface in _PASSES_REFUSALS and (refusal := upstream_refusal(first)):
        return refusal
    if surface is Surface.MESSAGES and (refusal := messages_refusal(first)):
        return refusal
    match surface:
        case Surface.CHAT | Surface.RESPONSES | Surface.MESSAGES:
            return ModelInvokerInternalError(
                f'All chat models failed for model {route}: {first}'
            )
        case Surface.CHAT_STREAM:
            return ModelInvokerInternalError(f'All models failed for streaming {route}')
        case Surface.EMBEDDINGS:
            return ModelInvokerInternalError(
                f'All embedding models failed for model {route}: {first}'
            )
        case Surface.TRANSCRIPTION:
            return ModelInvokerInternalError(
                f'All transcription models failed for route {route}: {first}'
            )
        case Surface.TRANSCRIPTION_STREAM:
            return ModelInvokerInternalError(
                f'All transcription models failed for streaming {route}: {first}'
            )
        case Surface.DECISION:
            return ModelInvokerBadGateway(
                f'No decision model answered for route {route}'
            )


def raising(surface: Surface, route: str) -> Callable[[list[Failure]], NoReturn]:
    """Return the ``on_exhausted`` of a call that raises when no model answered."""

    def raise_exhausted(failures: list[Failure]) -> NoReturn:
        errors = [failure.error for failure in failures]
        raise exhausted(surface, route, errors) from (errors[0] if errors else None)

    return raise_exhausted
