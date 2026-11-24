"""Responses API requests: the order a request goes through the route's
policies.

The policies read the request's texts as chat messages (see
``ResponsesRequest``); what they change is written back into the body that
goes upstream.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from radicalbit_ai_gateway.endpoints.chat_like.limits import check_chat_limits
from radicalbit_ai_gateway.endpoints.chat_like.model_selection import route_chat
from radicalbit_ai_gateway.endpoints.chat_like.system_prompt import apply_config_prompt
from radicalbit_ai_gateway.endpoints.common.streams import stream_of
from radicalbit_ai_gateway.endpoints.responses.cache import ResponsesEntry
from radicalbit_ai_gateway.endpoints.responses.events import response_events
from radicalbit_ai_gateway.endpoints.responses.guardrails import ResponsesReply
from radicalbit_ai_gateway.endpoints.responses.output import (
    gateway_response,
    message_item,
)
from radicalbit_ai_gateway.endpoints.responses.request import (
    ResponsesRequest,
    apply_governance,
    check_supported,
    references_stored_state,
)
from radicalbit_ai_gateway.gateway_route.scope import RequestScope
from radicalbit_ai_gateway.guardrails.guardrails import Conversation, GuardrailFlags
from radicalbit_ai_gateway.invocation.chat_model_invoker import ChatModelInvoker
from radicalbit_ai_gateway.limiting.limits import Usage
from radicalbit_ai_gateway.llm.usage import responses_token_counts
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.preprocessing import run_preprocessing
from radicalbit_ai_gateway.telemetry.tracing import workflow
from radicalbit_ai_gateway.utils.exceptions import GatewayBadRequest
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
    set_streaming,
)

#: A Responses API request: it serves and stores response objects.
ResponsesScope = RequestScope[dict[str, Any], dict[str, Any]]


@dataclass
class _Prepared:
    """A request after its input policies, before the model call, with the
    invoker that calls the model.

    ``allow_fallback`` is False when the request continues state stored at
    the provider, which only the selected model's account can serve.
    ``soft_block`` is the response object of an input soft block.
    """

    body: dict[str, Any]
    invoker: ChatModelInvoker
    model: Model
    allow_fallback: bool
    soft_block: dict[str, Any] | None = None


async def respond(scope: ResponsesScope, body: dict[str, Any]) -> dict[str, Any]:
    """Answer a Responses API request with one response object."""
    return await _respond(scope, await _prepare(scope, body))


async def stream(scope: ResponsesScope, body: dict[str, Any]) -> AsyncIterator[str]:
    """Answer a Responses API request with SSE frames.

    The upstream's events are relayed as they come, unless the whole reply
    must be known first: a soft block, a cache hit, or a reply the output
    guardrails must pass. Then the frames are known when this returns.
    """
    prepared = await _prepare(scope, body)
    if (
        (prepared.soft_block is not None and len(prepared.soft_block) > 0)
        or scope.cached.hit
        or scope.route.guardrails.has_output
    ):
        return stream_of(await _buffered(scope, prepared))
    return _live(scope, prepared)


async def _prepare(scope: ResponsesScope, body: dict[str, Any]) -> _Prepared:
    route = scope.route
    config = route.gateway_route_config
    route_name = config.route_name
    invoker = route.chat_invoker
    if invoker is None:
        raise GatewayBadRequest(f'Route {route_name} has no chat models defined')

    check_supported(body)
    request = ResponsesRequest(body)
    apply_governance(request.body, config.responses, route_name)
    allow_fallback = not references_stored_state(request.body)

    # Limits come first, before anything that spends (routing, judges, the
    # semantic cache, the model), as on chat.
    await check_chat_limits(scope, request.messages())

    set_operation_category(OperationCategory.PREPROCESSING)
    messages = await run_preprocessing(request.messages(), config.plugins)
    redaction = await scope.guardrails.redact_input(Conversation(messages))
    # Route on the redacted messages, as the chat path does.
    model = await route_chat(scope, redaction.payload.messages())
    if not invoker.supports_responses(model.model_id):
        raise GatewayBadRequest(
            f'Model {model.model_id} of route {route_name} '
            'does not serve the Responses API'
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
            invoker,
            model,
            allow_fallback,
            soft_block=gateway_response(
                scope.identity.request_uuid,
                route_name,
                body,
                screened.soft_block.get_soft_block_message(),
            ),
        )

    if model.effective_prompt is not None and model.effective_prompt != '':
        request.write_back(messages[1:])
        request.insert_prompt(messages[0], model.role)
    else:
        request.write_back(messages)

    scope.cached = await scope.cache.lookup(ResponsesEntry(request.body))
    return _Prepared(request.body, invoker, model, allow_fallback)


async def _respond(scope: ResponsesScope, prepared: _Prepared) -> dict[str, Any]:
    route_name = scope.route.gateway_route_config.route_name
    if prepared.soft_block is not None and len(prepared.soft_block) > 0:
        return prepared.soft_block

    if scope.cached.hit:
        response = scope.cached.value
    else:
        set_operation_category(OperationCategory.INVOCATION)
        response, _ = await prepared.invoker.complete_responses(
            **_call(scope, prepared)
        )

    if not scope.cached.hit:
        await _count(scope, prepared, response)
    response = await _screen_output(scope, response)
    if not scope.cached.hit:
        await _store(scope, prepared, response)
    return {**response, 'model': route_name}


def _call(scope: ResponsesScope, prepared: _Prepared) -> dict[str, Any]:
    """Return the arguments of the invoker's call for a prepared request."""
    return {
        'identity': scope.identity,
        'body': prepared.body,
        'model_id': prepared.model.model_id,
        'allow_fallback': prepared.allow_fallback,
    }


