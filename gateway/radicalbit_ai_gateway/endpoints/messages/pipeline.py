"""Anthropic Messages API requests: the order a request goes through the
route's policies.

The policies read the request's texts as chat messages (see
``MessagesRequest``); what they change is written back into the body that
goes upstream. The order is the one of the Responses API. The cache does not
apply to the Messages API yet (AG-1132).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

from radicalbit_ai_gateway.endpoints.chat_like.limits import check_chat_limits
from radicalbit_ai_gateway.endpoints.chat_like.model_selection import route_chat
from radicalbit_ai_gateway.endpoints.chat_like.system_prompt import apply_config_prompt
from radicalbit_ai_gateway.endpoints.common.streams import stream_of
from radicalbit_ai_gateway.endpoints.messages.events import (
    MessageCollector,
    message_events,
    relay_frame,
    sse,
)
from radicalbit_ai_gateway.endpoints.messages.guardrails import screen_output
from radicalbit_ai_gateway.endpoints.messages.output import gateway_message
from radicalbit_ai_gateway.endpoints.messages.request import MessagesRequest
from radicalbit_ai_gateway.gateway_route.scope import RequestScope
from radicalbit_ai_gateway.guardrails.guardrails import Conversation
from radicalbit_ai_gateway.limiting.limits import Usage
from radicalbit_ai_gateway.llm.messages_stream import stream_usage
from radicalbit_ai_gateway.llm.usage import messages_token_counts
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.preprocessing import run_preprocessing
from radicalbit_ai_gateway.utils.exceptions import (
    GatewayBadRequest,
    ModelInvokerInternalError,
)
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
    set_streaming,
)


@dataclass
class _Prepared:
    """A request after its input policies, before the model call: the body
    and the client's ``anthropic-*`` headers to forward upstream.

    ``soft_block`` is the message object of an input soft block.
    """

    body: dict
    headers: dict[str, str]
    model: Model
    soft_block: dict | None = None


async def respond(scope: RequestScope, body: dict, headers: dict[str, str]) -> dict:
    """Answer a Messages API request with one message object."""
    return await _respond(scope, await _prepare(scope, body, headers))


async def stream(
    scope: RequestScope, body: dict, headers: dict[str, str]
) -> AsyncIterator[str]:
    """Answer a Messages API request with SSE frames.

    The upstream's events are relayed as they come, unless the whole answer
    must be known first: a soft block, or an answer the output guardrails
    must pass. Then the frames are known when this returns.

    The input policies run before this returns, so a request they refuse
    gets an HTTP error.
    """
    prepared = await _prepare(scope, body, headers)
    # A cache hit is known whole too: it goes with the buffered answers.
    if prepared.soft_block or scope.route.guardrails.has_output:
        return stream_of(await _buffered(scope, prepared))
    return _live(scope, prepared)


async def _prepare(
    scope: RequestScope, body: dict, headers: dict[str, str]
) -> _Prepared:
    route = scope.route
    config = route.gateway_route_config
    route_name = config.route_name
    if not route.chat_invoker:
        raise GatewayBadRequest(f'Route {route_name} has no chat models defined')

    request = MessagesRequest(body)
    # Limits come first, before anything that spends (routing, judges, the
    # model), as on chat.
    await check_chat_limits(scope, request.messages())

    set_operation_category(OperationCategory.PREPROCESSING)
    messages = await run_preprocessing(request.messages(), config.plugins)
    redaction = await scope.guardrails.redact_input(Conversation(messages))
    # Route on the redacted messages, as the chat path does (ADR 0010).
    model = await route_chat(scope, redaction.payload.messages())
    if not route.chat_invoker.supports_messages(model.model_id):
        raise GatewayBadRequest(
            f'Model {model.model_id} of route {route_name} '
            'does not serve the Messages API'
        )

    messages = redaction.payload.messages()
    added = apply_config_prompt(messages, model)
    screened = await scope.guardrails.check_input(
        Conversation(messages, skip=added), redaction.flags
    )
    scope.flags |= screened.flags
    if screened.soft_block:
        return _Prepared(
            request.body,
            headers,
            model,
            soft_block=gateway_message(
                scope.identity.request_uuid,
                route_name,
                screened.soft_block.get_soft_block_message(),
            ),
        )

    request.write_back(messages[added:])
    if added:
        # A deliberate choice, as on the Responses API: the configured prompt
        # goes first in ``system``. It changes the prefix the client's prompt
        # cache sees.
        request.insert_system_prompt(messages[0])

    # The cache lookup goes here, on the body as it goes upstream.
    return _Prepared(request.body, headers, model)


async def _respond(scope: RequestScope, prepared: _Prepared) -> dict:
    if prepared.soft_block:
        return prepared.soft_block

    set_operation_category(OperationCategory.INVOCATION)
    message, _ = await scope.route.chat_invoker.complete_messages(
        **_call(scope, prepared)
    )
    return await _screened(scope, prepared, message)


async def _screened(scope: RequestScope, prepared: _Prepared, message: dict) -> dict:
    """Count a model's answer, apply the output guardrails to it and return
    it as the client gets it.
    """
    await _count(scope, prepared, message.get('usage'))
    message = await screen_output(scope, message)
    # The cache store goes here, on the screened answer.
    return {**message, 'model': scope.route.gateway_route_config.route_name}


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
    # The cache store of a relayed answer goes here.


async def _buffered(scope: RequestScope, prepared: _Prepared) -> list[str]:
    """Return the frames of an answer known whole before streaming.

    The model's answer is collected from its stream, so a long answer comes
    as it would to the client. The answer is then streamed as Anthropic
    streams it, each block in one delta.
    """
    set_streaming()
    if prepared.soft_block:
        return message_events(prepared.soft_block)

    set_operation_category(OperationCategory.INVOCATION)
    collector = MessageCollector()
    async for event, data in scope.route.chat_invoker.stream_messages(
        **_call(scope, prepared)
    ):
        collector.add(event, data)
    message = collector.message()
    if message is None:
        # The answer was cut off: none of its text goes out unscreened.
        await _count(scope, prepared, collector.usage)
        if collector.error is None:
            raise ModelInvokerInternalError(
                'The model stream ended before the answer was complete'
            )
        return [sse('error', collector.error)]
    return message_events(await _screened(scope, prepared, message))


async def _count(scope: RequestScope, prepared: _Prepared, usage: dict | None) -> None:
    """Count a model's reply against the limits. It runs before the output
    guardrails: the model was paid for even when they refuse the reply
    (ADR 0006).
    """
    if not usage:
        return
    input_tokens, output_tokens = messages_token_counts(usage)
    await scope.limits.count(Usage.priced(prepared.model, input_tokens, output_tokens))
