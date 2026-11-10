import logging
import logging.config
import os

from celery import Celery
import fakeredis
from opentelemetry import context as otel_context, trace
from opentelemetry.sdk.trace import SpanProcessor
import pytest
import tldextract
from tldextract import tldextract as tldextract_module
from traceloop.sdk import Traceloop
from traceloop.sdk.tracing.tracing import TracerWrapper

import tests.common.pook_httpx2  # noqa: F401

from radicalbit_ai_gateway.events import buffer
from radicalbit_ai_gateway.events.alerts_processor import _alerts_buffer
from radicalbit_ai_gateway.events.events_processor import _events_buffer
from radicalbit_ai_gateway.events.request_events_processor import _request_events_buffer
from radicalbit_ai_gateway.limiter.storage import shared as limit_storage
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.secrets import (
    FileSecretProvider,
    resolve_secrets_from_string,
)

# Presidio's email recognizer reads domains with tldextract, whose default
# extractor downloads the public suffix list on first use. Use the snapshot
# the package ships, so no test depends on the network or on a warm cache.
tldextract_module.TLD_EXTRACTOR = tldextract.TLDExtract(suffix_list_urls=())

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
def _fresh_limit_storage(monkeypatch):
    """Give each test its own limit counters: the storage is process-wide."""
    monkeypatch.setattr(limit_storage, '_storage', None)


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
    yield
    # The buffers flush at exit, after the Redis container is gone: flush them
    # while it is up, then release Celery's broker connections.
    for flushed in (_events_buffer, _request_events_buffer, _alerts_buffer):
        flushed.close()
    buffer.celery_app.close()


class SpanCollector(SpanProcessor):
    """Keeps the spans that end while it is on."""

    def __init__(self):
        self.on = False
        self.spans: list = []

    def on_end(self, span) -> None:
        if self.on:
            self.spans.append(span)


@pytest.fixture(scope='module')
def span_collector():
    """Collect the gateway's trace spans while the collector is on."""
    collector = SpanCollector()
    initialized = hasattr(TracerWrapper, 'instance')
    if initialized:
        trace.get_tracer_provider().add_span_processor(collector)
    else:
        Traceloop.init(
            app_name='test-gateway',
            telemetry_enabled=False,
            disable_batch=True,
            processor=collector,
            instruments=set(),
        )
    TracerWrapper.set_disabled(False)
    yield collector
    # Traceloop's provider cannot be uninstalled: switch the decorators off
    # again, as the rest of the suite runs them, and let a later
    # Traceloop.init add its own processor.
    TracerWrapper.set_disabled(True)
    if not initialized:
        del TracerWrapper.instance


@pytest.fixture(autouse=True)
def _restore_otel_context():
    """Give each test the OpenTelemetry context it started with.

    The gateway attaches trace attributes to the current context without
    detaching them: each request runs in a context of its own. A synchronous
    test runs on the main thread, so what it attaches would reach the spans
    of every later test.
    """
    token = otel_context.attach(otel_context.get_current())
    yield
    otel_context.detach(token)


pytest_plugins = 'tests.fixtures.conftest_redis'
