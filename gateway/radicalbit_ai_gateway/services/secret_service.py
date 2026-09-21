from collections.abc import Callable

from radicalbit_ai_gateway.models.secret_dto import SecretOut
from radicalbit_ai_gateway.utils.secrets import SecretProvider, get_secret_provider


class SecretService:
    """Reads the secrets backend. Keys only, never values."""

    def __init__(
        self,
        secret_provider_factory: Callable[[], SecretProvider] = get_secret_provider,
    ):
        self._secret_provider_factory = secret_provider_factory

    def get_secrets(self) -> list[SecretOut]:
        """Return a row per secret key the backend holds, sorted by key.

        The provider is built on every call, so the result reflects the
        backend at read time rather than a snapshot.
        """
        provider = self._secret_provider_factory()
        return [SecretOut(key=key) for key in sorted(provider.list_secret_keys())]
