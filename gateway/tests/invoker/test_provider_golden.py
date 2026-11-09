"""Golden values of every chat provider's calls: what must not change when the
provider code does.

Each provider is driven through the HTTP app on real routes, with the
provider faked at the transport. For complete and stream calls, with and
without prompt cache reads and writes, the test compares with literals: the
client's body (or its stream chunks), the upstream requests as sent, the
model events with their costs, the model metrics and the model spans. Judges
and LLM routers on each provider, and the schemas each provider sends for
structured output, are pinned the same way.

These pin quirks recorded for the team (ARCHITECTURE-JOURNEY.md, D18-D22) as
they are today:

- D18: Mistral and DeepSeek get ``max_completion_tokens`` as sent; Mistral
  also gets ``stream_options``.
- D19: the Anthropic prompt-cache system block (``cache_control``) also
  reaches a non-Anthropic fallback.
- D20: a Mistral stream reports no cached tokens; a complete call reads them
  from ``prompt_tokens_details``.
- D21: a Gemini stream whose final prompt count is lower reports a negative
  input delta; the invoker keeps the last non-zero input count.
- D22: judges read cached tokens only from ``prompt_tokens_details``; LLM
  routers read none.

``EXPECTED`` lives in ``provider_golden_expected.py``.
"""

import contextlib
from decimal import Decimal
import json
import re
from typing import Any
from unittest.mock import MagicMock, patch

import anthropic
from fastapi.testclient import TestClient
import openai
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import BaseModel, Field
import pytest
from starlette.requests import Request

from tests.common import db_mock, provider_responses as upstream
from tests.common.provider_recorder import CannedResponse, ProviderRecorder
from tests.invoker.provider_golden_expected import EXPECTED, SCHEMAS

from radicalbit_ai_gateway.auth.api_key_validator import ApiKeyValidator
from radicalbit_ai_gateway.events import events_processor
from radicalbit_ai_gateway.guardrails.guardrails import Guardrails
from radicalbit_ai_gateway.guardrails.judges.decision_judge_engine import (
    DecisionJudgeEngine,
)
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.llm import tracing
from radicalbit_ai_gateway.llm.factory import init_chat_model
from radicalbit_ai_gateway.llm.messages import HumanMessage
from radicalbit_ai_gateway.metrics import define_metrics
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.judge_result import JudgeResult
from radicalbit_ai_gateway.models.routing import LLMRoutingConfig
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.routing.llm_router import build_response_schema
from radicalbit_ai_gateway.server import app, group_service, key_service
from radicalbit_ai_gateway.services.config_generator_service import YamlOut
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.dependencies import get_request_uuid
from radicalbit_ai_gateway.utils.gateway_route_factory import (
    build_gateway_routes_from_config,
    initialize_async_routers,
)

MODEL_EVENTS = {
    EventType.MODEL_INVOCATION,
    EventType.FALLBACK,
    EventType.INPUT_TOKEN_PROCESSED,
    EventType.OUTPUT_TOKEN_PROCESSED,
}
METRICS = (
    ('model_invocations_counter', 'add'),
    ('fallbacks_triggered_counter', 'add'),
    ('total_tokens_counter_input', 'add'),
    ('total_tokens_counter_output', 'add'),
)
CREDENTIALS = {'api_key': 'sk-test'}
PROVIDERS = ('gpt', 'claude', 'gemini', 'mistral', 'deepseek')
_UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
_HEX_ID = re.compile(r'\b[0-9a-f]{32}\b')


def _chat(model_id: str, name: str, **extra) -> dict:
    # Distinct prices, so every cost tells which count it was made of.
    return {
        'model_id': model_id,
        'model': name,
        'credentials': CREDENTIALS,
        'input_cost_per_million_tokens': 1,
        'output_cost_per_million_tokens': 2,
        'input_cached_cost_per_million_tokens': '0.5',
        'input_cache_creation_5m_cost_per_million_tokens': 3,
        'input_cache_creation_1h_cost_per_million_tokens': 4,
        **extra,
    }


def _options() -> list[dict]:
    return [
        {'model_id': 'gpt', 'description': 'Questions about geography'},
        {'model_id': 'deepseek', 'description': 'Questions about code'},
    ]


