"""Schema and content helpers shared by the chat providers.

Tools and structured output are described as LangChain described them, so
the schemas sent upstream stay the same.
"""

import copy
from typing import Any

from pydantic import BaseModel

# Data block types of the LangChain standard content format.
_DATA_BLOCK_TYPES = ('image', 'video', 'audio', 'text-plain', 'file')


class OutputParserError(ValueError):
    """A reply could not be parsed into the requested structure."""


def is_data_content_block(block: dict) -> bool:
    """Whether ``block`` is a standard multimodal data block (image, file...)."""
    if block.get('type') not in _DATA_BLOCK_TYPES:
        return False
    if any(key in block for key in ('url', 'base64', 'file_id', 'text')):
        return True
    if 'source_type' in block:
        source_type = block['source_type']
        if (source_type == 'url' and 'url' in block) or (
            source_type == 'base64' and 'data' in block
        ):
            return True
        if (source_type == 'id' and 'id' in block) or (
            source_type == 'text' and 'url' in block
        ):
            return True
    return False


def rm_titles(kv: dict, prev_key: str = '') -> dict:
    """Drop JSON-schema ``title``s, keeping properties that are named title."""
    new_kv = {}
    for k, v in kv.items():
        if k == 'title':
            if isinstance(v, dict) and prev_key == 'properties':
                new_kv[k] = rm_titles(v, k)
        elif isinstance(v, dict):
            new_kv[k] = rm_titles(v, k)
        else:
            new_kv[k] = v
    return new_kv


def _dereference(node: Any, defs: dict) -> Any:
    if isinstance(node, dict):
        ref = node.get('$ref')
        if isinstance(ref, str) and ref.startswith('#/$defs/'):
            target = _dereference(copy.deepcopy(defs[ref.split('/')[-1]]), defs)
            rest = {k: _dereference(v, defs) for k, v in node.items() if k != '$ref'}
            return {**target, **rest}
        return {k: _dereference(v, defs) for k, v in node.items()}
    if isinstance(node, list):
        return [_dereference(v, defs) for v in node]
    return node


def pydantic_to_function(schema: type[BaseModel]) -> dict:
    """Describe a pydantic model as an OpenAI function definition."""
    json_schema = schema.model_json_schema()
    defs = json_schema.pop('$defs', {})
    json_schema = _dereference(json_schema, defs)
    title = json_schema.pop('title', '')
    description = json_schema.pop('description', '')
    return {
        'name': title,
        'description': description,
        'parameters': rm_titles(json_schema),
    }
