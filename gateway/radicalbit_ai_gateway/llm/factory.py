"""Build chat and embedding models from a ``provider:model`` identifier."""

from collections.abc import Callable
from typing import Any

from radicalbit_ai_gateway.llm.chat_model import ChatModel
from radicalbit_ai_gateway.llm.embeddings import Embeddings
from radicalbit_ai_gateway.llm.providers import (
    anthropic,
    deepseek,
    google_genai,
    mistralai,
    openai,
)

# provider -> builder. A builder takes the model name and the configured kwargs
# (credentials, params, http_async_client) and returns the model.
CHAT_PROVIDERS: dict[str, Callable[..., ChatModel]] = {
    'openai': openai.build_chat_model,
    'azure_openai': openai.build_azure_chat_model,
    # The documented chat prefix: endpoint from ``api_base``/``base_url``.
    'azure': openai.build_azure_deployment_chat_model,
    'deepseek': deepseek.build_chat_model,
    'anthropic': anthropic.build_chat_model,
    'google_genai': google_genai.build_chat_model,
    'mistralai': mistralai.build_chat_model,
}
EMBEDDING_PROVIDERS: dict[str, Callable[..., Embeddings]] = {
    'openai': openai.build_embeddings,
    'azure_openai': openai.build_azure_embeddings,
    'google_genai': google_genai.build_embeddings,
    'mistralai': mistralai.build_embeddings,
}


def normalize_provider(provider: str) -> str:
    """Map a gateway provider name (``google-genai``) to its registry key."""
    return provider.replace('-', '_').lower()


def _builder(registry: dict[str, Callable], provider: str, kind: str) -> Callable:
    try:
        return registry[provider]
    except KeyError:
        supported = ', '.join(sorted(registry))
        raise ValueError(
            f'Unsupported {kind} model provider {provider!r}. '
            f'Supported providers: {supported}'
        ) from None


def init_chat_model(model: str, **kwargs: Any) -> ChatModel:
    """Build the chat model for ``model`` (``'provider:model_name'``)."""
    provider, _, model_name = model.partition(':')
    builder = _builder(CHAT_PROVIDERS, normalize_provider(provider), 'chat')
    return builder(model_name, **kwargs)


def init_embeddings(model: str, *, provider: str, **kwargs: Any) -> Embeddings:
    """Build the embedding model ``model`` of ``provider``."""
    builder = _builder(EMBEDDING_PROVIDERS, normalize_provider(provider), 'embedding')
    return builder(model, **kwargs)
