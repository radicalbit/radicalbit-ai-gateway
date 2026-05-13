"""Translation utilities between Responses API and Chat Completions format.

Translates:
- ResponseCreateParams.input  → list[BaseMessage]  (LangChain format)
- ChatCompletion               → Response           (Responses API format)
- Responses API tools          → ChatCompletionToolParam list
"""

from __future__ import annotations

from typing import Any
import uuid

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam
from openai.types.responses import (
    Response,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseUsage,
)
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
)

from radicalbit_ai_gateway.models.chat_request import to_target_multimodal_parts
from radicalbit_ai_gateway.utils.exceptions import GatewayBadRequest


def _input_content_to_lc_content(content: Any) -> str | list:
    """Convert Responses API content (str or list of content parts) to LangChain format."""
    if isinstance(content, str):
        return content

    if not isinstance(content, list):
        return str(content)

    parts = []
    for item in content:
        if not isinstance(item, dict):
            parts.append({'type': 'text', 'text': str(item)})
            continue
        t = item.get('type')
        if t == 'input_text':
            parts.append({'type': 'text', 'text': item.get('text', '')})
        elif t == 'input_image':
            image_url = item.get('image_url')
            if image_url:
                if isinstance(image_url, str) and image_url.startswith('data:'):
                    # base64 data URL — reuse existing multimodal normalisation
                    parts.append({'type': 'image_url', 'image_url': {'url': image_url}})
                else:
                    parts.append({'type': 'image_url', 'image_url': {'url': image_url}})
            # file_id-based images are not supported (skip silently)
        elif t == 'input_file':
            # File attachments not supported, fall back to text placeholder
            parts.append({'type': 'text', 'text': '[file attachment not supported]'})
        else:
            parts.append({'type': 'text', 'text': str(item)})

    if not parts:
        return ''

    return parts


def input_to_langchain_messages(
    input: str | list,
    instructions: str | None = None,
) -> list[BaseMessage]:
    """Translate Responses API input to LangChain messages.

    Args:
        input: The Responses API input — a plain string or list of message items.
        instructions: Optional system instructions prepended as a SystemMessage.

    Returns:
        List of LangChain BaseMessage objects.

    """
    messages: list[BaseMessage] = []

    if instructions:
        messages.append(SystemMessage(content=instructions))

    if isinstance(input, str):
        messages.append(HumanMessage(content=input))
        return messages

    if not isinstance(input, list):
        raise GatewayBadRequest(f'Unsupported input type: {type(input).__name__}')

    for item in input:
        if not isinstance(item, dict):
            continue

        item_type = item.get('type', 'message')

        if item_type == 'message':
            role = item.get('role', 'user')
            content = item.get('content', '')
            lc_content = _input_content_to_lc_content(content)

            match role:
                case 'system' | 'developer':
                    text = (
                        lc_content if isinstance(lc_content, str) else str(lc_content)
                    )
                    messages.append(SystemMessage(content=text))

                case 'user':
                    if isinstance(lc_content, list):
                        # Normalise multimodal parts using the existing helper
                        lc_content = to_target_multimodal_parts(lc_content)
                    messages.append(HumanMessage(content=lc_content))

                case 'assistant':
                    text = (
                        lc_content if isinstance(lc_content, str) else str(lc_content)
                    )
                    messages.append(AIMessage(content=text))

                case _:
                    text = (
                        lc_content if isinstance(lc_content, str) else str(lc_content)
                    )
                    messages.append(HumanMessage(content=text))

        elif item_type == 'function_call_output':
            call_id = item.get('call_id', '')
            output = item.get('output', '')
            if not call_id:
                raise GatewayBadRequest(
                    'function_call_output item must have a call_id.'
                )
            messages.append(ToolMessage(content=str(output), tool_call_id=call_id))

        # All other item types (computer_call_output, file_search_result, etc.) are skipped.

    return messages


def responses_tools_to_chat_completions_tools(
    tools: list | None,
) -> list[ChatCompletionToolParam]:
    """Extract and convert function tools from a Responses API tools list.

    Built-in tools (file_search, web_search_preview, code_interpreter, computer_use)
    are silently skipped — they require server-side infrastructure not available here.
    """
    if not tools:
        return []

    result: list[ChatCompletionToolParam] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get('type') != 'function':
            continue

        func = tool.get('function') or {}
        # Some clients pass the function fields directly at the top level
        name = func.get('name') or tool.get('name', '')
        description = func.get('description') or tool.get('description')
        parameters = func.get('parameters') or tool.get('parameters')

        entry: dict = {'type': 'function', 'function': {'name': name}}
        if description is not None:
            entry['function']['description'] = description
        if parameters is not None:
            entry['function']['parameters'] = parameters

        result.append(entry)

    return result


def translate_tool_choice(tool_choice: Any) -> Any:
    """Translate Responses API tool_choice to Chat Completions tool_choice format."""
    if tool_choice is None:
        return 'auto'
    if isinstance(tool_choice, str):
        return tool_choice
    if isinstance(tool_choice, dict) and tool_choice.get('type') == 'function':
        func = tool_choice.get('function', {})
        name = func.get('name') if isinstance(func, dict) else None
        if name:
            return {'type': 'function', 'function': {'name': name}}
    return 'auto'


def chat_completion_to_response(
    completion: ChatCompletion,
    route_name: str,
) -> Response:
    """Translate a ChatCompletion response to a Responses API Response object.

    Args:
        completion: The ChatCompletion to translate.
        route_name: The gateway route name used as the model identifier.

    Returns:
        A Response object in Responses API format with status='completed'.

    """
    output: list = []

    if completion.choices:
        choice = completion.choices[0]
        message = choice.message

        if message.tool_calls:
            for tc in message.tool_calls:
                # ruff: noqa: PERF401
                output.append(
                    ResponseFunctionToolCall(
                        arguments=tc.function.arguments,
                        call_id=tc.id,
                        name=tc.function.name,
                        type='function_call',
                        id=tc.id,
                        status='completed',
                    )
                )
        elif message.content is not None:
            output.append(
                ResponseOutputMessage(
                    id=f'msg_{uuid.uuid4().hex[:24]}',
                    content=[
                        ResponseOutputText(
                            text=message.content,
                            type='output_text',
                            annotations=[],
                        )
                    ],
                    role='assistant',
                    status='completed',
                    type='message',
                )
            )

    usage = None
    if completion.usage:
        u = completion.usage
        cached = 0
        reasoning = 0
        if u.prompt_tokens_details and u.prompt_tokens_details.cached_tokens:
            cached = u.prompt_tokens_details.cached_tokens
        if u.completion_tokens_details and u.completion_tokens_details.reasoning_tokens:
            reasoning = u.completion_tokens_details.reasoning_tokens
        usage = ResponseUsage(
            input_tokens=u.prompt_tokens,
            input_tokens_details=InputTokensDetails(cached_tokens=cached),
            output_tokens=u.completion_tokens,
            output_tokens_details=OutputTokensDetails(reasoning_tokens=reasoning),
            total_tokens=u.total_tokens,
        )

    return Response(
        id=completion.id,
        created_at=float(completion.created),
        error=None,
        model=route_name,
        object='response',
        output=output,
        parallel_tool_calls=True,
        status='completed',
        temperature=None,
        tool_choice='auto',
        tools=[],
        usage=usage,
    )
