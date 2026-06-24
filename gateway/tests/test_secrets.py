import tempfile

import pytest

from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.utils.exceptions import SecretNotFoundError
from radicalbit_ai_gateway.utils.secrets import (
    FileSecretProvider,
    get_secret_provider,
    resolve_secrets_from_string,
)


def test_secrets_are_resolved(resolved_config_dict):
    chat_models = resolved_config_dict['chat_models']
    openai_model = next(m for m in chat_models if m['model_id'] == 'openai')
    assert openai_model['credentials']['api_key'] == 'sk-dummy-key'


def test_config_is_valid(resolved_config_dict):
    config = GatewayConfig.model_validate(resolved_config_dict)
    assert config.routes is not None


def test_cache_redis_host_secret(resolved_config_dict):
    assert resolved_config_dict['cache']['redis_host'] == 'localhost'


def test_cache_redis_port_secret(resolved_config_dict):
    assert resolved_config_dict['cache']['redis_port'] == 6379


def test_missing_secret_raises_error(secrets_path):
    config_yaml = """
cache:
  redis_host: !secret MISSING_SECRET
"""
    provider = FileSecretProvider(secrets_path)
    with pytest.raises(SecretNotFoundError, match="Secret 'MISSING_SECRET' not found"):
        resolve_secrets_from_string(config_yaml, provider=provider)


def test_wrong_secret_value(resolved_config_dict):
    assert resolved_config_dict['cache']['redis_host'] != 'ciccio_pasticcio_host'
    assert resolved_config_dict['cache']['redis_port'] != 666


# --- SecretProvider tests ---


def test_file_secret_provider_get_secret(secrets_path):
    provider = FileSecretProvider(secrets_path)
    assert provider.get_secret('OPENAI_API_KEY') == 'sk-dummy-key'


def test_file_secret_provider_missing_key(secrets_path):
    provider = FileSecretProvider(secrets_path)
    with pytest.raises(
        SecretNotFoundError, match="Secret 'NONEXISTENT' not found"
    ) as exc_info:
        provider.get_secret('NONEXISTENT')
    assert exc_info.value.key == 'NONEXISTENT'


def test_file_secret_provider_caches_load(secrets_path):
    provider = FileSecretProvider(secrets_path)
    assert provider._secrets is None
    provider.get_secret('OPENAI_API_KEY')
    assert provider._secrets is not None
    cached = provider._secrets
    provider.get_secret('CACHE_REDIS_HOST')
    assert provider._secrets is cached


def test_file_secret_provider_empty_yaml():
    with tempfile.NamedTemporaryFile('w+', suffix='.yaml', delete=False) as f:
        f.write('')
        f.flush()
        provider = FileSecretProvider(f.name)
        with pytest.raises(SecretNotFoundError):
            provider.get_secret('ANY_KEY')


def test_get_secret_provider_returns_file_provider(secrets_path):
    provider = get_secret_provider(secrets_path)
    assert isinstance(provider, FileSecretProvider)


_YAML_WITH_CACHE_SECRETS = """\
chat_models:
  - model_id: openai
    model: openai/gpt-4o
    credentials:
      api_key: !secret OPENAI_API_KEY
routes:
  rb-gateway:
    chat_models:
      - openai
cache:
  redis_host: !secret CACHE_REDIS_HOST
  redis_port: !secret CACHE_REDIS_PORT
"""


def test_resolve_secrets_with_explicit_provider(secrets_path):
    provider = FileSecretProvider(secrets_path)
    result = resolve_secrets_from_string(_YAML_WITH_CACHE_SECRETS, provider=provider)
    assert result['cache']['redis_host'] == 'localhost'
    assert result['cache']['redis_port'] == 6379


# --- resolve_secrets_from_string tests ---

_YAML_NO_SECRETS = """\
chat_models:
  - model_id: mock-chat
    model: mock/gateway
routes:
  test-route:
    chat_models:
      - mock-chat
"""

_YAML_WITH_SECRET_REF = """\
chat_models:
  - model_id: openai-chat
    model: openai/gpt-4o
    credentials:
      api_key: !secret OPENAI_API_KEY
routes:
  test-route:
    chat_models:
      - openai-chat
"""


def test_resolve_secrets_from_string_no_secrets():
    result = resolve_secrets_from_string(_YAML_NO_SECRETS)
    assert result['routes'] == {'test-route': {'chat_models': ['mock-chat']}}
    assert result['chat_models'][0]['model_id'] == 'mock-chat'


def test_resolve_secrets_from_string_returns_dict():
    result = resolve_secrets_from_string(_YAML_NO_SECRETS)
    assert isinstance(result, dict)


def test_resolve_secrets_from_string_resolves_secret(secrets_path):
    provider = FileSecretProvider(secrets_path)
    result = resolve_secrets_from_string(_YAML_WITH_SECRET_REF, provider=provider)
    assert result['chat_models'][0]['credentials']['api_key'] == 'sk-dummy-key'


def test_resolve_secrets_from_string_missing_secret_raises(secrets_path):
    provider = FileSecretProvider(secrets_path)
    yaml_with_unknown = _YAML_WITH_SECRET_REF.replace(
        'OPENAI_API_KEY', 'NONEXISTENT_KEY'
    )
    with pytest.raises(Exception, match='NONEXISTENT_KEY'):
        resolve_secrets_from_string(yaml_with_unknown, provider=provider)


# --- validate_secret tests ---


def test_validate_secret_returns_none_for_valid_key(secrets_path):
    provider = FileSecretProvider(secrets_path)
    assert provider.validate_secret('OPENAI_API_KEY') is None


def test_validate_secret_returns_error_for_missing_key(secrets_path):
    provider = FileSecretProvider(secrets_path)
    error = provider.validate_secret('NONEXISTENT')
    assert error is not None
    assert 'not found' in error


def test_validate_secret_returns_error_for_empty_value():
    with tempfile.NamedTemporaryFile('w+', suffix='.yaml', delete=False) as f:
        f.write('EMPTY_SECRET: ""\n')
        f.flush()
        provider = FileSecretProvider(f.name)
        error = provider.validate_secret('EMPTY_SECRET')
        assert error is not None
        assert 'empty' in error


def test_validate_secret_returns_error_for_whitespace_only_value():
    with tempfile.NamedTemporaryFile('w+', suffix='.yaml', delete=False) as f:
        f.write('BLANK_SECRET: "   "\n')
        f.flush()
        provider = FileSecretProvider(f.name)
        error = provider.validate_secret('BLANK_SECRET')
        assert error is not None
        assert 'empty' in error
