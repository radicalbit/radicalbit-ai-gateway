"""Chat message types exchanged between the gateway, plugins and model providers.

The field layout (names, order and defaults) is part of the gateway's contract:
exact and semantic cache keys embed ``model_dump_json()`` of these messages, so
changing it invalidates every cached entry.
"""

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# pydantic needs typing_extensions.TypedDict before Python 3.12.
from typing_extensions import NotRequired, TypedDict

MessageContent = str | list[str | dict[Any, Any]]


class InputTokenDetails(TypedDict, total=False):
    # Providers may add further keys (e.g. ephemeral_5m_input_tokens).
    audio: int
    cache_creation: int
    cache_read: int


class OutputTokenDetails(TypedDict, total=False):
    audio: int
    reasoning: int


class UsageMetadata(TypedDict):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_token_details: NotRequired[InputTokenDetails]
    output_token_details: NotRequired[OutputTokenDetails]


class ToolCall(TypedDict):
    name: str
    args: dict[str, Any]
    id: str | None
    type: NotRequired[Literal['tool_call']]


class ToolCallChunk(TypedDict):
    name: str | None
    args: str | None
    id: str | None
    index: int | None
    type: NotRequired[Literal['tool_call_chunk']]


class InvalidToolCall(TypedDict):
    # Serialized in this key order, unlike ToolCall and ToolCallChunk.
    type: Literal['invalid_tool_call']
    id: str | None
    name: str | None
    args: str | None
    error: str | None
    index: NotRequired[int | str]
    extras: NotRequired[dict[str, Any]]


def tool_call(*, name: str, args: dict[str, Any], id: str | None) -> ToolCall:  # noqa: A002
    return ToolCall(name=name, args=args, id=id, type='tool_call')


def tool_call_chunk(
    *,
    name: str | None = None,
    args: str | None = None,
    id: str | None = None,  # noqa: A002
    index: int | None = None,
) -> ToolCallChunk:
    return ToolCallChunk(
        name=name, args=args, id=id, index=index, type='tool_call_chunk'
    )


def invalid_tool_call(
    *,
    name: str | None = None,
    args: str | None = None,
    id: str | None = None,  # noqa: A002
    error: str | None = None,
) -> InvalidToolCall:
    return InvalidToolCall(
        name=name, args=args, id=id, error=error, type='invalid_tool_call'
    )


class BaseMessage(BaseModel):
    """Base for every chat message. ``content`` may be passed positionally."""

    model_config = ConfigDict(extra='allow')

    content: MessageContent
    additional_kwargs: dict[Any, Any] = Field(default_factory=dict)
    response_metadata: dict[Any, Any] = Field(default_factory=dict)
    type: str
    name: str | None = None
    id: str | None = Field(default=None, coerce_numbers_to_str=True)

    def __init__(self, content: MessageContent | None = None, **kwargs: Any):
        super().__init__(content=content, **kwargs)

    @property
    def text(self) -> str:
        """The message's text: string content, or its text blocks joined."""
        if isinstance(self.content, str):
            return self.content
        return ''.join(
            block if isinstance(block, str) else block['text']
            for block in self.content
            if isinstance(block, str)
            or (block.get('type') == 'text' and isinstance(block.get('text'), str))
        )


class HumanMessage(BaseMessage):
    type: Literal['human'] = 'human'


class SystemMessage(BaseMessage):
    type: Literal['system'] = 'system'


class FunctionMessage(BaseMessage):
    name: str
    type: Literal['function'] = 'function'


class ToolMessage(BaseMessage):
    tool_call_id: str
    type: Literal['tool'] = 'tool'
    artifact: Any = None
    status: Literal['success', 'error'] = 'success'

    @model_validator(mode='before')
    @classmethod
    def _coerce_args(cls, values: dict[str, Any]) -> dict[str, Any]:
        content = values['content']
        if isinstance(content, tuple):
            content = list(content)
        if not isinstance(content, str | list):
            values['content'] = str(content)
        elif isinstance(content, list):
            values['content'] = [
                x if isinstance(x, str | dict) else str(x) for x in content
            ]
        tool_call_id = values['tool_call_id']
        if isinstance(tool_call_id, int | float):
            values['tool_call_id'] = str(tool_call_id)
        return values


