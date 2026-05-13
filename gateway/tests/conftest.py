import logging
import logging.config
import os

from celery import Celery
import fakeredis
import pytest

from radicalbit_ai_gateway.events import buffer
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.secrets import (
    FileSecretProvider,
    resolve_secrets_from_string,
)

_SECRETS_YAML = """\
OPENAI_API_KEY: sk-dummy-key
CACHE_REDIS_HOST: "localhost"
CACHE_REDIS_PORT: 6379
"""

_SAMPLE_CONFIG_YAML = """\
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


def test_data_dir():
    return os.path.join(os.path.dirname(__file__), 'resources')


@pytest.fixture(scope='session')
def test_data_dir_fixture():
    return test_data_dir()


@pytest.fixture(scope='session')
def secrets_path(tmp_path_factory):
    p = tmp_path_factory.mktemp('secrets') / 'secrets.yaml'
    p.write_text(_SECRETS_YAML)
    app_config = get_app_config()
    app_config.gateway_secrets_path = p
    return str(p)


@pytest.fixture(scope='session')
def resolved_config_dict(secrets_path):
    provider = FileSecretProvider(secrets_path)
    return resolve_secrets_from_string(_SAMPLE_CONFIG_YAML, provider=provider)


app_config = get_app_config()

logging_config_dict = app_config.log_config.model_dump()
logging.config.dictConfig(logging_config_dict)
logger = logging.getLogger(app_config.log_config.logger_name)


@pytest.fixture(autouse=True)
def _ensure_logging_is_enabled_after_test():
    yield
    logging.disable(logging.NOTSET)


@pytest.fixture
def fake_redis_client(request):
    return fakeredis.FakeAsyncRedis()


@pytest.fixture(scope='session', autouse=True)
def configure_celery_with_test_redis(redis_connection_url):
    # Recreate celery_app with test Redis URL
    buffer.celery_app = Celery('events_app', broker=redis_connection_url)
    buffer.celery_app.conf.update(
        task_send_sent_event=False,
        broker_pool_limit=buffer.app_config.celery_config.celery_broker_pool_limit,
        task_ignore_result=True,
    )


pytest_plugins = 'tests.fixtures.conftest_redis'
