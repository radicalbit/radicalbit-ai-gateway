import ast
from collections.abc import Iterable, Mapping
import json
import logging
import logging.config
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import GatewayBadRequest

app_config = get_app_config()
logging_config_dict = app_config.log_config.model_dump()
logging.config.dictConfig(logging_config_dict)
logger = logging.getLogger(app_config.log_config.logger_name)


def parse_tool_calls(tool_calls: list):
    """Parse tool calls from the API to LangChain format."""
    return [
        {
            'name': tc.get('function', {}).get('name'),
            'args': json.loads(tc.get('function', {}).get('arguments', '{}')),
            'id': tc.get('id'),
        }
        for tc in tool_calls
    ]


def _parse_content_maybe(content: Any) -> Any:
    """Try to parse JSON/py-literal strings into Python objects; otherwise return as-is."""
    if not isinstance(content, str):
        return content
    s = content.strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    try:
        return ast.literal_eval(s)
    except Exception:
        return content


def _parse_data_url(val: str) -> tuple[str | None, str | None]:
    """Split data URL into (mime, base64) or return (None, original) for raw base64."""
    if isinstance(val, str) and val.startswith('data:') and ',' in val:
        header, b64 = val.split(',', 1)
        mime = header[5:].split(';')[0] or None
        return mime, b64
    if isinstance(val, str):
        return None, val
    return None, None


def _remap_file_data(obj: Any) -> Any:
    """Rename 'file_data' -> 'data' inside file parts; keep structure intact."""
    if isinstance(obj, list):
        return [_remap_file_data(x) for x in obj]
    if isinstance(obj, Mapping):
        d = {k: _remap_file_data(v) for k, v in obj.items()}
        if d.get('type') == 'file':
            if isinstance(d.get('file'), Mapping):
                f = dict(d['file'])
                if 'file_data' in f and 'data' not in f:
                    f['data'] = f.pop('file_data')
                d['file'] = f
            if 'file_data' in d and 'data' not in d:
                d['data'] = d.pop('file_data')
        return d
    return obj


def _to_image_or_file_part(data_str: str, filename: str | None = None) -> dict:
    """Build a normalized image/file part from a data URL or raw base64."""
    mime, b64 = _parse_data_url(data_str)

    if mime and mime.startswith('image/'):
        return {
            'type': 'image',
            'source_type': 'base64',
            'data': b64,
            'mime_type': mime,
        }

    return {
        'type': 'file',
        'source_type': 'base64',
        'data': b64,
        'mime_type': mime or 'application/octet-stream',
        **({'filename': filename} if filename else {}),
    }


def to_target_multimodal_parts(parts: Any) -> list[dict]:
    """Normalize incoming parts to the gateway's target multimodal format.
    - text -> {"type":"text","text": "..."}
    - image_url (data URL) -> {"type":"image", "source_type":"base64", ...}
    - file (data URL) -> {"type":"file", "source_type":"base64", ...}
    - image_url (http/https) -> keep {"type":"image_url","image_url":{"url":...}}
    """
    parts = _remap_file_data(_parse_content_maybe(parts))
    out: list[dict] = []

    if not isinstance(parts, list):
        return [{'type': 'text', 'text': str(parts)}]

    for p in parts:
        t = p.get('type')
        if t == 'text':
            out.append({'type': 'text', 'text': p.get('text', '')})
        elif t == 'image_url':
            url = (p.get('image_url') or {}).get('url', '')
            if url.startswith('data:'):
                out.append(_to_image_or_file_part(url))
            else:
                out.append({'type': 'image_url', 'image_url': {'url': url}})
        elif t == 'file':
            f = p.get('file') if isinstance(p.get('file'), Mapping) else p
            data_url = f.get('data') or f.get('file_data')
            filename = f.get('filename')
            if isinstance(data_url, str):
                out.append(_to_image_or_file_part(data_url, filename))
        else:
            out.append({'type': 'text', 'text': str(p)})
    return out


def _coerce_to_text(content: Any) -> str:
    """Return a safe string for non-user roles."""
    if isinstance(content, str):
        return content
    if content is None:
        return ''
    if isinstance(content, bytes | bytearray):
        try:
            return content.decode('utf-8')
        except Exception:
            return str(content)
    if isinstance(content, list | dict):
        try:
            return json.dumps(content, ensure_ascii=False)
        except Exception:
            return str(content)
    return str(content)


def select_message_by_role(
    role: str, content: list | str, tool_calls: list, tool_call_id: str | None
) -> BaseMessage:
    match role:
        case 'system':
            return SystemMessage(content=_coerce_to_text(content))

        case 'user' | 'developer':
            logger.debug('User/Developer message: %s', content)
            normalized_parts = (
                to_target_multimodal_parts(content)
                if isinstance(content, list)
                else content
            )
            logger.debug('User/Developer message (normalized): %s', normalized_parts)
            return HumanMessage(content=normalized_parts)

        case 'assistant':
            return AIMessage(content=_coerce_to_text(content), tool_calls=tool_calls)

        case 'function':
            return FunctionMessage(content=_coerce_to_text(content))

        case 'tool':
            if not tool_call_id:
                raise GatewayBadRequest('ToolMessage must have tool_call_id.')
            return ToolMessage(
                content=_coerce_to_text(content), tool_call_id=tool_call_id
            )

        case _:
            raise GatewayBadRequest(f'Unsupported role: {role}')


def convert_openai_messages(messages: list) -> list[BaseMessage]:
    """Convert OpenAI messages to LangChain messages, tolerando tipi atipici."""
    openai_messages: list[BaseMessage] = []
    for m in messages:
        raw = m.get('content', '')

        if isinstance(raw, Iterable) and not isinstance(raw, str):
            content = list(raw)
        else:
            content = str(raw)

        message = select_message_by_role(
            role=m.get('role'),
            content=content,
            tool_calls=parse_tool_calls(list(m.get('tool_calls', []) or [])),
            tool_call_id=m.get('tool_call_id'),
        )
        openai_messages.append(message)

    return openai_messages