CONFIG = {
    'chat_models': [
        _chat('gpt', 'openai/gpt-x'),
        _chat('claude', 'anthropic/claude-sonnet-4-5'),
        _chat(
            'claude-pc',
            'anthropic/claude-sonnet-4-5',
            prompt='Be terse.',
            params={'enable_prompt_cache': True},
        ),
        _chat('gemini', 'google-genai/gemini-2.5-flash', params={'max_retries': 1}),
        _chat('mistral', 'mistralai/mistral-small-latest'),
        _chat('deepseek', 'deepseek/deepseek-chat'),
    ],
    'guardrails': [
        {
            'name': f'judge-{provider}',
            'type': 'judge',
            'where': 'input',
            'behavior': 'block',
            'parameters': {'model_id': provider, 'prompt': 'Judge this.'},
        }
        for provider in PROVIDERS
    ],
    'routing': [
        {
            'name': f'by-{provider}',
            'type': 'llm',
            'router_model_id': provider,
            'default_model_id': 'gpt',
            'output_mapping': _options(),
        }
        for provider in PROVIDERS
    ],
    'routes': {
        **{provider: {'chat_models': [provider]} for provider in PROVIDERS},
        'cached-fallback': {
            'chat_models': ['claude-pc', 'gpt'],
            'fallback': [{'target': 'claude-pc', 'fallbacks': ['gpt'], 'type': 'chat'}],
        },
        **{
            f'judged-{provider}': {
                'chat_models': ['gpt'],
                'guardrails': [f'judge-{provider}'],
            }
            for provider in PROVIDERS
        },
        **{
            f'routed-{provider}': {
                'chat_models': ['gpt', 'deepseek'],
                'routing': f'by-{provider}',
            }
            for provider in PROVIDERS
        },
    },
}


async def _build_routes() -> dict:
    config = GatewayConfig.model_validate(CONFIG)
    cost_service = CostService(
        chat_models_by_id=config.chat_models_by_id,
        embedding_models_by_id=config.embedding_models_by_id,
        transcription_models_by_id=config.transcription_models_by_id,
        decision_models_by_id=config.decision_models_by_id,
    )
    guardrails = Guardrails(
        presidio_engine=PresidioEngine(),
        judge_engine=JudgeEngine(prompt_manager=MagicMock(spec_set=PromptManager)),
        cost_service=cost_service,
        guardrails=config.guardrails,
        chat_models_by_id=config.chat_models_by_id,
        decision_judge_engine=DecisionJudgeEngine(
            decision_models=config.decision_models, cost_service=cost_service
        ),
    )
    routes = build_gateway_routes_from_config(
        config,
        guardrails,
        redis_client=None,
        cost_service=cost_service,
        httpx_client=None,
        project_uuid='',
    )
    await initialize_async_routers(routes)
    for route in routes.values():
        route.project_name = 'proj'
    return {f'proj/{name}': route for name, route in routes.items()}


def _mock_request_uuid(request: Request):
    request.state.request_uuid = str(db_mock.REQUEST_UUID)
    return str(db_mock.REQUEST_UUID)


def _no_retries() -> list:
    """Return patches that stop the SDKs' own retries (they ask for more replies)."""
    return [
        patch.object(
            openai._base_client.BaseClient, '_should_retry', return_value=False
        ),
        patch.object(
            anthropic._base_client.BaseClient, '_should_retry', return_value=False
        ),
    ]


@pytest.fixture
def spans(monkeypatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing, '_tracer', provider.get_tracer('test'))
    return exporter


@pytest.fixture
async def gateway(spans):
    routes = await _build_routes()
    app.dependency_overrides[get_request_uuid] = _mock_request_uuid
    saved_validator = app.state.token_validator
    saved_routes = getattr(app.state, 'routes', None)
    app.state.token_validator = ApiKeyValidator(key_service=key_service)
    app.state.routes = routes
    api_key = db_mock.get_sample_key_with_group(group_uuid=db_mock.GROUP_UUID)
    events: list = []
    metrics: list = []
    patchers = [
        patch.object(key_service, 'get_key_by_hashed_key', return_value=api_key),
        patch.object(group_service, 'check_key_uuid_for_route', return_value=True),
        patch.object(events_processor._events_buffer, 'add', side_effect=events.append),
        *_no_retries(),
        *(
            patch.object(
                getattr(define_metrics, name),
                method,
                side_effect=lambda value, attributes, name=name: metrics.append(
                    (name, value, dict(attributes))
                ),
            )
            for name, method in METRICS
        ),
    ]
    for patcher in patchers:
        patcher.start()
    try:
        yield _Gateway(TestClient(app), events, metrics, spans)
    finally:
        for patcher in reversed(patchers):
            patcher.stop()
        app.state.token_validator = saved_validator
        if saved_routes is not None:
            app.state.routes = saved_routes
        app.dependency_overrides = {}


