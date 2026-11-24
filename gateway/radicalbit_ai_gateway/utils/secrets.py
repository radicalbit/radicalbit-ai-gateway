from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from typing_extensions import override
import yaml

from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    SecretNotFoundError,
    SecretsBackendError,
)


class SecretProvider(ABC):
    @abstractmethod
    def get_secret(self, key: str) -> object:
        """Resolve a secret by key. Raises SecretNotFoundError if unavailable.

        The value is the one the config gets in place of its ``!secret``
        reference: a string, or whatever value the backend holds (a secrets
        file holds YAML values, such as a port as a number).
        """
        ...

    @abstractmethod
    def list_secret_keys(self) -> list[str]:
        """Return the secret keys the backend holds.

        Keys only. A secret value is never returned by this method.
        """
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
        self._secrets: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        if self._secrets is None:
            try:
                with open(self._secrets_path) as f:
                    self._secrets = yaml.safe_load(f) or {}
            except (OSError, yaml.YAMLError) as e:
                raise SecretsBackendError(
                    f'Could not read the secrets file {self._secrets_path}: {e}'
                ) from e
        return self._secrets

    @override
    def get_secret(self, key: str) -> object:
        secrets = self._load()
        value = secrets.get(key)
        if value is None:
            raise SecretNotFoundError(key, str(self._secrets_path))
        return value

    @override
    def list_secret_keys(self) -> list[str]:
        return list(self._load().keys())


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
) -> dict[str, Any]:
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
