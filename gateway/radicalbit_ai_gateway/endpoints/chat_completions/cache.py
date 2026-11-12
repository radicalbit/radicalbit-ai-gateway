"""How a chat completion is cached: what keys the request, and the reply
as stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import json
import logging
from typing import Any

from openai.types.chat.chat_completion import ChatCompletion

from radicalbit_ai_gateway.caching.route_cache import Hit
from radicalbit_ai_gateway.llm.messages import AIMessage, BaseMessage, HumanMessage
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.chat_utils import ChatUtils
from radicalbit_ai_gateway.utils.content_utils import ContentUtils

logger = logging.getLogger(get_app_config().log_config.logger_name)


@dataclass(frozen=True)
class StreamedReply:
    """A streamed chat reply, stored as the completion a non-streamed call
    would have got: its text, tool calls, reasoning and finish reason.
    """

    message: AIMessage
    model_id: str
    request_id: str | None = None

    def completion(self) -> ChatCompletion:
        return ChatUtils.to_openai_chat_completion(
            self.message,
            model_id_invoked=self.model_id,
            request_id=self.request_id,
        )


@dataclass(frozen=True)
class ChatEntry:
    """A chat completion request, keyed on its turn from the last user
    message on, its tools and its parameters.
    """

    messages: list[BaseMessage]
    tools: Any = None
    tool_choice: Any = None
    params: dict = field(default_factory=dict)
    #: Whether the reply is streamed: a stream replays a hit's text only.
    stream: bool = False

    lookup_spans = ('lookup_cache',)
    get_spans = ('get_cached_response',)
    exact_only = False
    hit_log = 'Cache hit. Hash name: %s'

    def _turn(self) -> list[BaseMessage]:
        last = -1
        for index, message in enumerate(self.messages):
            if isinstance(message, HumanMessage):
                last = index
        return self.messages[last:] if last != -1 else []

    def signature(self) -> str | None:
        turn = self._turn()
        if not turn:
            return None
        # Streamed or not, a request asks for the same reply: the stream
        # flags stay out of the key, as on Responses.
        params = {
            name: value
            for name, value in self.params.items()
            if name not in ('stream', 'stream_options')
        }
        return (
            f'messages:{[message.model_dump_json(indent=None) for message in turn]};'
            f'tools:{json.dumps(self.tools)};'
            f'tool_choice:{json.dumps(self.tool_choice)};'
            f'extra_args:{json.dumps(params)}'
        )

    def text(self) -> str:
        turn = self._turn()
        return ContentUtils.extract_text_content(turn[0].content) if turn else ''

    def parse(self, raw: str) -> ChatCompletion | None:
        try:
            completion = ChatCompletion.model_validate(json.loads(raw))
        except ValueError:
            # A semantic cache shares a route's entries between endpoints:
            # a Responses API entry is a miss here.
            logger.debug('Cached entry is not a chat completion: cache miss')
            return None
        if self.stream and completion.choices[0].message.tool_calls:
            # A stream hit replays the reply's text only.
            logger.debug('Cached reply has tool calls a stream cannot replay')
            return None
        return completion

    def dump(self, value: ChatCompletion | StreamedReply) -> str:
        if isinstance(value, StreamedReply):
            value = value.completion()
        return value.model_dump_json(indent=None)

    def hit(self, value: ChatCompletion) -> Hit:
        return Hit(value.model, value.usage)

    def refresh(self, value: ChatCompletion) -> ChatCompletion:
        return value.model_copy(
            update={'created': int(datetime.datetime.now().timestamp())}
        )

    def store_spans(self, value) -> tuple[str, ...]:
        if isinstance(value, StreamedReply):
            return ('set_cached_stream_response', 'set_cached_response')
        return ('set_cached_response',)