def _scrub(value: Any) -> Any:
    """Replace the ids generated per call, so values compare across runs."""
    if isinstance(value, str):
        return _HEX_ID.sub('<hex>', _UUID.sub('<uuid>', value))
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(_scrub(v) for v in value)
    return value


class _Gateway:
    def __init__(self, client: TestClient, events: list, metrics: list, spans):
        self.client = client
        self._events = events
        self.metrics = metrics
        self._spans = spans
        self.headers = {'Authorization': f'Bearer {db_mock.PLAIN_KEY}'}

    def chat(self, replies: list[CannedResponse], route: str, **body):
        payload = {
            'model': f'proj/{route}',
            'messages': [{'role': 'user', 'content': 'Where is Paris?'}],
            **body,
        }
        with ProviderRecorder(replies) as recorder:
            response = self.client.post(
                '/v1/chat/completions', headers=self.headers, json=payload
            )
        assert recorder.unused == 0, 'a canned reply was not asked for'
        self.upstream = recorder.requests
        return response

    def events(self) -> list[tuple]:
        """Return the model events: type, model, target, fallback, value, cost,
        cached, cache type, judge, routing.
        """
        return [
            (
                e['EVENT_TYPE'].name,
                e['MODEL_ID'],
                e['TARGET'],
                e['FALLBACK'],
                e['VALUE'],
                Decimal(str(e['COST'])),
                e['IS_CACHED_TOKENS'],
                e['CACHE_TYPE'],
                e['IS_JUDGE'],
                e['IS_ROUTING'],
            )
            for e in self._events
            if e['EVENT_TYPE'] in MODEL_EVENTS
        ]

    def spans(self) -> list[tuple[str, dict]]:
        """Return each model span's name and attributes, timings left out."""
        return [
            (
                span.name,
                _scrub(
                    {
                        k: v
                        for k, v in sorted(span.attributes.items())
                        if 'time_to_first' not in k and 'duration' not in k
                    }
                ),
            )
            for span in self._spans.get_finished_spans()
            if span.name.endswith('.chat')
        ]


def _client_body(response) -> Any:
    """Return the client's body, or its stream chunks, without generated fields."""
    if response.headers.get('content-type', '').startswith('text/event-stream'):
        chunks = []
        for line in response.text.splitlines():
            if not line.startswith('data: '):
                continue
            data = line.removeprefix('data: ')
            if data == '[DONE]':
                chunks.append(data)
                continue
            chunk = json.loads(data)
            chunks.append({k: v for k, v in chunk.items() if k not in ('created',)})
        return _scrub(chunks)
    try:
        body = response.json()
    except ValueError:
        return response.text
    if isinstance(body, dict):
        body = {k: v for k, v in body.items() if k not in ('created',)}
    return _scrub(body)


def _snapshot(gateway: _Gateway, response) -> dict:
    return {
        'status': response.status_code,
        'body': _client_body(response),
        'upstream': [
            {k: r[k] for k in ('url', 'body')} for r in _scrub(gateway.upstream)
        ],
        'events': gateway.events(),
        'metrics': gateway.metrics,
        'spans': gateway.spans(),
    }


# ── Canned provider replies ──────────────────────────────────────────────────


def _openai_usage(prompt: int, completion: int, cached: int) -> dict:
    return {
        'prompt_tokens': prompt,
        'completion_tokens': completion,
        'total_tokens': prompt + completion,
        'prompt_tokens_details': {'cached_tokens': cached, 'audio_tokens': 0},
        'completion_tokens_details': {'reasoning_tokens': 0, 'audio_tokens': 0},
    }