async def _live(scope: ResponsesScope, prepared: _Prepared) -> AsyncIterator[str]:
    """Relay the upstream's events, then account for the final response."""
    set_streaming()
    set_operation_category(OperationCategory.INVOCATION)
    route_name = scope.route.gateway_route_config.route_name
    final_response = None
    async for event in prepared.invoker.stream_responses(**_call(scope, prepared)):
        if event.is_final:
            final_response = event.response
        yield event.to_sse(route_name)

    if final_response is not None and len(final_response) > 0:
        await _count(scope, prepared, final_response)
        await _store(scope, prepared, final_response)


async def _buffered(scope: ResponsesScope, prepared: _Prepared) -> list[str]:
    """Return the frames of a reply known whole before streaming.

    A reply the gateway changed or built is streamed as OpenAI streams it,
    each text in one delta; an unchanged one as the upstream sent it.
    """
    set_streaming()
    if (
        prepared.soft_block is not None and len(prepared.soft_block) > 0
    ) or scope.cached.hit:
        return response_events(await _respond(scope, prepared))

    route_name = scope.route.gateway_route_config.route_name
    set_operation_category(OperationCategory.INVOCATION)
    frames: list[str] = []
    final_response = None
    async for event in prepared.invoker.stream_responses(**_call(scope, prepared)):
        if event.is_final:
            final_response = event.response
        frames.append(event.to_sse(route_name))
    if final_response is None:
        return frames

    await _count(scope, prepared, final_response)
    response = await _screen_output(scope, final_response)
    await _store(scope, prepared, response)
    if response != final_response:
        frames = response_events({**response, 'model': route_name})
    return frames


async def _screen_output(
    scope: ResponsesScope, response: dict[str, Any]
) -> dict[str, Any]:
    """Apply the output guardrails to the text of a response. A soft block
    replaces the reply.

    A route with no output guardrails opens no span.
    """
    if not scope.route.guardrails.has_output:
        return response
    return await _screen_output_in_span(scope, response)


@workflow(name='apply_responses_output_guardrails')
async def _screen_output_in_span(
    scope: ResponsesScope, response: dict[str, Any]
) -> dict[str, Any]:
    screened = await scope.guardrails.screen_output(ResponsesReply.of(response))
    if screened.soft_block:
        scope.flags |= GuardrailFlags(output_warned=True, output_blocked=True)
        text = screened.soft_block.get_soft_block_message()
        return {**response, 'output': [message_item(text)]}
    scope.flags |= GuardrailFlags(output_warned=screened.flags.output_warned)
    return screened.payload.response()


async def _count(
    scope: ResponsesScope, prepared: _Prepared, response: dict[str, Any]
) -> None:
    """Count a model's response against the limits. It runs before the
    output guardrails: the model was paid for even when they refuse the
    reply (ADR 0006).
    """
    input_tokens, _, output_tokens = responses_token_counts(response.get('usage'))
    await scope.limits.count(Usage.priced(prepared.model, input_tokens, output_tokens))


async def _store(
    scope: ResponsesScope, prepared: _Prepared, response: dict[str, Any]
) -> None:
    """Cache a model's screened response, when it completed."""
    if response.get('status') == 'completed':
        await scope.cached.store({**response, 'model': prepared.model.model_id})
