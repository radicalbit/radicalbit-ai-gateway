"""Build chat and embedding models: from a configured ``Model``, or from a
``provider:model`` identifier.
"""

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
from radicalbit_ai_gateway.models.model import (
    ENABLE_PROMPT_CACHE_PARAM,
    MockGatewayChatModel,
    MockGatewayEmbeddings,
    Model,
)
from radicalbit_ai_gateway.utils.parse_provider_and_model import (
    parse_provider_and_model,
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
# Gateway params that are not the provider's.
_GATEWAY_PARAMS = frozenset({ENABLE_PROMPT_CACHE_PARAM})
# Providers whose models open their own HTTP client.
_OWN_HTTP_CLIENT = ('anthropic', 'mistralai')


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


def build_chat_model(
    model: Model,
    http_client: Any = None,
    *,
    params: dict | None = None,
    mock: bool = True,
) -> ChatModel:
    """Build the chat model of a configured ``model``.

    ``params`` replace the model's configured params (a judge sets its own).
    With ``mock`` false a ``mock/`` model is an unsupported provider, as it
    has always been for judges.
    """
    provider, model_name = parse_provider_and_model(model.model)
    if params is None:
        params = model.params or {}
    if provider == 'mock' and mock:
        return MockGatewayChatModel(
            model_name=model_name,
            latency_ms=int(params.get('latency_ms', 0)),
            response_text=params.get('response_text', 'ok'),
        )
    kwargs = {
        k: v
        for k, v in {**params, **_credentials(model)}.items()
        if k not in _GATEWAY_PARAMS
    }
    if provider not in _OWN_HTTP_CLIENT:
        kwargs['http_async_client'] = http_client
    # Registry keys use underscores (google_genai), the config hyphens.
    return init_chat_model(model=f'{_underscored(provider)}:{model_name}', **kwargs)


def build_embeddings(model: Model, http_client: Any = None) -> Embeddings:
    """Build the embedding model of a configured ``model``."""
    provider, model_name = parse_provider_and_model(model.model)
    params = model.params or {}
    if provider == 'mock':
        return MockGatewayEmbeddings(
            latency_ms=int(params.get('latency_ms', 0)),
            vector_size=int(params.get('vector_size', 5)),
        )
    # Every provider accepts api_key directly as an alias for its own key.
    return init_embeddings(
        model=model_name,
        provider=_underscored(provider),
        http_async_client=http_client,
        **{**params, **_credentials(model)},
    )


def _underscored(provider: str) -> str:
    return provider.replace('-', '_')


def _credentials(model: Model) -> dict:
    return model.credentials.model_dump(exclude_none=True) if model.credentials else {}