def _with_usage(reply: CannedResponse, usage: dict) -> CannedResponse:
    """Return ``reply`` with its usage (the last event's, for a stream) replaced."""
    if reply.sse_events is None:
        return CannedResponse(json_body={**reply.json_body, 'usage': usage})
    events = list(reply.sse_events)
    last = max(i for i, e in enumerate(events) if isinstance(e, dict) and 'usage' in e)
    events[last] = {**events[last], 'usage': usage}
    return CannedResponse(sse_events=events)


def _gpt(cached: int = 0, stream: bool = False) -> CannedResponse:
    if stream:
        return upstream.openai_stream(
            ['Paris', ' is in France'],
            model='gpt-x',
            prompt_tokens=21,
            completion_tokens=7,
            cached_tokens=cached,
        )
    return upstream.openai_completion(
        'Paris is in France',
        model='gpt-x',
        prompt_tokens=21,
        completion_tokens=7,
        cached_tokens=cached,
    )


def _claude(stream: bool = False, **cache) -> CannedResponse:
    if not stream:
        return upstream.anthropic_message('Paris is in France', **cache)
    reply = upstream.anthropic_stream(['Paris', ' is in France'], **cache)
    # As the API does, message_delta reports the whole usage, cache included.
    usage = upstream._anthropic_usage(
        21,
        7,
        cache.get('cache_read', 0),
        cache.get('cache_5m', 0),
        cache.get('cache_1h', 0),
    )
    events = [
        {**e, 'usage': usage} if e['type'] == 'message_delta' else e
        for e in reply.sse_events
    ]
    return CannedResponse(sse_events=events, sse_format='anthropic')


def _gemini(cached: int = 0, stream: bool = False) -> CannedResponse:
    if stream:
        return upstream.gemini_stream(['Paris', ' is in France'], cached_tokens=cached)
    return upstream.gemini_response('Paris is in France', cached_tokens=cached)


def _gemini_lower_final_prompt() -> CannedResponse:
    """Return a stream whose last chunk reports fewer prompt tokens than the first."""
    usage = upstream._gemini_usage
    payload = upstream._gemini_payload
    return CannedResponse(
        sse_events=[
            payload([{'text': 'Paris'}], None, usage(21, 1, 0)),
            payload([{'text': ' is in France'}], None, usage(21, 4, 0)),
            payload([{'text': ''}], 'STOP', usage(15, 7, 0)),
        ]
    )


def _mistral(cached: int = 0, stream: bool = False) -> CannedResponse:
    if stream:
        reply = upstream.mistral_stream(['Paris', ' is in France'])
    else:
        reply = upstream.mistral_completion('Paris is in France')
    return _with_usage(reply, _openai_usage(21, 7, cached)) if cached else reply


def _deepseek(cached: int = 0, stream: bool = False) -> CannedResponse:
    reply = _gpt(cached, stream)
    if not cached:
        return reply
    usage = {
        **_openai_usage(21, 7, cached),
        'prompt_cache_hit_tokens': cached,
        'prompt_cache_miss_tokens': 21 - cached,
    }
    return _with_usage(reply, usage)


def _reply(provider: str, stream: bool = False, **cache) -> CannedResponse:
    return {
        'gpt': _gpt,
        'claude': _claude,
        'gemini': _gemini,
        'mistral': _mistral,
        'deepseek': _deepseek,
    }[provider](stream=stream, **cache)


NOT_TRIGGERED = {'triggered': False, 'reasoning': None, 'violation_type': None}
SCORES = {'option_1': 0.9, 'option_2': 0.1}


