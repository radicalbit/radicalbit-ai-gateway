import pytest

from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.utils.exceptions import (
    SecretNotFoundError,
    SecretsBackendError,
)
from radicalbit_ai_gateway.utils.secrets import (
    FileSecretProvider,
    SecretProvider,
    get_secret_provider,
    resolve_secrets_from_string,
)


def _provider(tmp_path, content: str) -> FileSecretProvider:
    secrets_file = tmp_path / 'secrets.yaml'
    secrets_file.write_text(content)
    return FileSecretProvider(secrets_file)


# --- resolve_secrets_from_string ---


def test_secrets_are_resolved(resolved_config_dict):
    assert resolved_config_dict == {
        'chat_models': [
            {
                'model_id': 'openai',
                'model': 'openai/gpt-4o',
                'credentials': {'api_key': 'sk-dummy-key'},
            }
        ],
        'routes': {'rb-gateway': {'chat_models': ['openai']}},
        'cache': {'redis_host': 'localhost', 'redis_port': 6379},
    }
    config = GatewayConfig.model_validate(resolved_config_dict)
    assert list(config.routes) == ['rb-gateway']


def test_resolve_secrets_from_string_no_secrets():
    yaml_no_secrets = """\
chat_models:
  - model_id: mock-chat
    model: mock/gateway
routes:
  test-route:
    chat_models:
      - mock-chat
"""
    assert resolve_secrets_from_string(yaml_no_secrets) == {
        'chat_models': [{'model_id': 'mock-chat', 'model': 'mock/gateway'}],
        'routes': {'test-route': {'chat_models': ['mock-chat']}},
    }


def test_mcp_server_nested_secrets_are_resolved(secrets_path):
    config_yaml = """
mcp_servers:
  - alias: github
    transport: streamable_http
    url: https://api.example.com/mcp/
    headers:
      Authorization: !secret OPENAI_API_KEY
  - alias: local
    transport: stdio
    command: python
    env:
      API_TOKEN: !secret OPENAI_API_KEY
"""
    provider = FileSecretProvider(secrets_path)

    assert resolve_secrets_from_string(config_yaml, provider=provider) == {
        'mcp_servers': [
            {
                'alias': 'github',
                'transport': 'streamable_http',
                'url': 'https://api.example.com/mcp/',
                'headers': {'Authorization': 'sk-dummy-key'},
            },
            {
                'alias': 'local',
                'transport': 'stdio',
                'command': 'python',
                'env': {'API_TOKEN': 'sk-dummy-key'},
            },
        ]
    }


@pytest.mark.parametrize(
    ('config_yaml', 'key'),
    [
        ('cache:\n  redis_host: !secret MISSING_SECRET\n', 'MISSING_SECRET'),
        ('chat_models:\n  - api_key: !secret NONEXISTENT_KEY\n', 'NONEXISTENT_KEY'),
    ],
)
def test_missing_secret_raises_error(secrets_path, config_yaml, key):
    provider = FileSecretProvider(secrets_path)

    with pytest.raises(SecretNotFoundError, match=f"Secret '{key}' not found"):
        resolve_secrets_from_string(config_yaml, provider=provider)


# --- FileSecretProvider ---


def test_file_secret_provider_loads_the_file_once(secrets_path):
    provider = FileSecretProvider(secrets_path)
    assert provider._secrets is None

    assert provider.get_secret('OPENAI_API_KEY') == 'sk-dummy-key'
    cached = provider._secrets
    assert cached is not None
    assert provider.get_secret('CACHE_REDIS_HOST') == 'localhost'
    assert provider._secrets is cached

    names = provider.list_secret_keys()
    assert sorted(names) == ['CACHE_REDIS_HOST', 'CACHE_REDIS_PORT', 'OPENAI_API_KEY']
    assert {str(provider.get_secret(name)) for name in names}.isdisjoint(names)


def test_file_secret_provider_lists_no_keys_for_an_empty_file(tmp_path):
    assert _provider(tmp_path, '').list_secret_keys() == []


@pytest.mark.parametrize(
    ('content', 'key'),
    [('OPENAI_API_KEY: sk-dummy-key\n', 'NONEXISTENT'), ('', 'ANY_KEY')],
)
def test_file_secret_provider_missing_key(tmp_path, content, key):
    provider = _provider(tmp_path, content)

    with pytest.raises(SecretNotFoundError, match=f"Secret '{key}' not found") as exc:
        provider.get_secret(key)
    assert exc.value.key == key


@pytest.mark.parametrize('absent', [True, False], ids=['missing', 'invalid'])
def test_an_unreadable_file_is_a_backend_error(tmp_path, absent):
    provider = (
        FileSecretProvider(tmp_path / 'absent.yaml')
        if absent
        else _provider(tmp_path, 'KEY: [unclosed\n')
    )

    with pytest.raises(SecretsBackendError, match='Could not read the secrets file'):
        provider.list_secret_keys()


@pytest.mark.parametrize(
    ('content', 'key', 'error'),
    [
        ('OPENAI_API_KEY: sk-dummy-key\n', 'OPENAI_API_KEY', None),
        ('OPENAI_API_KEY: sk-dummy-key\n', 'NONEXISTENT', 'not found'),
        ('EMPTY_SECRET: ""\n', 'EMPTY_SECRET', 'has an empty value'),
        ('BLANK_SECRET: "   "\n', 'BLANK_SECRET', 'has an empty value'),
    ],
)
def test_validate_secret(tmp_path, content, key, error):
    assert _provider(tmp_path, content).validate_secret(key) == error


def test_get_secret_provider_returns_file_provider(secrets_path):
    provider = get_secret_provider(secrets_path)

    assert isinstance(provider, FileSecretProvider)
    assert provider.get_secret('OPENAI_API_KEY') == 'sk-dummy-key'


def test_secret_provider_must_implement_list_secret_keys():
    class IncompleteProvider(SecretProvider):
        def get_secret(self, key: str) -> str:
            return 'value'

    with pytest.raises(TypeError, match='list_secret_keys'):
        IncompleteProvider()
