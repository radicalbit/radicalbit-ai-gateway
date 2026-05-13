from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.metrics import Observation
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
import psutil

psutil.cpu_percent(percpu=True)

resource = Resource.create(attributes={'service.name': 'gateway.app.service'})

reader = PrometheusMetricReader()

provider = MeterProvider(resource=resource, metric_readers=[reader])
metrics.set_meter_provider(provider)
meter = metrics.get_meter('gateway_meter')


def get_cpu_usage_callback(options):
    for i, percentage in enumerate(psutil.cpu_percent(percpu=True)):
        yield Observation(value=percentage, attributes={'cpu.core': str(i)})


def get_ram_usage_callback(options):
    ram_percent = psutil.virtual_memory().percent
    yield Observation(value=ram_percent, attributes={})


meter.create_observable_gauge(
    name='system.cpu.utilization',
    description='Current CPU utilization.',
    callbacks=[get_cpu_usage_callback],
    unit='%',
)

meter.create_observable_gauge(
    name='system.memory.utilization',
    description='Current RAM utilization.',
    callbacks=[get_ram_usage_callback],
    unit='%',
)

total_requests_counter = meter.create_counter(
    name='gateway.requests.total',
    description='The total number of requests processed by the gateway.',
    unit='1',
)

request_latency_histogram = meter.create_histogram(
    name='gateway.request.duration',
    description='The distribution of request latency.',
    unit='ms',
)

model_invocations_counter = meter.create_counter(
    name='gateway.model.invocations',
    description='The number of times a model was invoked.',
    unit='1',
)

guardrails_triggered_counter = meter.create_counter(
    name='gateway.guardrails.triggered',
    description='The number of times a guardrail was triggered.',
    unit='1',
)

fallbacks_triggered_counter = meter.create_counter(
    name='gateway.fallbacks.triggered',
    description='The number of times a fallback mechanism was triggered.',
    unit='1',
)

total_tokens_counter_output = meter.create_counter(
    name='gateway.tokens.total.output',
    description='The total number of tokens processed in output.',
    unit='tokens',
)

total_tokens_counter_input = meter.create_counter(
    name='gateway.tokens.total.input',
    description='The total number of tokens processed in input.',
    unit='tokens',
)

tokens_per_request_histogram_input = meter.create_histogram(
    name='gateway.tokens.per_request.input',
    description='The distribution of tokens in each request in input.',
    unit='tokens',
)

tokens_per_request_histogram_output = meter.create_histogram(
    name='gateway.tokens.per_request.output',
    description='The distribution of tokens in each request in output.',
    unit='tokens',
)

cache_hit_counter = meter.create_counter(
    name='gateway.cache.hit',
    description='The total number of cache hit.',
    unit='1',
)

rate_limiting_counter = meter.create_counter(
    name='gateway.rate_limiting',
    description='The total number of rate limiting triggers.',
    unit='1',
)

token_input_limiting_counter = meter.create_counter(
    name='gateway.token_input_limiting',
    description='The total number of token input limiting triggers.',
    unit='1',
)

token_output_limiting_counter = meter.create_counter(
    name='gateway.token_output_limiting',
    description='The total number of token output limiting triggers.',
    unit='1',
)

invocations_latency_histogram = meter.create_histogram(
    name='gateway.invocation.duration',
    description='The distribution of invocation latency.',
    unit='ms',
)

cache_input_tokens = meter.create_counter(
    name='gateway.cache.input.saved.tokens',
    description='The total number of cache tokens saved.',
    unit='1',
)

cache_output_tokens = meter.create_counter(
    name='gateway.cache.output.saved.tokens',
    description='The total number of cache tokens saved.',
    unit='1',
)

semantic_cache_similarity = meter.create_histogram(
    name='gateway.cache.semantic.similarity',
    description='The similarity score of semantic cache lookups.',
    unit='1',
    explicit_bucket_boundaries_advisory=[
        0.0,
        0.5,
        0.6,
        0.7,
        0.75,
        0.8,
        0.85,
        0.9,
        0.95,
        0.98,
        1.0,
    ],
)
