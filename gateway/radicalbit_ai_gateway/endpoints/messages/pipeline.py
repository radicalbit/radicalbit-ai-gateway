"""Anthropic Messages API requests: the order a request goes through the
route's policies.

The policies read the request's texts as chat messages (see
``MessagesRequest``); what they change is written back into the body that
goes upstream. The input and output guardrails and the cache do not apply to
the Messages API yet (AG-1132).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

from radicalbit_ai_gateway.endpoints.chat_like.limits import check_chat_limits
from radicalbit_ai_gateway.endpoints.chat_like.model_selection import route_chat
from radicalbit_ai_gateway.endpoints.chat_like.system_prompt import apply_config_prompt
from radicalbit_ai_gateway.endpoints.messages.events import relay_frame
from radicalbit_ai_gateway.endpoints.messages.request import MessagesRequest
from radicalbit_ai_gateway.gateway_route.scope import RequestScope
from radicalbit_ai_gateway.limiting.limits import Usage
from radicalbit_ai_gateway.llm.messages_stream import stream_usage
from radicalbit_ai_gateway.llm.usage import messages_token_counts
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.preprocessing import run_preprocessing
from radicalbit_ai_gateway.utils.exceptions import GatewayBadRequest
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
    set_streaming,
)


@dataclass
class _Prepared:
    """A request after its input policies, before the model call: the body
    and the client's ``anthropic-*`` headers to forward upstream.
    """

    body: dict
    headers: dict[str, str]
    model: Model


async def respond(scope: RequestScope, body: dict, headers: dict[str, str]) -> dict:
    """Answer a Messages API request with one message object."""
    prepared = await _prepare(scope, body, headers)
    set_operation_category(OperationCategory.INVOCATION)
    message, _ = await scope.route.chat_invoker.complete_messages(
        **_call(scope, prepared)
    )
    await _count(scope, prepared, message.get('usage'))
    return {**message, 'model': scope.route.gateway_route_config.route_name}


async def stream(
    scope: RequestScope, body: dict, headers: dict[str, str]
) -> AsyncIterator[str]:
    """Answer a Messages API request with SSE frames: the upstream's events,
    relayed as they come.

    The input policies run before this returns, so a request they refuse
    gets an HTTP error.
    """
    return _live(scope, await _prepare(scope, body, headers))


async def _prepare(
    scope: RequestScope, body: dict, headers: dict[str, str]
) -> _Prepared:
    route = scope.route
    config = route.gateway_route_config
    route_name = config.route_name
    if not route.chat_invoker:
        raise GatewayBadRequest(f'Route {route_name} has no chat models defined')

    request = MessagesRequest(body)
    # Limits come first, before anything that spends (routing, the model),
    # as on chat.
    await check_chat_limits(scope, request.messages())

    set_operation_category(OperationCategory.PREPROCESSING)
    messages = await run_preprocessing(request.messages(), config.plugins)
    model = await route_chat(scope, messages)
    if not route.chat_invoker.supports_messages(model.model_id):
        raise GatewayBadRequest(
            f'Model {model.model_id} of route {route_name} '
            'does not serve the Messages API'
        )

    added = apply_config_prompt(messages, model)
    request.write_back(messages[added:])
    if added:
        # A deliberate choice, as on the Responses API: the configured prompt
        # goes first in ``system``. It changes the prefix the client's prompt
        # cache sees.
        request.insert_system_prompt(messages[0])
    return _Prepared(request.body, headers, model)


def _call(scope: RequestScope, prepared: _Prepared) -> dict:
    """Return the arguments of the invoker's call for a prepared request."""
    return {
        'identity': scope.identity,
        'body': prepared.body,
        'headers': prepared.headers,
        'model_id': prepared.model.model_id,
    }


async def _live(scope: RequestScope, prepared: _Prepared) -> AsyncIterator[str]:
    """Relay the upstream's events, then count the reply on the limits."""
    set_streaming()
    set_operation_category(OperationCategory.INVOCATION)
    route_name = scope.route.gateway_route_config.route_name
    usage: dict = {}
    async for event, data in scope.route.chat_invoker.stream_messages(
        **_call(scope, prepared)
    ):
        usage = stream_usage(event, data, usage)
        yield relay_frame(event, data, route_name)
    await _count(scope, prepared, usage)


async def _count(scope: RequestScope, prepared: _Prepared, usage: dict | None) -> None:
    """Count a model's reply against the limits."""
    if not usage:
        return
    input_tokens, output_tokens = messages_token_counts(usage)
    await scope.limits.count(Usage.priced(prepared.model, input_tokens, output_tokens))
