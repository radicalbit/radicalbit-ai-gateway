import json

from langchain_core.messages import BaseMessage


def build_user_content(messages: list[BaseMessage]) -> str:
    """Build a single text representation of all messages' content
    for token estimation (tiktoken).
    """
    parts: list[str] = []
    for msg in messages:
        s = stringify_message_content(msg.content)
        if s:
            parts.append(s)
    return ' '.join(parts).strip()


def build_user_content_from_texts(input_texts: list[str]) -> str:
    """Embedding inputs are list[str]. Reuse the same stringify logic for stable join."""
    return stringify_message_content(input_texts)


def _stable_json_dumps(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def stringify_message_content(content: str | list) -> str:
    """Deterministically convert BaseMessage.content into a single string.
    - str -> returned as-is
    - list[str|dict] -> join extracted parts
      - {"type":"text","text":"..."} -> include text
      - {"type":"image_url","image_url":{"url":"..."}} -> include url
      - unknown dict/list -> stable json dump
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                if item.strip():
                    parts.append(item)
                continue
            if isinstance(item, dict):
                item_type = item.get('type')
                if item_type == 'text':
                    txt = item.get('text', '')
                    if isinstance(txt, str) and txt.strip():
                        parts.append(txt)
                    elif txt is not None:
                        parts.append(str(txt))
                elif item_type == 'image_url':
                    image_url = item.get('image_url')
                    if isinstance(image_url, dict) and image_url.get('url'):
                        parts.append(str(image_url['url']))
                    else:
                        parts.append(_stable_json_dumps(item))
                else:
                    parts.append(_stable_json_dumps(item))
                continue
            parts.append(str(item))
        return ' '.join(p for p in parts if p).strip()
    return str(content).strip()
