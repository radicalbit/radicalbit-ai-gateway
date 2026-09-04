import hashlib
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

    def generate_mcp_list_cache_key(
        self,
        project_uuid: str,
        route_name: str,
        key_uuid: str,
        method: str,
        servers_signature: str,
    ) -> str:
        """Key a cached MCP list method (``tools/list`` and its siblings)."""
        request_signature = self._build_mcp_list_request_signature(
            method=method, servers_signature=servers_signature
        )
        return self.cache_client.generate_cache_key(
            project_uuid, route_name, request_signature, key_uuid
        )

    @staticmethod
    def _build_mcp_list_request_signature(
        method: str,
        servers_signature: str,
    ) -> str:
        return f'mcp_method:{method};mcp_servers:{servers_signature}'

    def generate_transcription_cache_key(
        self,
        project_uuid: str,
        route_name: str,
        key_uuid: str,
        audio_bytes: bytes,
        **kwargs,
    ) -> str:
        request_signature = self._build_transcription_request_signature(
            audio_bytes=audio_bytes,
            **kwargs,
        )
        return self.cache_client.generate_cache_key(
            project_uuid, route_name, request_signature, key_uuid
        )

    @staticmethod
    def _build_transcription_request_signature(
        audio_bytes: bytes,
        **kwargs,
    ) -> str:
        # The audio itself is hashed separately (never embedded raw) — it's
        # binary, not text, and would otherwise dominate the signature size.
        audio_hash = hashlib.sha256(audio_bytes).hexdigest()
        return f'audio_hash:{audio_hash};extra_args:{json.dumps(kwargs)}'