class AIMessage(BaseMessage):
    tool_calls: list[ToolCall] = Field(default_factory=list)
    invalid_tool_calls: list[InvalidToolCall] = Field(default_factory=list)
    usage_metadata: UsageMetadata | None = None
    type: Literal['ai'] = 'ai'

    @model_validator(mode='before')
    @classmethod
    def _normalize_tool_calls(cls, values: dict[str, Any]) -> Any:
        # Every tool-call-like dict carries its ``type`` tag, in a fixed key
        # order, whatever the caller passed.
        if tool_calls := values.get('tool_calls'):
            values['tool_calls'] = [
                tool_call(
                    **{k: v for k, v in tc.items() if k not in {'type', 'extras'}}
                )
                for tc in tool_calls
            ]
        if invalid := values.get('invalid_tool_calls'):
            values['invalid_tool_calls'] = [
                invalid_tool_call(**{k: v for k, v in tc.items() if k != 'type'})
                for tc in invalid
            ]
        if chunks := values.get('tool_call_chunks'):
            values['tool_call_chunks'] = [
                tool_call_chunk(**{k: v for k, v in tc.items() if k != 'type'})
                for tc in chunks
            ]
        return values


class AIMessageChunk(AIMessage):
    """A streamed piece of an assistant message."""

    type: Literal['AIMessageChunk'] = 'AIMessageChunk'  # type: ignore[assignment]
    tool_call_chunks: list[ToolCallChunk] = Field(default_factory=list)
    chunk_position: Literal['last'] | None = None

    @model_validator(mode='after')
    def _init_tool_calls(self):
        if not self.tool_call_chunks:
            if self.tool_calls:
                self.tool_call_chunks = [
                    tool_call_chunk(
                        name=tc['name'],
                        args=json.dumps(tc['args']),
                        id=tc['id'],
                        index=None,
                    )
                    for tc in self.tool_calls
                ]
            if self.invalid_tool_calls:
                self.tool_call_chunks = [
                    *self.tool_call_chunks,
                    *(
                        tool_call_chunk(
                            name=tc['name'], args=tc['args'], id=tc['id'], index=None
                        )
                        for tc in self.invalid_tool_calls
                    ),
                ]
            return self
        tool_calls: list[ToolCall] = []
        invalid: list[InvalidToolCall] = []
        for chunk in self.tool_call_chunks:
            try:
                args = parse_partial_json(chunk['args']) if chunk['args'] else {}
            except Exception:
                args = None
            if isinstance(args, dict):
                tool_calls.append(
                    tool_call(name=chunk['name'] or '', args=args, id=chunk['id'])
                )
            else:
                invalid.append(
                    invalid_tool_call(
                        name=chunk['name'],
                        args=chunk['args'],
                        id=chunk['id'],
                        error=None,
                    )
                )
        self.tool_calls = tool_calls
        self.invalid_tool_calls = invalid
        return self


def parse_partial_json(s: str) -> Any:
    """Parse JSON that may be truncated mid-stream by closing open scopes.

    Returns None on mismatched closing brackets; raises ``JSONDecodeError``
    when no prefix of ``s`` can be completed into valid JSON.
    """
    try:
        return json.loads(s, strict=False)
    except json.JSONDecodeError:
        pass
    new_chars: list[str] = []
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in s:
        new_char = char
        if in_string:
            if char == '"' and not escaped:
                in_string = False
            elif char == '\n' and not escaped:
                new_char = '\\n'
            elif char == '\\':
                escaped = not escaped
            else:
                escaped = False
        elif char == '"':
            in_string = True
            escaped = False
        elif char == '{':
            stack.append('}')
        elif char == '[':
            stack.append(']')
        elif char in {'}', ']'}:
            if stack and stack[-1] == char:
                stack.pop()
            else:
                return None
        new_chars.append(new_char)
    if in_string:
        if escaped:
            new_chars.pop()
        new_chars.append('"')
    stack.reverse()
    while new_chars:
        try:
            return json.loads(''.join(new_chars + stack), strict=False)
        except json.JSONDecodeError:
            new_chars.pop()
    return json.loads(s, strict=False)
