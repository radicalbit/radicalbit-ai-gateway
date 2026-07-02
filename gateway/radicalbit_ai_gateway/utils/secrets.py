from abc import ABC, abstractmethod
from pathlib import Path

import yaml

from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import SecretNotFoundError


class SecretProvider(ABC):
    @abstractmethod
    def get_secret(self, key: str) -> str:
        """Resolve a secret by key. Raises SecretNotFoundError if unavailable."""
        ...

    def validate_secret(self, key: str) -> str | None:
        """Check that *key* exists and has a non-empty value.

        Returns ``None`` when valid, or a short error description otherwise.
        The actual secret value is never exposed.
        """
        try:
            value = self.get_secret(key)
        except SecretNotFoundError:
            return 'not found'
        if not str(value).strip():
            return 'has an empty value'
        return None


class FileSecretProvider(SecretProvider):
    def __init__(self, secrets_path: str | Path):
        self._secrets_path = Path(secrets_path)
        self._secrets: dict | None = None

    def _load(self) -> dict:
        if self._secrets is None:
            with open(self._secrets_path) as f:
                self._secrets = yaml.safe_load(f) or {}
        return self._secrets

    def get_secret(self, key: str) -> str:
        secrets = self._load()
        value = secrets.get(key)
        if value is None:
            raise SecretNotFoundError(key, str(self._secrets_path))
        return value


_secret_provider_factory: list[type[SecretProvider] | None] = [None]


def set_secret_provider_factory(factory: type[SecretProvider]):
    """Override the default secret provider.

    Call from a plugin module at import time to register a custom
    ``SecretProvider`` implementation. When set, ``get_secret_provider()``
    will use this factory instead of ``FileSecretProvider``.
    """
    _secret_provider_factory[0] = factory


def get_secret_provider(secrets_path: str | Path | None = None) -> SecretProvider:
    factory = _secret_provider_factory[0]
    if factory is not None:
        return factory()
    if secrets_path is None:
        secrets_path = get_app_config().gateway_secrets_path
    return FileSecretProvider(secrets_path)


def resolve_secrets_from_string(
    yaml_content: str,
    provider: SecretProvider | None = None,
) -> dict:
    if provider is None:
        provider = get_secret_provider()

    def secret_constructor(loader, node):
        key = loader.construct_scalar(node)
        value = provider.get_secret(key)
        if not str(value).strip():
            raise SecretNotFoundError(key, 'value is empty')
        return value

    loader = yaml.SafeLoader(yaml_content)
    loader.add_constructor('!secret', secret_constructor)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()
