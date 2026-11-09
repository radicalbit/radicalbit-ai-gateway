"""Responses API requests: the order a request goes through the route's
policies.

The policies read the request's texts as chat messages (see
``ResponsesRequest``); what they change is written back into the body that
goes upstream.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

from traceloop.sdk.decorators import workflow

from radicalbit_ai_gateway.caching.route_cache import ResponsesEntry
from radicalbit_ai_gateway.guardrails.guardrails import (
    Conversation,
    GuardrailFlags,
    ResponsesReply,
)
from radicalbit_ai_gateway.limiting.limits import Usage
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.pipeline.conversation import (
    apply_config_prompt,
    check_chat_limits,
    route_chat,
)
from radicalbit_ai_gateway.pipeline.scope import RequestScope
from radicalbit_ai_gateway.preprocessing import run_preprocessing
from radicalbit_ai_gateway.responses.events import response_events
from radicalbit_ai_gateway.responses.output import (
    gateway_response,
    message_item,
    usage_token_counts,
)
from radicalbit_ai_gateway.responses.request import (
    ResponsesRequest,
    apply_governance,
    check_supported,
    references_stored_state,
)
from radicalbit_ai_gateway.utils.exceptions import GatewayBadRequest
from radicalbit_ai_gateway.utils.trace_attributes import (
    OperationCategory,
    set_operation_category,
    set_streaming,
)


@dataclass
class _Prepared:
    """A request after its input policies, before the model call.

    ``allow_fallback`` is False when the request continues state stored at
    the provider, which only the selected model's account can serve.
    ``soft_block`` is the response object of an input soft block.
    """

    body: dict
    model: Model
    allow_fallback: bool
    soft_block: dict | None = None


async def respond(scope: RequestScope, body: dict) -> dict:
    """Answer a Responses API request with one response object."""
    return await _respond(scope, await _prepare(scope, body))


async def stream(scope: RequestScope, body: dict) -> AsyncIterator[str]:
    """Answer a Responses API request with SSE frames.

    The upstream's events are relayed as they come, unless the whole reply
    must be known first: a soft block, a cache hit, or a reply the output
    guardrails must pass. Then the frames are known when this returns.
    """
    prepared = await _prepare(scope, body)
    if prepared.soft_block or scope.cached.hit or scope.route.guardrails.has_output:
        return _aiter(await _buffered(scope, prepared))
    return _live(scope, prepared)


async def _prepare(scope: RequestScope, body: dict) -> _Prepared:
    route = scope.route
    config = route.gateway_route_config
    route_name = config.route_name
    if not route.chat_invoker:
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
    if not route.chat_invoker.supports_responses(model.model_id):
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
            model,
            allow_fallback,
            soft_block=gateway_response(
                scope.identity.request_uuid,
                route_name,
                body,
                screened.soft_block.get_soft_block_message(),
            ),
        )

    if model.effective_prompt:
        request.write_back(messages[1:])
        request.insert_prompt(messages[0], model.role)
    else:
        request.write_back(messages)

    scope.cached = await scope.cache.lookup(ResponsesEntry(request.body))
    return _Prepared(request.body, model, allow_fallback)


async def _respond(scope: RequestScope, prepared: _Prepared) -> dict:
    route_name = scope.route.gateway_route_config.route_name
    if prepared.soft_block:
        return prepared.soft_block

    if scope.cached.hit:
        response = scope.cached.value
    else:
        set_operation_category(OperationCategory.INVOCATION)
        response, _ = await scope.route.chat_invoker.complete_responses(
            **_call(scope, prepared)
        )

    response = await _screen_output(scope, response)
    if not scope.cached.hit:
        await _account(scope, prepared, response)
    return {**response, 'model': route_name}


def _call(scope: RequestScope, prepared: _Prepared) -> dict:
    """Return the arguments of the invoker's call for a prepared request."""
    return {
        'identity': scope.identity,
        'body': prepared.body,
        'model_id': prepared.model.model_id,
        'allow_fallback': prepared.allow_fallback,
    }


async def _live(scope: RequestScope, prepared: _Prepared) -> AsyncIterator[str]:
    """Relay the upstream's events, then account for the final response."""
    set_streaming()
    set_operation_category(OperationCategory.INVOCATION)
    route_name = scope.route.gateway_route_config.route_name
    final_response = None
    async for event in scope.route.chat_invoker.stream_responses(
        **_call(scope, prepared)
    ):
        if event.is_final:
            final_response = event.response
        yield event.to_sse(route_name)

    if final_response:
        await _account(scope, prepared, final_response)


async def _buffered(scope: RequestScope, prepared: _Prepared) -> list[str]:
    """Return the frames of a reply known whole before streaming.

    A reply the gateway changed or built is streamed as OpenAI streams it,
    each text in one delta; an unchanged one as the upstream sent it.
    """
    set_streaming()
    if prepared.soft_block or scope.cached.hit:
        return response_events(await _respond(scope, prepared))

    route_name = scope.route.gateway_route_config.route_name
    set_operation_category(OperationCategory.INVOCATION)
    frames: list[str] = []
    final_response = None
    async for event in scope.route.chat_invoker.stream_responses(
        **_call(scope, prepared)
    ):
        if event.is_final:
            final_response = event.response
        frames.append(event.to_sse(route_name))
    if final_response is None:
        return frames

    response = await _screen_output(scope, final_response)
    await _account(scope, prepared, response)
    if response != final_response:
        frames = response_events({**response, 'model': route_name})
    return frames


@workflow(name='apply_responses_output_guardrails')
async def _screen_output(scope: RequestScope, response: dict) -> dict:
    """Apply the output guardrails to the text of a response. A soft block
    replaces the reply.
    """
    if not scope.route.guardrails.has_output:
        return response
    screened = await scope.guardrails.screen_output(ResponsesReply.of(response))
    if screened.soft_block:
        scope.flags |= GuardrailFlags(output_warned=True, output_blocked=True)
        text = screened.soft_block.get_soft_block_message()
        return {**response, 'output': [message_item(text)]}
    scope.flags |= GuardrailFlags(output_warned=screened.flags.output_warned)
    return screened.payload.response()


async def _account(scope: RequestScope, prepared: _Prepared, response: dict) -> None:
    """Count a model's response against the limits, and cache it."""
    input_tokens, _, output_tokens = usage_token_counts(response.get('usage'))
    await scope.limits.count(Usage.priced(prepared.model, input_tokens, output_tokens))
    if response.get('status') == 'completed':
        await scope.cached.store({**response, 'model': prepared.model.model_id})


async def _aiter(items: list) -> AsyncIterator:
    for item in items:
        yield item
