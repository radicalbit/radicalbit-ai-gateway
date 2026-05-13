from __future__ import annotations

from functools import lru_cache
import logging
from typing import Protocol, runtime_checkable

from deepseek_tokenizer import ds_token
import tiktoken

from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import ModelInvokerBadRequest
from radicalbit_ai_gateway.utils.parse_provider_and_model import (
    parse_provider_and_model,
)

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)

DEFAULT_ENCODING = 'cl100k_base'
OPENAI_PROVIDERS = frozenset({'openai', 'azure'})
DEEPSEEK_PROVIDERS = frozenset({'deepseek'})


@runtime_checkable
class TokenEncoding(Protocol):
    """Minimal interface shared by all tokenizer back-ends."""

    @property
    def name(self) -> str: ...

    def encode(self, text: str) -> list[int]: ...


class TiktokenEncodingAdapter:
    """Wrap a ``tiktoken.Encoding`` behind the ``TokenEncoding`` protocol."""

    def __init__(self, encoding: tiktoken.Encoding) -> None:
        self._encoding = encoding

    @property
    def name(self) -> str:
        return self._encoding.name

    def encode(self, text: str) -> list[int]:
        return self._encoding.encode(text)


class DeepSeekEncodingAdapter:
    """Wrap ``deepseek_tokenizer`` behind the ``TokenEncoding`` protocol."""

    name: str = 'deepseek'

    def __init__(self) -> None:
        self._tokenizer = ds_token

    def encode(self, text: str) -> list[int]:
        return self._tokenizer.encode(text)


def _tiktoken_default() -> TiktokenEncodingAdapter:
    return TiktokenEncodingAdapter(tiktoken.get_encoding(DEFAULT_ENCODING))


def count_tokens(text: str, model_string: str) -> int:
    """Count tokens for the given text using the encoding appropriate for *model_string*.

    Delegates to :func:`get_encoding_for_model` so the correct tokenizer is used
    per provider (tiktoken for OpenAI/Azure, deepseek-tokenizer for DeepSeek, etc.).
    Returns 0 on any failure so that callers can safely fall back to a default model.
    """
    try:
        encoding = get_encoding_for_model(model_string)
        return len(encoding.encode(text))
    except Exception as e:
        logger.warning(
            'Token counting failed for model %s, returning 0: %s', model_string, e
        )
        return 0


@lru_cache(maxsize=64)
def get_encoding_for_model(model_string: str) -> TokenEncoding:
    """Return the appropriate token encoding for the given model string.

    For OpenAI/Azure models, attempts to resolve the model-specific encoding
    via ``tiktoken.encoding_for_model``.  For DeepSeek models the native
    ``deepseek-tokenizer`` is used.  For all other providers (Anthropic,
    Google Gemini, Ollama, etc.) the default ``cl100k_base`` encoding is
    returned as a reasonable approximation.
    """
    try:
        provider, model_name = parse_provider_and_model(model_string)
    except ModelInvokerBadRequest:
        return _tiktoken_default()

    if provider in OPENAI_PROVIDERS:
        try:
            return TiktokenEncodingAdapter(tiktoken.encoding_for_model(model_name))
        except KeyError:
            logger.debug(
                'tiktoken has no specific encoding for model %s, falling back to %s',
                model_name,
                DEFAULT_ENCODING,
            )
            return _tiktoken_default()

    if provider in DEEPSEEK_PROVIDERS:
        return DeepSeekEncodingAdapter()

    return _tiktoken_default()
