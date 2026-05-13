"""Streaming adapter: translates a stream of ChatCompletionChunk objects
to SSE-formatted ResponseStreamEvent strings for the Responses API endpoint.

Emits events in the standard OpenAI Responses API streaming sequence:
  response.created → response.in_progress →
  response.output_item.added → response.content_part.added →
  response.output_text.delta (× N) →
  response.output_text.done → response.content_part.done →
  response.output_item.done → response.completed
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from time import time
import uuid

from openai.types.chat.chat_completion_chunk import ChatCompletionChunk
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseContentPartAddedEvent,
    ResponseContentPartDoneEvent,
    ResponseCreatedEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseFunctionToolCall,
    ResponseInProgressEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseTextDeltaEvent,
    ResponseTextDoneEvent,
    ResponseUsage,
)
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
)


def build_skeleton_response(
    route_name: str,
    request_id: str,
    instructions: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    tool_choice: str | None = None,
) -> Response:
    """Build a skeleton Response with status='in_progress' to open a streaming session."""
    return Response(
        id=request_id,
        created_at=float(int(time())),
        error=None,
        model=route_name,
        object='response',
        output=[],
        parallel_tool_calls=True,
        status='in_progress',
        temperature=temperature,
        tool_choice=tool_choice or 'auto',
        tools=[],
        instructions=instructions,
        top_p=top_p,
    )


async def chat_chunks_to_response_events(
    chunks: AsyncIterator[ChatCompletionChunk],
    skeleton: Response,
) -> AsyncIterator[str]:
    r"""Translate an async stream of ChatCompletionChunks to SSE strings.

    Yields ``data: <json>\\n\\n`` strings suitable for a StreamingResponse.
    The final ``data: [DONE]\\n\\n`` marker is NOT yielded here — the caller
    is responsible for appending it after this generator is exhausted.
    """
    seq = 0

    def _sse(event) -> str:
        return f'data: {event.model_dump_json(exclude_none=True)}\n\n'

    # ── Initial events ──────────────────────────────────────────────────────
    yield _sse(
        ResponseCreatedEvent(
            response=skeleton,
            sequence_number=seq,
            type='response.created',
        )
    )
    seq += 1

    yield _sse(
        ResponseInProgressEvent(
            response=skeleton.model_copy(update={'status': 'in_progress'}),
            sequence_number=seq,
            type='response.in_progress',
        )
    )
    seq += 1

    # ── State ───────────────────────────────────────────────────────────────
    msg_item_id = f'msg_{uuid.uuid4().hex[:24]}'
    text_started = False
    full_text = ''

    # {tool_call_index: {item_id, call_id, name, args}}
    func_state: dict[int, dict] = {}

    final_usage = None

    # ── Process chunks ──────────────────────────────────────────────────────
    async for chunk in chunks:
        # Usage comes in the final usage-only chunk (no choices)
        if chunk.usage:
            final_usage = chunk.usage

        if not chunk.choices:
            continue

        choice = chunk.choices[0]
        delta = choice.delta

        # ── Text deltas ──────────────────────────────────────────────────
        if delta.content:
            if not text_started:
                text_started = True
                msg_item = ResponseOutputMessage(
                    id=msg_item_id,
                    content=[],
                    role='assistant',
                    status='in_progress',
                    type='message',
                )
                yield _sse(
                    ResponseOutputItemAddedEvent(
                        item=msg_item,
                        output_index=0,
                        sequence_number=seq,
                        type='response.output_item.added',
                    )
                )
                seq += 1

                yield _sse(
                    ResponseContentPartAddedEvent(
                        content_index=0,
                        item_id=msg_item_id,
                        output_index=0,
                        part=ResponseOutputText(
                            text='', type='output_text', annotations=[]
                        ),
                        sequence_number=seq,
                        type='response.content_part.added',
                    )
                )
                seq += 1

            full_text += delta.content
            yield _sse(
                ResponseTextDeltaEvent(
                    content_index=0,
                    delta=delta.content,
                    item_id=msg_item_id,
                    logprobs=[],
                    output_index=0,
                    sequence_number=seq,
                    type='response.output_text.delta',
                )
            )
            seq += 1

        # ── Tool call deltas ─────────────────────────────────────────────
        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index

                if idx not in func_state:
                    item_id = f'fc_{uuid.uuid4().hex[:24]}'
                    func_state[idx] = {
                        'item_id': item_id,
                        'call_id': tc.id or '',
                        'name': (tc.function.name if tc.function else '') or '',
                        'args': '',
                    }
                    func_item = ResponseFunctionToolCall(
                        arguments='',
                        call_id=func_state[idx]['call_id'],
                        name=func_state[idx]['name'],
                        type='function_call',
                        id=item_id,
                        status='in_progress',
                    )
                    yield _sse(
                        ResponseOutputItemAddedEvent(
                            item=func_item,
                            output_index=idx,
                            sequence_number=seq,
                            type='response.output_item.added',
                        )
                    )
                    seq += 1

                state = func_state[idx]
                if tc.function:
                    if tc.function.name and not state['name']:
                        state['name'] = tc.function.name
                    if tc.function.arguments:
                        state['args'] += tc.function.arguments
                        yield _sse(
                            ResponseFunctionCallArgumentsDeltaEvent(
                                delta=tc.function.arguments,
                                item_id=state['item_id'],
                                output_index=idx,
                                sequence_number=seq,
                                type='response.function_call_arguments.delta',
                            )
                        )
                        seq += 1

    # ── Done events for text ─────────────────────────────────────────────────
    if text_started:
        yield _sse(
            ResponseTextDoneEvent(
                content_index=0,
                item_id=msg_item_id,
                logprobs=[],
                output_index=0,
                sequence_number=seq,
                text=full_text,
                type='response.output_text.done',
            )
        )
        seq += 1

        yield _sse(
            ResponseContentPartDoneEvent(
                content_index=0,
                item_id=msg_item_id,
                output_index=0,
                part=ResponseOutputText(
                    text=full_text, type='output_text', annotations=[]
                ),
                sequence_number=seq,
                type='response.content_part.done',
            )
        )
        seq += 1

        done_msg = ResponseOutputMessage(
            id=msg_item_id,
            content=[
                ResponseOutputText(text=full_text, type='output_text', annotations=[])
            ],
            role='assistant',
            status='completed',
            type='message',
        )
        yield _sse(
            ResponseOutputItemDoneEvent(
                item=done_msg,
                output_index=0,
                sequence_number=seq,
                type='response.output_item.done',
            )
        )
        seq += 1

    # ── Done events for tool calls ───────────────────────────────────────────
    for idx in sorted(func_state.keys()):
        state = func_state[idx]
        yield _sse(
            ResponseFunctionCallArgumentsDoneEvent(
                arguments=state['args'],
                item_id=state['item_id'],
                name=state['name'],
                output_index=idx,
                sequence_number=seq,
                type='response.function_call_arguments.done',
            )
        )
        seq += 1

        done_func = ResponseFunctionToolCall(
            arguments=state['args'],
            call_id=state['call_id'],
            name=state['name'],
            type='function_call',
            id=state['item_id'],
            status='completed',
        )
        yield _sse(
            ResponseOutputItemDoneEvent(
                item=done_func,
                output_index=idx,
                sequence_number=seq,
                type='response.output_item.done',
            )
        )
        seq += 1

    # ── Build final output list ──────────────────────────────────────────────
    output_items: list = []
    if text_started:
        output_items.append(
            ResponseOutputMessage(
                id=msg_item_id,
                content=[
                    ResponseOutputText(
                        text=full_text, type='output_text', annotations=[]
                    )
                ],
                role='assistant',
                status='completed',
                type='message',
            )
        )
    for idx in sorted(func_state.keys()):
        state = func_state[idx]
        output_items.append(
            ResponseFunctionToolCall(
                arguments=state['args'],
                call_id=state['call_id'],
                name=state['name'],
                type='function_call',
                id=state['item_id'],
                status='completed',
            )
        )

    # ── Build usage ──────────────────────────────────────────────────────────
    resp_usage = None
    if final_usage:
        u = final_usage
        cached = 0
        reasoning = 0
        if u.prompt_tokens_details and u.prompt_tokens_details.cached_tokens:
            cached = u.prompt_tokens_details.cached_tokens
        if u.completion_tokens_details and u.completion_tokens_details.reasoning_tokens:
            reasoning = u.completion_tokens_details.reasoning_tokens
        resp_usage = ResponseUsage(
            input_tokens=u.prompt_tokens,
            input_tokens_details=InputTokensDetails(cached_tokens=cached),
            output_tokens=u.completion_tokens,
            output_tokens_details=OutputTokensDetails(reasoning_tokens=reasoning),
            total_tokens=u.total_tokens,
        )

    completed = skeleton.model_copy(
        update={'status': 'completed', 'output': output_items, 'usage': resp_usage}
    )
    yield _sse(
        ResponseCompletedEvent(
            response=completed,
            sequence_number=seq,
            type='response.completed',
        )
    )


async def list_chunks_to_response_events(
    chunks: list[ChatCompletionChunk],
    skeleton: Response,
) -> AsyncIterator[str]:
    async def _iter():
        for chunk in chunks:
            yield chunk

    async for sse in chat_chunks_to_response_events(_iter(), skeleton):
        yield sse
