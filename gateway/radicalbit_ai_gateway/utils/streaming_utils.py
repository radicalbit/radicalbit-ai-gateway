import datetime
from time import time
import uuid

from langchain_core.messages import AIMessageChunk
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_chunk import (
    ChatCompletionChunk,
    Choice,
    ChoiceDelta,
    ChoiceDeltaToolCall,
    ChoiceDeltaToolCallFunction,
)
from openai.types.completion_usage import CompletionUsage

from radicalbit_ai_gateway.utils.ai_gateway_types import ChunkAccumulationResult


class StreamingUtils:
    """Utility class for streaming response operations."""

    @staticmethod
    def cached_response_to_chunk(
        cached_response: ChatCompletion,
        route_name: str,
    ) -> ChatCompletionChunk:
        """Convert a cached ChatCompletion to a streaming chunk.

        Args:
            cached_response: The cached ChatCompletion response.
            route_name: The route name to use as the model identifier.

        Returns:
            A ChatCompletionChunk with finish_reason='stop'.

        """
        chunk = StreamingUtils.to_openai_chat_completion_chunk(
            AIMessageChunk(
                content=cached_response.choices[0].message.content,
                usage_metadata={
                    'input_tokens': cached_response.usage.prompt_tokens,
                    'output_tokens': cached_response.usage.completion_tokens,
                    'total_tokens': cached_response.usage.total_tokens,
                }
                if cached_response.usage
                else None,
            ),
            model_id_invoked=route_name,
            request_id=cached_response.id,
        )
        chunk.choices[0].finish_reason = 'stop'
        return chunk

    @staticmethod
    def build_soft_block_chunk(
        soft_block: ChatCompletion,
        route_name: str,
    ) -> ChatCompletionChunk:
        """Build a soft block response as a streaming chunk.

        Args:
            soft_block: The soft block ChatCompletion response.
            route_name: The route name to use as the model identifier.

        Returns:
            A ChatCompletionChunk with finish_reason='stop'.

        """
        chunk = StreamingUtils.to_openai_chat_completion_chunk(
            AIMessageChunk(content=soft_block.choices[0].message.content),
            model_id_invoked=route_name,
            request_id=soft_block.id,
        )
        chunk.choices[0].finish_reason = 'stop'
        return chunk

    @staticmethod
    def prepare_stream_options(kwargs: dict) -> dict | None:
        """Prepare stream options, forcing include_usage=True upstream.

        Modifies kwargs in-place to set stream_options with include_usage=True.
        Returns the original user stream_options for later use (to decide whether
        to yield usage chunk downstream).

        Args:
            kwargs: The keyword arguments dict to modify.

        Returns:
            The original user stream_options, or None if not provided.

        """
        user_stream_options = kwargs.get('stream_options')
        upstream_stream_options = (
            user_stream_options.copy()
            if user_stream_options and isinstance(user_stream_options, dict)
            else {}
        )
        upstream_stream_options['include_usage'] = True
        kwargs['stream_options'] = upstream_stream_options
        return user_stream_options

    @staticmethod
    def accumulate_chunk_content(
        chunk: AIMessageChunk,
        current_text: str,
    ) -> ChunkAccumulationResult:
        """Accumulate content from a streaming chunk.

        Args:
            chunk: The AIMessageChunk to process.
            current_text: The current accumulated text.

        Returns:
            A ChunkAccumulationResult with updated text and usage metadata.

        """
        updated_text = current_text
        if chunk.content:
            if isinstance(chunk.content, str):
                updated_text += chunk.content
            else:
                updated_text += str(chunk.content)
        return ChunkAccumulationResult(
            text=updated_text,
            usage_metadata=chunk.usage_metadata,
        )

    @staticmethod
    def build_usage_chunk(
        final_usage: dict,
        model_id_invoked: str,
        request_id: str,
    ) -> ChatCompletionChunk:
        """Build a usage-only chunk for streaming.

        Args:
            final_usage: Dictionary with token usage information.
            model_id_invoked: The model ID to include in the chunk.
            request_id: The request ID for the chunk.

        Returns:
            A ChatCompletionChunk containing only usage information.

        """
        return ChatCompletionChunk(
            id=request_id,
            object='chat.completion.chunk',
            created=int(datetime.datetime.now().timestamp()),
            model=model_id_invoked,
            choices=[],
            usage=CompletionUsage(
                prompt_tokens=final_usage.get('input_tokens', 0),
                completion_tokens=final_usage.get('output_tokens', 0),
                total_tokens=final_usage.get('total_tokens', 0),
                prompt_tokens_details={
                    'cached_tokens': final_usage.get('input_token_details', {}).get(
                        'cache_read', 0
                    ),
                    'audio_tokens': final_usage.get('input_token_details', {}).get(
                        'audio', 0
                    ),
                }
                if final_usage.get('input_token_details')
                else None,
                completion_tokens_details={
                    'reasoning_tokens': final_usage.get('output_token_details', {}).get(
                        'reasoning', 0
                    ),
                    'audio_tokens': final_usage.get('output_token_details', {}).get(
                        'audio', 0
                    ),
                    'accepted_prediction_tokens': final_usage.get(
                        'output_token_details', {}
                    ).get('accepted_prediction', 0),
                    'rejected_prediction_tokens': final_usage.get(
                        'output_token_details', {}
                    ).get('rejected_prediction', 0),
                }
                if final_usage.get('output_token_details')
                else None,
            ),
        )

    @staticmethod
    def to_openai_chat_completion_chunk(
        chunk: AIMessageChunk, model_id_invoked: str, request_id: str | None = None
    ) -> ChatCompletionChunk:
        choices = []

        delta_content = chunk.content
        if isinstance(delta_content, list | dict):
            delta_content = str(delta_content)

        tool_calls = None
        if chunk.tool_call_chunks:
            tool_calls = [
                ChoiceDeltaToolCall(
                    index=i,
                    id=tc_chunk['id'],
                    function=ChoiceDeltaToolCallFunction(
                        name=tc_chunk['name'], arguments=tc_chunk['args']
                    ),
                    type='function',
                )
                for i, tc_chunk in enumerate(chunk.tool_call_chunks)
            ]

        finish_reason = None
        if chunk.response_metadata:
            finish_reason_raw = chunk.response_metadata.get('finish_reason')
            if finish_reason_raw:
                finish_reason = (
                    finish_reason_raw.lower()
                    if isinstance(finish_reason_raw, str)
                    else 'stop'
                )

        choices.append(
            Choice(
                index=0,
                delta=ChoiceDelta(
                    role='assistant',
                    content=delta_content if delta_content else None,
                    tool_calls=tool_calls,
                ),
                finish_reason=finish_reason,
                logprobs=None,
            )
        )

        usage = None
        if chunk.usage_metadata:
            usage = CompletionUsage(
                prompt_tokens=chunk.usage_metadata.get('input_tokens', 0),
                completion_tokens=chunk.usage_metadata.get('output_tokens', 0),
                total_tokens=chunk.usage_metadata.get('total_tokens', 0),
                prompt_tokens_details={
                    'cached_tokens': chunk.usage_metadata.get(
                        'input_token_details', {}
                    ).get('cache_read', 0),
                    'audio_tokens': chunk.usage_metadata.get(
                        'input_token_details', {}
                    ).get('audio', 0),
                }
                if chunk.usage_metadata.get('input_token_details')
                else None,
                completion_tokens_details={
                    'reasoning_tokens': chunk.usage_metadata.get(
                        'output_token_details', {}
                    ).get('reasoning', 0),
                    'audio_tokens': chunk.usage_metadata.get(
                        'output_token_details', {}
                    ).get('audio', 0),
                    'accepted_prediction_tokens': chunk.usage_metadata.get(
                        'output_token_details', {}
                    ).get('accepted_prediction', 0),
                    'rejected_prediction_tokens': chunk.usage_metadata.get(
                        'output_token_details', {}
                    ).get('rejected_prediction', 0),
                }
                if chunk.usage_metadata.get('output_token_details')
                else None,
            )

        return ChatCompletionChunk(
            id=request_id or f'chatcmpl-{uuid.uuid4()}',
            object='chat.completion.chunk',
            created=int(time()),
            model=model_id_invoked,
            choices=choices,
            usage=usage,
        )
