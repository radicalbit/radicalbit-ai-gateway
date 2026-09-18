from radicalbit_ai_gateway.models.secret_dto import SecretOut
from radicalbit_ai_gateway.services.secret_service import SecretService
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


def _service(secrets: dict[str, str]) -> SecretService:
    return SecretService(secret_provider_factory=lambda: FakeSecretProvider(secrets))


def test_get_secrets_returns_a_row_per_backend_key():
    service = _service({'OPENAI_API_KEY': 'sk-dummy-key'})
    assert service.get_secrets() == [SecretOut(key='OPENAI_API_KEY')]


def test_get_secrets_returns_no_values():
    service = _service({'OPENAI_API_KEY': 'sk-dummy-key'})
    rows = service.get_secrets()
    assert 'sk-dummy-key' not in rows[0].model_dump().values()


def test_get_secrets_empty_backend():
    assert _service({}).get_secrets() == []


def test_get_secrets_sorts_by_key():
    service = _service({'ZETA': 'z', 'ALPHA': 'a', 'MIKE': 'm'})
    assert [row.key for row in service.get_secrets()] == ['ALPHA', 'MIKE', 'ZETA']


def test_get_secrets_reads_the_backend_on_every_call():
    # The page must never show a stale snapshot, so the provider is built per
    # call. A backend that gained a key between calls shows it on the second.
    secrets = {'ALPHA': 'a'}
    service = SecretService(
        secret_provider_factory=lambda: FakeSecretProvider(dict(secrets))
    )
    assert [row.key for row in service.get_secrets()] == ['ALPHA']
    secrets['BRAVO'] = 'b'
    assert [row.key for row in service.get_secrets()] == ['ALPHA', 'BRAVO']