def _structured(provider: str, name: str, content: dict) -> CannedResponse:
    """Return a structured answer, with 6 cached prompt tokens where it can."""
    text = json.dumps(content)
    if provider == 'gpt':
        return upstream.openai_completion(
            text, prompt_tokens=30, completion_tokens=4, cached_tokens=6
        )
    if provider == 'deepseek':
        # DeepSeek answers structured output with a tool call.
        call = {'id': 'call_1', 'type': 'function'}
        call['function'] = {'name': name, 'arguments': text}
        reply = upstream.openai_completion(
            None, tool_calls=[call], finish_reason='tool_calls'
        )
        return _with_usage(
            reply, {**_openai_usage(30, 4, 6), 'prompt_cache_hit_tokens': 6}
        )
    if provider == 'claude':
        return upstream.anthropic_message(
            None,
            tool_use=[{'id': 'toolu_1', 'name': name, 'input': content}],
            input_tokens=30,
            output_tokens=4,
            cache_read=6,
        )
    if provider == 'gemini':
        return upstream.gemini_response(
            text, prompt_tokens=30, output_tokens=4, cached_tokens=6
        )
    call = {'id': 'abcdefghi', 'type': 'function'}
    call['function'] = {'name': name, 'arguments': text}
    return _with_usage(
        upstream.mistral_completion(None, tool_calls=[call]), _openai_usage(30, 4, 6)
    )


def _tool_call(provider: str) -> CannedResponse:
    if provider == 'claude':
        return upstream.anthropic_message(
            None, tool_use=[upstream.ANTHROPIC_WEATHER_TOOL_USE]
        )
    if provider == 'gemini':
        return upstream.gemini_response(
            None, function_calls=[upstream.GEMINI_WEATHER_CALL]
        )
    if provider == 'mistral':
        return upstream.mistral_completion(
            None, tool_calls=[upstream.MISTRAL_WEATHER_TOOL_CALL]
        )
    return upstream.openai_completion(
        None, tool_calls=[upstream.WEATHER_TOOL_CALL], finish_reason='tool_calls'
    )


WEATHER_TOOL = {
    'type': 'function',
    'function': {
        'name': 'get_weather',
        'description': 'Weather of a city.',
        'parameters': {
            'type': 'object',
            'properties': {
                'city': {'type': 'string', 'title': 'City'},
                'unit': {'$ref': '#/$defs/Unit'},
            },
            'required': ['city'],
            '$defs': {'Unit': {'type': 'string', 'enum': ['c', 'f']}},
        },
    },
}


def _anthropic_error() -> CannedResponse:
    return CannedResponse(
        status=500,
        json_body={'type': 'error', 'error': {'type': 'api_error', 'message': 'boom'}},
    )


# ── Scenarios ────────────────────────────────────────────────────────────────

# provider -> the cache variants it can report.
CACHE_VARIANTS = {
    'gpt': {'no_cache': {}, 'cache_read': {'cached': 6}},
    'claude': {
        'no_cache': {},
        'cache_read': {'cache_read': 6},
        'cache_write_5m': {'cache_5m': 5},
        'cache_write_1h': {'cache_1h': 4},
        'cache_all': {'cache_read': 6, 'cache_5m': 5, 'cache_1h': 4},
    },
    'gemini': {'no_cache': {}, 'cache_read': {'cached': 6}},
    'mistral': {'no_cache': {}, 'cache_read': {'cached': 6}},
    'deepseek': {'no_cache': {}, 'cache_read': {'cached': 6}},
}
STREAM = {'stream': True}
STREAM_USAGE = {'stream': True, 'stream_options': {'include_usage': True}}


def _usage_scenarios() -> dict:
    scenarios = {}
    for provider, variants in CACHE_VARIANTS.items():
        for variant, cache in variants.items():
            for mode, body in (('complete', {}), ('stream', STREAM_USAGE)):
                scenarios[f'{provider}_{mode}_{variant}'] = (
                    lambda g, p=provider, c=cache, b=body: g.chat(
                        [_reply(p, stream=bool(b), **c)], route=p, **b
                    )
                )
    return scenarios


def _request_scenarios() -> dict:
    scenarios = {}
    for provider in PROVIDERS:
        scenarios[f'{provider}_complete_max_completion_tokens'] = lambda g, p=provider: (
            g.chat([_reply(p)], route=p, max_completion_tokens=50, temperature=0.2)
        )
        scenarios[f'{provider}_stream_max_completion_tokens'] = lambda g, p=provider: (
            g.chat(
                [_reply(p, stream=True)], route=p, max_completion_tokens=50, **STREAM
            )
        )
        scenarios[f'{provider}_complete_tools'] = lambda g, p=provider: g.chat(
            [_tool_call(p)], route=p, tools=[WEATHER_TOOL], tool_choice='required'
        )
        scenarios[f'{provider}_complete_tool_choice_auto'] = lambda g, p=provider: (
            g.chat([_tool_call(p)], route=p, tools=[WEATHER_TOOL], tool_choice='auto')
        )
        scenarios[f'{provider}_judge'] = lambda g, p=provider: g.chat(
            [_structured(p, 'JudgeResult', NOT_TRIGGERED), _reply('gpt')],
            route=f'judged-{p}',
        )
        scenarios[f'{provider}_router'] = lambda g, p=provider: g.chat(
            [_structured(p, 'routing_distribution', SCORES), _reply('gpt')],
            route=f'routed-{p}',
        )
    return scenarios


