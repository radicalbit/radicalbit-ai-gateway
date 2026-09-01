from abc import ABC, abstractmethod
import hashlib


class AbstractCache(ABC):
    @staticmethod
    def generate_cache_key(
        project_uuid: str, route_name: str, request_signature: str, key_uuid: str
    ) -> str:
        """Build the storage key for a cached response.

        ``project_uuid`` scopes the key. Route names are unique only within a
        project and an API key can be moved between groups bound to different
        projects, so omitting it lets one project read another's cached
        completions.
        """
        request_signature_hash = hashlib.sha256(
            request_signature.encode('utf-8')
        ).hexdigest()
        return f'response:aigateway:cache:{project_uuid}:{route_name}:{key_uuid}:{request_signature_hash}'

    @abstractmethod
    async def get(self, cache_key: str, **kwargs) -> str | None:
        pass

    @abstractmethod
    async def set(
        self,
        cache_key: str,
        response: str,
        ttl: int | None,
        **kwargs,
    ):
        pass
