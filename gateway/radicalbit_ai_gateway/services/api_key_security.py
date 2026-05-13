import secrets
import string

from radicalbit_ai_gateway.models.api_key_dto import ApiKeySec
from radicalbit_ai_gateway.services.commons.keyed_hash_algorithm import hash_key


class ApiKeySecurity:
    def __init__(self):
        pass

    @staticmethod
    def _create_secret() -> str:
        return 'sk-rb-' + ''.join(
            secrets.choice(string.ascii_letters + string.digits) for _ in range(48)
        )

    def generate_key(self) -> ApiKeySec:
        key = self._create_secret()
        hashed_key = hash_key(key)
        return ApiKeySec(plain_key=key, hashed_key=hashed_key)
