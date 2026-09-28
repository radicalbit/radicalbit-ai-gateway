from radicalbit_ai_gateway.utils.exceptions import SecretNotFoundError
from radicalbit_ai_gateway.utils.secrets import SecretProvider


class FakeSecretProvider(SecretProvider):
    """A secrets backend holding the given key/value mapping."""

    def __init__(self, secrets: dict[str, str]):
        self._secrets = secrets

    def get_secret(self, key: str) -> str:
        value = self._secrets.get(key)
        if value is None:
            raise SecretNotFoundError(key, 'fake')
        return value

    def list_secret_keys(self) -> list[str]:
        return list(self._secrets.keys())