SCENARIOS = {
    **_usage_scenarios(),
    **_request_scenarios(),
    # D21: the last non-zero input count wins.
    'gemini_stream_lower_final_prompt': lambda g: g.chat(
        [_gemini_lower_final_prompt()], route='gemini', **STREAM_USAGE
    ),
    # D19: the cached system block reaches the OpenAI fallback.
    'claude_prompt_cache_then_fallback': lambda g: g.chat(
        [_anthropic_error(), _reply('gpt')], route='cached-fallback'
    ),
    'claude_prompt_cache_then_fallback_stream': lambda g: g.chat(
        [_anthropic_error(), _reply('gpt', stream=True)],
        route='cached-fallback',
        **STREAM,
    ),
    'claude_prompt_cache': lambda g: g.chat(
        [_reply('claude', cache_read=6)], route='cached-fallback'
    ),
    # Without include_usage the client gets no usage chunk.
    'gpt_stream_without_usage': lambda g: g.chat(
        [_reply('gpt', stream=True)], route='gpt', **STREAM
    ),
}


@pytest.mark.parametrize('name', list(SCENARIOS))
async def test_golden(gateway, name):
    response = SCENARIOS[name](gateway)

    assert _snapshot(gateway, response) == EXPECTED[name]


# ── Structured-output schemas sent upstream ──────────────────────────────────


class _Unit(BaseModel):
    """A temperature unit."""

    name: str = Field(description='Celsius or Fahrenheit')
    title: str


class _Nested(BaseModel):
    """A schema with definitions, a property named title and a list."""

    title: str
    unit: _Unit
    units: list[_Unit]
    maybe: _Unit | None = None


ROUTER_SCHEMA = build_response_schema(
    LLMRoutingConfig.model_validate(
        {
            'name': 'by-llm',
            'type': 'llm',
            'router_model_id': 'r',
            'default_model_id': 'gpt',
            'output_mapping': _options(),
        }
    )
)
STRUCTURED = {
    'JudgeResult': JudgeResult,
    'routing_distribution': ROUTER_SCHEMA,
    'YamlOut': YamlOut,
    '_Nested': _Nested,
}
MODELS = {
    'gpt': ('openai:gpt-x', {'api_key': 'sk'}),
    'claude': ('anthropic:claude-sonnet-4-5', {'api_key': 'sk'}),
    'gemini': ('google_genai:gemini-2.5-flash', {'api_key': 'sk'}),
    'mistral': ('mistralai:mistral-small-latest', {'api_key': 'sk'}),
    'deepseek': ('deepseek:deepseek-chat', {'api_key': 'sk'}),
}


@pytest.mark.parametrize('schema', list(STRUCTURED))
@pytest.mark.parametrize('provider', PROVIDERS)
async def test_structured_output_schema(provider, schema):
    model, params = MODELS[provider]
    chat_model = init_chat_model(model, **params).with_structured_output(
        STRUCTURED[schema], include_raw=True
    )
    patchers = _no_retries()
    for patcher in patchers:
        patcher.start()
    try:
        # Only the request matters: the empty answer may not parse.
        with (
            ProviderRecorder([_structured(provider, schema, {})]) as recorder,
            contextlib.suppress(Exception),
        ):
            await chat_model.ainvoke([HumanMessage('Hi')])
    finally:
        for patcher in reversed(patchers):
            patcher.stop()

    (request,) = recorder.requests
    body = request['body']
    sent = {
        k: body[k]
        for k in ('tools', 'tool_choice', 'response_format', 'generationConfig')
        if k in body
    }
    assert sent == SCHEMAS[f'{provider}/{schema}']
