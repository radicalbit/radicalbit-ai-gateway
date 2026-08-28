import json

from langchain_core.messages import BaseMessage
from openai.types.chat import (
    ChatCompletionToolChoiceOptionParam,
    ChatCompletionToolParam,
)

from radicalbit_ai_gateway.caching.abstract_cache import AbstractCache
from radicalbit_ai_gateway.caching.in_memory_cache import CacheToolsInMemory
from radicalbit_ai_gateway.caching.redis_cache import RedisCache
from radicalbit_ai_gateway.caching.semantic_caching import SemanticCache
from radicalbit_ai_gateway.models.caching import CacheType


class GatewayCache:
    def __init__(self, cache_client: AbstractCache):
        self.cache_client = cache_client

    @property
    def cache_type(self) -> CacheType:
        if isinstance(self.cache_client, SemanticCache):
            return CacheType.SEMANTIC
        if isinstance(self.cache_client, RedisCache):
            return CacheType.EXACT
        if isinstance(self.cache_client, CacheToolsInMemory):
            return CacheType.IN_MEMORY
        return CacheType.UNKNOWN

    async def get(self, cache_key: str, **kwargs) -> str | None:
        return await self.cache_client.get(cache_key, **kwargs)

    async def set(
        self,
        cache_key: str,
        response: str,
        ttl: int | None,
        **kwargs,
    ):
        await self.cache_client.set(cache_key, response, ttl, **kwargs)

    def generate_cache_key(
        self,
        project_uuid: str,
        route_name: str,
        key_uuid: str,
        messages: list[BaseMessage],
        tools: list[ChatCompletionToolParam] | None,
        tool_choice: ChatCompletionToolChoiceOptionParam | None,
        **kwargs,
    ) -> str:
        request_signature = self._build_request_signature(
            messages, tools, tool_choice, **kwargs
        )
        return self.cache_client.generate_cache_key(
            project_uuid, route_name, request_signature, key_uuid
        )

    @staticmethod
    def _build_request_signature(
        messages: list[BaseMessage],
        tools: list[ChatCompletionToolParam] | None,
        tool_choice: ChatCompletionToolChoiceOptionParam | None,
        **kwargs,
    ) -> str:
        return f'messages:{[message.model_dump_json(indent=None) for message in messages]};tools:{json.dumps(tools)};tool_choice:{json.dumps(tool_choice)};extra_args:{json.dumps(kwargs)}'

    def generate_embedding_cache_key(
        self,
        project_uuid: str,
        route_name: str,
        key_uuid: str,
        input_texts: list[str],
        **kwargs,
    ) -> str:
        request_signature = self._build_embedding_request_signature(
            input_texts=input_texts,
            **kwargs,
        )
        return self.cache_client.generate_cache_key(
            project_uuid, route_name, request_signature, key_uuid
        )

    @staticmethod
    def _build_embedding_request_signature(
        input_texts: list[str],
        **kwargs,
    ) -> str:
        return f'inputs:{json.dumps(input_texts, ensure_ascii=False)};extra_args:{json.dumps(kwargs)}'
