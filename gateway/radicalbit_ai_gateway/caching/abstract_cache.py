from abc import ABC, abstractmethod
import hashlib


class AbstractCache(ABC):
    @staticmethod
    def generate_cache_key(
        route_name: str, request_signature: str, key_uuid: str
    ) -> str:
        request_signature_hash = hashlib.sha256(
            request_signature.encode('utf-8')
        ).hexdigest()
        return (
            f'response:aigateway:cache:{route_name}:{key_uuid}:{request_signature_hash}'
        )

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
