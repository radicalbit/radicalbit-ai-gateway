"""Golden values of the response cache: what must not change when the code does.

Every endpoint that caches is driven through the HTTP app on real routes, with
the providers faked at the transport and the routes caching in memory (no
Redis client). A semantic route gets a fake index that matches equal vectors
within the three tags the real one filters on. Status codes, bodies, headers,
the keys and the stored entries, the cache events and the cache metrics are
compared with literals. Only the drivers (the functions that build the routes,
send the requests and read the store) may change.
"""

from dataclasses import replace
from decimal import Decimal
import json
import logging
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import numpy as np
import openai
from opentelemetry import trace
from opentelemetry.sdk.trace import SpanProcessor
import pytest
from starlette.requests import Request
import tiktoken
from traceloop.sdk import Traceloop
from traceloop.sdk.tracing.tracing import TracerWrapper

from tests.common import db_mock, provider_responses as upstream
from tests.common.audio import make_wav_bytes
from tests.common.provider_recorder import CannedResponse, ProviderRecorder

from radicalbit_ai_gateway import server
from radicalbit_ai_gateway.auth.api_key_validator import ApiKeyValidator
from radicalbit_ai_gateway.caching.gateway_cache import GatewayCache
from radicalbit_ai_gateway.caching.semantic_caching import SemanticCache
from radicalbit_ai_gateway.events import events_processor
from radicalbit_ai_gateway.guardrails.guardrails import Guardrails
from radicalbit_ai_gateway.guardrails.judges.judge_engine import JudgeEngine
from radicalbit_ai_gateway.guardrails.presidio import PresidioEngine
from radicalbit_ai_gateway.metrics import define_metrics
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.server import app, group_service, key_service
from radicalbit_ai_gateway.services.cost_service import CostService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.dependencies import get_request_uuid
from radicalbit_ai_gateway.utils.gateway_route_factory import (
    build_gateway_routes_from_config,
)

LOGGER = get_app_config().log_config.logger_name
CACHE_EVENTS = {
    EventType.CACHE_HIT,
    EventType.CACHE_INPUT_TOKENS,
    EventType.CACHE_OUTPUT_TOKENS,
}
MODEL_EVENTS = {EventType.MODEL_INVOCATION, EventType.INPUT_TOKEN_PROCESSED}
METRICS = ('cache_hit_counter', 'cache_input_tokens', 'cache_output_tokens')
CREDENTIALS = {'api_key': 'sk-test'}
WAV = make_wav_bytes(1.0)
API_KEY = str(db_mock.API_KEY_UUID)
PROJECT = '11111111-1111-1111-1111-111111111111'
CACHE_HIT = 'X-RB-AIGATEWAY-CACHE-HIT'
EMAIL = 'ada.lovelace@analytical-engine.example.com'


def _priced(model_id: str, name: str, **extra) -> dict:
    return {
        'model_id': model_id,
        'model': name,
        'credentials': CREDENTIALS,
        'input_cost_per_million_tokens': 1,
        'output_cost_per_million_tokens': 2,
        **extra,
    }


def _contains(name: str, where: str, behavior: str, value: str) -> dict:
    return {
        'name': name,
        'type': 'contains',
        'where': where,
        'behavior': behavior,
        'parameters': {'values': [value]},
    }


EXACT = {'type': 'exact', 'ttl': 60}
SEMANTIC = {'type': 'semantic', 'embedding_model_id': 'e2', 'dim': 4, 'ttl': 60}

CONFIG = {
    'chat_models': [_priced('gpt', 'openai/gpt-4o')],
    'embedding_models': [
        _priced('e1', 'openai/text-embedding-3-small'),
        _priced('e2', 'openai/text-embedding-3-large'),
        # A dollar a token: what its call is charged at shows.
        _priced(
            'e3',
            'openai/text-embedding-3-large',
            input_cost_per_million_tokens=1_000_000,
        ),
    ],
    'transcription_models': [_priced('t1', 'openai/gpt-4o-transcribe')],
    'decision_models': [
        {
            'model_id': 'd1',
            'model': 'typesafe/jev-latest',
            'credentials': {'api_key': 'ts-test'},
            'input_cost_per_million_tokens': 3,
        }
    ],
    'guardrails': [
        {
            'name': 'redact_in',
            'type': 'presidio_anonymizer',
            'where': 'input',
            'parameters': {'language': 'en', 'entities': ['EMAIL_ADDRESS']},
        },
        {
            'name': 'redact_out',
            'type': 'presidio_anonymizer',
            'where': 'output',
            'parameters': {'language': 'en', 'entities': ['EMAIL_ADDRESS']},
        },
        _contains('warn_out', 'output', 'warn', 'warnout'),
        _contains('soft_out', 'output', 'soft_block', 'softout'),
    ],
    'cache': {'redis_host': 'localhost', 'redis_port': 6379},
    'routes': {
        'chat': {'chat_models': ['gpt'], 'caching': EXACT},
        'guarded': {
            'chat_models': ['gpt'],
            'guardrails': ['warn_out'],
            'caching': EXACT,
        },
        'blocked': {
            'chat_models': ['gpt'],
            'guardrails': ['soft_out'],
            'caching': EXACT,
        },
        'masked': {
            'chat_models': ['gpt'],
            'guardrails': ['redact_out'],
            'caching': EXACT,
        },
        'redacted': {
            'chat_models': ['gpt'],
            'embedding_models': ['e1', 'e2'],
            'guardrails': ['redact_in'],
            'caching': EXACT,
        },
        'semantic': {
            'chat_models': ['gpt'],
            'embedding_models': ['e1', 'e2'],
            'caching': SEMANTIC,
        },
        'semantic_limited': {
            'chat_models': ['gpt'],
            'embedding_models': ['e1', 'e2'],
            'caching': SEMANTIC,
            'token_limiting': {'input': {'window_size': '1 minute', 'max_token': 22}},
        },
        'semantic_fallback': {
            'chat_models': ['gpt'],
            'embedding_models': ['e1', 'e3'],
            'fallback': [{'target': 'e1', 'fallbacks': ['e3'], 'type': 'embedding'}],
            'caching': {**SEMANTIC, 'embedding_model_id': 'e1'},
            'budget_limiting': {'window_size': '1 minute', 'max_budget': 0.5},
        },
        'semantic_redacted': {
            'chat_models': ['gpt'],
            'embedding_models': ['e1', 'e2'],
            'guardrails': ['redact_in'],
            'caching': SEMANTIC,
        },
        'embed': {'embedding_models': ['e1'], 'caching': EXACT},
        'audio': {'transcription_models': ['t1'], 'caching': EXACT},
        'agent': {'decision_models': ['d1'], 'caching': EXACT},
        'limited': {
            'chat_models': ['gpt'],
            'embedding_models': ['e1'],
            'caching': EXACT,
            'token_limiting': {'input': {'window_size': '1 minute', 'max_token': 15}},
        },
        'audio_two_seconds': {
            'transcription_models': ['t1'],
            'caching': EXACT,
            'duration_limiting': {
                'window_size': '1 minute',
                'max_duration_seconds': 2,
            },
        },
        'audio_limited': {
            'transcription_models': ['t1'],
            'caching': EXACT,
            'duration_limiting': {
                'window_size': '1 minute',
                'max_duration_seconds': 1,
            },
        },
    },
}


class FakeSemanticIndex(SemanticCache):
    """The semantic index, in memory: an entry matches an equal vector with
    the same three tags. It refuses what the real one refuses.
    """

    def __init__(self):
        self.similarity_threshold = 1.0
        self.index_name = 'ai_gateway_idx'
        self.docs: dict[str, dict] = {}

    async def get(self, cache_key: str, **kwargs) -> str | None:
        embeddings = kwargs.get('embeddings')
        if embeddings is None:
            raise ValueError('Embeddings param must be passed')
        self._build_filter_conditions(**kwargs)
        vector = embeddings.astype(np.float32).tobytes()
        for doc in self.docs.values():
            if doc['embedding'] == vector and all(
                doc[tag] == kwargs[tag]
                for tag in ('project_uuid', 'route_name', 'key_uuid')
            ):
                return doc['response']
        return None

    async def set(self, cache_key: str, response: str, ttl: int | None, **kwargs):
        embeddings = kwargs.get('embeddings')
        if embeddings is None:
            raise ValueError('Embeddings param must be passed')
        self._build_filter_conditions(**kwargs)
        self.docs[cache_key] = {
            'response': response,
            'project_uuid': kwargs['project_uuid'],
            'route_name': kwargs['route_name'],
            'key_uuid': kwargs['key_uuid'],
            'embedding': embeddings.astype(np.float32).tobytes(),
            'ttl': ttl,
        }


def _build_routes() -> dict:
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
    )
    routes = build_gateway_routes_from_config(
        config,
        guardrails,
        redis_client=None,
        cost_service=cost_service,
        httpx_client=None,
        project_uuid=PROJECT,
    )
    for route in routes.values():
        route.project_name = 'proj'
    _use_semantic_index(routes['semantic'], FakeSemanticIndex())
    _use_semantic_index(routes['semantic_redacted'], FakeSemanticIndex())
    _use_semantic_index(routes['semantic_limited'], FakeSemanticIndex())
    _use_semantic_index(routes['semantic_fallback'], FakeSemanticIndex())
    return {f'proj/{name}': route for name, route in routes.items()}


def _use_semantic_index(route, index: FakeSemanticIndex) -> None:
    route.gateway_cache = GatewayCache(index)
    route.cache = replace(route.cache, backend=route.gateway_cache)


def _stored(route) -> dict[str, str]:
    """Return what a route's cache holds: its entries by key."""
    client = route.gateway_cache.cache_client
    if isinstance(client, FakeSemanticIndex):
        return {key: doc['response'] for key, doc in client.docs.items()}
    return {key: value['response'] for key, (value, _) in client._cache.items()}


def _plant(route, key: str, raw: str) -> None:
    """Write an entry straight into a route's in-memory cache, as a gateway
    before this one may have left it.
    """
    route.gateway_cache.cache_client._cache[key] = (
        {'response': raw, 'exp': None},
        None,
    )


def _mock_request_uuid(request: Request):
    request.state.request_uuid = str(db_mock.REQUEST_UUID)
    return str(db_mock.REQUEST_UUID)


@pytest.fixture
def gateway(caplog):
    routes = _build_routes()
    app.dependency_overrides[get_request_uuid] = _mock_request_uuid
    saved_validator = app.state.token_validator
    saved_routes = getattr(app.state, 'routes', None)
    app.state.token_validator = ApiKeyValidator(key_service=key_service)
    app.state.routes = routes
    api_key = db_mock.get_sample_key_with_group(
        uuid=db_mock.API_KEY_UUID, group_uuid=db_mock.GROUP_UUID
    )
    events: list = []
    metrics: list = []
    patchers = [
        patch.object(key_service, 'get_key_by_hashed_key', return_value=api_key),
        patch.object(group_service, 'check_key_uuid_for_route', return_value=True),
        patch.object(
            server.project_budget_limit_dao, 'get_by_project_uuid', return_value=[]
        ),
        patch.object(events_processor._events_buffer, 'add', side_effect=events.append),
        patch.object(
            openai._base_client.BaseClient, '_should_retry', return_value=False
        ),
        *(
            patch.object(
                getattr(define_metrics, name),
                'add',
                side_effect=lambda value, attributes, name=name: metrics.append(
                    (name, value, dict(attributes))
                ),
            )
            for name in METRICS
        ),
    ]
    for patcher in patchers:
        patcher.start()
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    try:
        yield _Gateway(TestClient(app), routes, events, metrics)
    finally:
        for patcher in reversed(patchers):
            patcher.stop()
        app.state.token_validator = saved_validator
        if saved_routes is not None:
            app.state.routes = saved_routes
        app.dependency_overrides = {}


class _Gateway:
    def __init__(self, client: TestClient, routes: dict, events: list, metrics):
        self.client = client
        self.routes = routes
        self._events = events
        self.metrics = metrics
        self.headers = {'Authorization': f'Bearer {db_mock.PLAIN_KEY}'}
        self.upstream: list[dict] = []

    def post(self, path: str, replies: list[CannedResponse], **kwargs):
        self._events.clear()
        self.metrics.clear()
        with ProviderRecorder(replies) as recorder:
            response = self.client.post(path, headers=self.headers, **kwargs)
        assert recorder.unused == 0, 'a canned reply was not asked for'
        self.upstream = recorder.requests
        return response

    def chat(self, replies, route='chat', text='Where is Paris?', **params):
        return self.post(
            '/v1/chat/completions',
            replies,
            json={
                'model': f'proj/{route}',
                'messages': [{'role': 'user', 'content': text}],
                **params,
            },
        )

    def responses(self, replies, route='chat', text='Where is Paris?', **params):
        return self.post(
            '/v1/responses',
            replies,
            json={'model': f'proj/{route}', 'input': text, **params},
        )

    def embed(self, replies, texts=('one', 'two')):
        return self.post(
            '/v1/embeddings',
            replies,
            json={'model': 'proj/embed', 'input': list(texts)},
        )

    def transcribe(self, replies, stream=False, route='audio', audio=WAV):
        return self.post(
            '/v1/audio/transcriptions',
            replies,
            data={'model': f'proj/{route}', 'stream': str(stream).lower()},
            files={'file': ('a.wav', audio, 'audio/wav')},
        )

    def decide(self, replies):
        return self.post(
            '/v1/systemone',
            replies,
            json={
                'model': 'proj/agent',
                'state': {'ticket': 'printer on fire'},
                'questions': {'urgent': {'type': 'noul', 'instructions': 'Urgent?'}},
            },
        )

    def stored(self, route: str) -> dict[str, str]:
        return _stored(self.routes[f'proj/{route}'])

    def cache_events(self) -> list[tuple]:
        """Return the cache events: type, value, cost, cache type, model."""
        return [
            (
                e['EVENT_TYPE'].name,
                e['VALUE'],
                Decimal(str(e['COST'])),
                e['CACHE_TYPE'],
                e['MODEL_ID'],
            )
            for e in self._events
            if e['EVENT_TYPE'] in CACHE_EVENTS
        ]

    def model_events(self) -> list[tuple]:
        """Return the model events: type, model, model type, cache type, value."""
        return [
            (
                e['EVENT_TYPE'].name,
                e['MODEL_ID'],
                e['MODEL_TYPE'],
                e['CACHE_TYPE'],
                e['VALUE'],
            )
            for e in self._events
            if e['EVENT_TYPE'] in MODEL_EVENTS
        ]


def _cache_headers(response) -> dict[str, str]:
    return {
        k.upper(): v
        for k, v in response.headers.items()
        if k.upper().startswith('X-RB-AIGATEWAY-')
    }


def _body(response) -> dict:
    body = response.json()
    for field in ('id', 'created', 'created_at', 'completed_at'):
        body.pop(field, None)
    return body


def _sse(response) -> list:
    """Return the data frames of a stream, without ids and timestamps."""
    frames = []
    for line in response.text.splitlines():
        if not line.startswith('data: '):
            continue
        data = line[len('data: ') :]
        if data == '[DONE]':
            frames.append(data)
            continue
        frame = json.loads(data)
        frame.pop('id', None)
        frame.pop('created', None)
        frame.pop('sequence_number', None)
        if isinstance(frame.get('response'), dict):
            for field in ('id', 'created_at', 'completed_at'):
                frame['response'].pop(field, None)
        frames.append(frame)
    return frames


def _entries(stored: dict[str, str]) -> dict[str, dict]:
    """Return stored entries as JSON, without ids and timestamps."""
    entries = {}
    for key, raw in stored.items():
        entry = json.loads(raw)
        for field in ('id', 'created', 'created_at', 'completed_at'):
            entry.pop(field, None)
        entries[key] = entry
    return entries


def _completion(text: str = 'Paris is in France') -> CannedResponse:
    return upstream.openai_completion(
        text, model='gpt-4o', prompt_tokens=11, completion_tokens=5
    )


def _stream(*parts: str) -> CannedResponse:
    return upstream.openai_stream(
        list(parts or ('Paris', ' is in France')),
        model='gpt-4o',
        prompt_tokens=11,
        completion_tokens=5,
    )


def _transcription(text: str = 'hello') -> CannedResponse:
    return CannedResponse(
        json_body={
            'text': text,
            'usage': {
                'type': 'tokens',
                'input_tokens': 10,
                'output_tokens': 3,
                'total_tokens': 13,
                'input_token_details': {'audio_tokens': 8, 'text_tokens': 2},
            },
        }
    )


def _transcription_stream(text: str = 'hello') -> CannedResponse:
    return CannedResponse(
        sse_events=[
            {'type': 'transcript.text.delta', 'delta': text},
            {
                'type': 'transcript.text.done',
                'text': text,
                'usage': {
                    'type': 'tokens',
                    'input_tokens': 10,
                    'output_tokens': 3,
                    'total_tokens': 13,
                    'input_token_details': {'audio_tokens': 8, 'text_tokens': 2},
                },
            },
        ]
    )


def _typesafe() -> CannedResponse:
    return CannedResponse(
        json_body={
            'answers': {'urgent': {'type': 'noul', 'noul': 0.9}},
            'model': 'jev-1',
            'usage': {'input_tokens': 40, 'output_tokens': 2},
        }
    )


def _hit_events(model: str, cache_type: str = 'in-memory', tokens=(11, 5)):
    """Return the events of a chat or Responses hit: the hit, then its tokens
    at the model's prices.
    """
    events = [('CACHE_HIT', 1.0, Decimal(0), cache_type, model)]
    if tokens[0]:
        events.append(
            (
                'CACHE_INPUT_TOKENS',
                float(tokens[0]),
                Decimal(str(tokens[0] / 1e6)),
                cache_type,
                model,
            )
        )
    if tokens[1]:
        events.append(
            (
                'CACHE_OUTPUT_TOKENS',
                float(tokens[1]),
                Decimal(str(tokens[1] * 2 / 1e6)),
                cache_type,
                model,
            )
        )
    return events


def _hit_metrics(route: str, model: str, tokens=(11, 5)) -> list[tuple]:
    metrics = [('cache_hit_counter', 1, {'route_name': route})]
    attributes = {'route_name': route, 'model_name': model}
    if tokens[0]:
        metrics.append(('cache_input_tokens', tokens[0], attributes))
    if tokens[1]:
        metrics.append(('cache_output_tokens', tokens[1], attributes))
    return metrics


# ---------------------------------------------------------------------------
# Keys: the signature of each endpoint, hashed into the same key format
# ---------------------------------------------------------------------------

KEY = 'response:aigateway:cache:11111111-1111-1111-1111-111111111111:{route}:00000000-0000-0000-0000-000000000000:{sha}'
GOLDEN_KEYS = {
    'chat': KEY.format(
        route='chat',
        sha='a05886ad5eb0e3ac7ea0bba408fa8a598fe038eb0e4c83e6df5be82b053f5dbc',
    ),
    'responses': KEY.format(
        route='chat',
        sha='4cf9540301652357006dde0bf8675b9db5226e009af788bc71b362ee23314819',
    ),
    'embed': KEY.format(
        route='embed',
        sha='de8edb9544636d24b816d26afef4e8371ce857b4a8fe720fd13ae27cc4699b4d',
    ),
    'audio': KEY.format(
        route='audio',
        sha='6ea8cc4b6a77f68c561566cb2afe3ccb1a329ca078091ad233e4b93519e55bb0',
    ),
    'agent': KEY.format(
        route='agent',
        sha='783065e9764d1c485e1bd599f4a02d9dfa2e24c4c16dbbb4727faa0af8456cea',
    ),
}


def test_keys_of_every_endpoint(gateway):
    gateway.chat([_completion()])
    gateway.responses([upstream.openai_response('Paris is in France')])
    gateway.embed([upstream.openai_embeddings()])
    gateway.transcribe([_transcription()])
    gateway.decide([_typesafe()])

    assert list(gateway.stored('chat')) == [
        GOLDEN_KEYS['chat'],
        GOLDEN_KEYS['responses'],
    ]
    for route in ('embed', 'audio', 'agent'):
        assert list(gateway.stored(route)) == [GOLDEN_KEYS[route]]


# ---------------------------------------------------------------------------
# Chat completions
# ---------------------------------------------------------------------------


def test_chat_hit(gateway):
    miss = gateway.chat([_completion()])
    hit = gateway.chat([])

    assert miss.status_code == hit.status_code == 200
    assert _cache_headers(miss) == {}
    assert _cache_headers(hit) == {CACHE_HIT: 'true'}
    assert _body(hit) == _body(miss) == GOLDEN['chat_body']
    assert hit.json()['id'] == miss.json()['id']
    assert _entries(gateway.stored('chat')) == {
        GOLDEN_KEYS['chat']: GOLDEN['chat_entry']
    }
    assert gateway.cache_events() == _hit_events('gpt')
    assert gateway.metrics == _hit_metrics('chat', 'gpt')


def test_chat_live_stream_hit(gateway):
    options = {'stream': True, 'stream_options': {'include_usage': True}}
    miss = gateway.chat([_stream()], **options)
    hit = gateway.chat([], **options)

    assert miss.status_code == hit.status_code == 200
    assert _cache_headers(miss) == {}
    assert _cache_headers(hit) == {CACHE_HIT: 'true'}
    # One chunk with the whole text and its usage, and no usage chunk (D16).
    assert _sse(hit) == GOLDEN['live_stream_hit']
    assert list(_entries(gateway.stored('chat')).values()) == [GOLDEN['stream_entry']]
    assert gateway.cache_events() == _hit_events('gpt')


def test_chat_buffered_stream_hit(gateway):
    options = {'stream': True, 'stream_options': {'include_usage': True}}
    miss = gateway.chat([_stream()], route='guarded', **options)
    hit = gateway.chat([], route='guarded', **options)

    assert miss.status_code == hit.status_code == 200
    assert _cache_headers(hit) == {CACHE_HIT: 'true'}
    assert _sse(hit) == GOLDEN['buffered_stream_hit']
    assert list(_entries(gateway.stored('guarded')).values()) == [
        GOLDEN['stream_entry']
    ]
    stored = json.loads(next(iter(gateway.stored('guarded').values())))
    assert stored['id'] == str(db_mock.REQUEST_UUID)
    assert gateway.cache_events() == _hit_events('gpt')


def test_a_soft_blocked_reply_is_cached_and_its_hit_loses_the_flags(gateway):
    """D12, kept: the hit answers the block without the block's headers."""
    miss = gateway.chat([_completion('softout')], route='blocked')
    hit = gateway.chat([], route='blocked')

    assert _cache_headers(miss) == {
        'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-TRIGGERED': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN': 'true',
    }
    assert _cache_headers(hit) == {CACHE_HIT: 'true'}
    assert _body(hit) == _body(miss)
    assert hit.json()['choices'][0]['message']['content'] == (
        'This response has been blocked due to policy violation: soft_out'
    )


def test_chat_without_a_user_message_is_not_cached(gateway):
    for _ in range(2):
        gateway.post(
            '/v1/chat/completions',
            [_completion()],
            json={
                'model': 'proj/chat',
                'messages': [{'role': 'system', 'content': 'Be brief.'}],
            },
        )

    assert gateway.stored('chat') == {}


def test_chat_keys_on_the_last_user_turn(gateway):
    gateway.chat([_completion()])
    hit = gateway.post(
        '/v1/chat/completions',
        [],
        json={
            'model': 'proj/chat',
            'messages': [
                {'role': 'user', 'content': 'Hello'},
                {'role': 'assistant', 'content': 'Hi'},
                {'role': 'user', 'content': 'Where is Paris?'},
            ],
        },
    )

    assert _cache_headers(hit) == {CACHE_HIT: 'true'}


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


def test_responses_hit(gateway):
    miss = gateway.responses([upstream.openai_response('Paris is in France')])
    hit = gateway.responses([])
    live = gateway.responses([], stream=True)
    buffered_miss = gateway.responses(
        [upstream.openai_response('Paris is in France')], route='guarded'
    )
    buffered = gateway.responses([], route='guarded', stream=True)

    assert miss.status_code == hit.status_code == live.status_code == 200
    assert _cache_headers(hit) == _cache_headers(live) == {CACHE_HIT: 'true'}
    assert _cache_headers(buffered) == {CACHE_HIT: 'true'}
    assert _body(hit) == _body(miss) == GOLDEN['responses_body']
    assert hit.json()['completed_at'] is None
    for stream, route in ((live, 'chat'), (buffered, 'guarded')):
        frames = _sse(stream)
        assert [frame['type'] for frame in frames] == RESPONSES_STREAM_EVENTS
        assert frames[-1]['response'] == {
            **GOLDEN['responses_body'],
            'model': route,
        }
    assert _entries(gateway.stored('chat')) == {
        GOLDEN_KEYS['responses']: GOLDEN['responses_entry']
    }
    assert buffered_miss.status_code == 200
    assert gateway.cache_events() == _hit_events('gpt', tokens=(21, 7))


# ---------------------------------------------------------------------------
# Embeddings, transcription, decision
# ---------------------------------------------------------------------------


def test_embeddings_hit(gateway):
    miss = gateway.embed([upstream.openai_embeddings()])
    hit = gateway.embed([])

    assert miss.status_code == hit.status_code == 200
    # D16, kept: no cache header.
    assert _cache_headers(hit) == {}
    assert hit.json() == miss.json()
    assert _entries(gateway.stored('embed')) == {
        GOLDEN_KEYS['embed']: GOLDEN['embed_entry']
    }
    assert gateway.cache_events() == [
        ('CACHE_HIT', 1.0, Decimal(0), 'in-memory', 'text-embedding-3-small'),
        (
            'CACHE_INPUT_TOKENS',
            2.0,
            Decimal(0),
            'in-memory',
            'text-embedding-3-small',
        ),
    ]


def test_transcription_hit(gateway):
    miss = gateway.transcribe([_transcription()])
    hit = gateway.transcribe([])

    assert miss.status_code == hit.status_code == 200
    # D16, kept: no cache header.
    assert _cache_headers(hit) == {}
    assert hit.json() == miss.json()
    assert _entries(gateway.stored('audio')) == {
        GOLDEN_KEYS['audio']: GOLDEN['audio_entry']
    }
    assert gateway.cache_events() == [('CACHE_HIT', 1.0, Decimal(0), 'in-memory', 't1')]
    assert gateway.metrics == [('cache_hit_counter', 1, {'route_name': 'audio'})]


def test_transcription_streams_are_not_cached(gateway):
    for _ in range(2):
        response = gateway.transcribe([_transcription_stream()], stream=True)
        assert response.status_code == 200

    assert gateway.stored('audio') == {}


def test_decision_hit(gateway):
    miss = gateway.decide([_typesafe()])
    hit = gateway.decide([])

    assert miss.status_code == hit.status_code == 200
    assert hit.content == miss.content
    assert _entries(gateway.stored('agent')) == {
        GOLDEN_KEYS['agent']: GOLDEN['agent_entry']
    }
    # A hit's input tokens cost nothing.
    assert gateway.cache_events() == [
        ('CACHE_HIT', 1.0, Decimal(0), 'in-memory', 'd1'),
        ('CACHE_INPUT_TOKENS', 40.0, Decimal(0), 'in-memory', 'd1'),
    ]
    assert gateway.metrics == [
        ('cache_hit_counter', 1, {'route_name': 'agent'}),
        ('cache_input_tokens', 40, {'route_name': 'agent', 'model_name': 'd1'}),
    ]


# ---------------------------------------------------------------------------
# Semantic cache
# ---------------------------------------------------------------------------


def _tokens(text: str) -> list[int]:
    return tiktoken.encoding_for_model('text-embedding-3-small').encode(text)


def _embedding_call(model: str = 'e1') -> list[tuple]:
    """Return the events of the semantic cache's embedding call, flagged semantic."""
    return [
        ('MODEL_INVOCATION', model, 'embeddings', 'semantic', 1.0),
        ('INPUT_TOKEN_PROCESSED', model, 'embeddings', 'semantic', 4.0),
    ]


def test_semantic_chat_hit(gateway):
    miss = gateway.chat(
        [upstream.openai_embeddings(count=1), _completion()], route='semantic'
    )
    hit = gateway.chat([upstream.openai_embeddings(count=1)], route='semantic')

    assert miss.status_code == hit.status_code == 200
    assert _cache_headers(hit) == {CACHE_HIT: 'true'}
    assert _body(hit) == _body(miss)
    # D14, kept: the route's first embedding model embeds, not the one the
    # caching block names.
    assert gateway.upstream[0]['url'] == 'https://api.openai.com/v1/embeddings'
    assert gateway.upstream[0]['body']['model'] == 'text-embedding-3-small'
    assert gateway.upstream[0]['body']['input'] == [_tokens('Where is Paris?')]
    assert gateway.model_events() == _embedding_call()
    assert gateway.cache_events() == _hit_events('gpt', cache_type='semantic')
    assert gateway.metrics == _hit_metrics('semantic', 'gpt')
    assert list(gateway.stored('semantic')) == [GOLDEN['semantic_chat_key']]


def test_semantic_responses_hit(gateway):
    miss = gateway.responses(
        [upstream.openai_embeddings(count=1), upstream.openai_response('Paris')],
        route='semantic',
    )
    hit = gateway.responses([upstream.openai_embeddings(count=1)], route='semantic')

    assert miss.status_code == hit.status_code == 200
    assert _cache_headers(hit) == {CACHE_HIT: 'true'}
    assert _body(hit) == _body(miss)
    assert gateway.model_events() == _embedding_call()
    assert gateway.cache_events() == _hit_events(
        'gpt', cache_type='semantic', tokens=(21, 7)
    )
    assert list(gateway.stored('semantic')) == [GOLDEN['semantic_responses_key']]


def test_semantic_responses_without_an_embedding_skip_the_cache(gateway):
    for _ in range(2):
        response = gateway.responses(
            [upstream.error(500), upstream.openai_response('Paris')],
            route='semantic',
        )
        assert response.status_code == 200
        assert _cache_headers(response) == {}

    assert gateway.stored('semantic') == {}


RESPONSES_STREAM_EVENTS = [
    'response.created',
    'response.in_progress',
    'response.output_item.added',
    'response.reasoning_summary_part.added',
    'response.reasoning_summary_text.delta',
    'response.reasoning_summary_text.done',
    'response.reasoning_summary_part.done',
    'response.output_item.done',
    'response.output_item.added',
    'response.content_part.added',
    'response.output_text.delta',
    'response.output_text.done',
    'response.content_part.done',
    'response.output_item.done',
    'response.completed',
]


GOLDEN = {
    'agent_entry': {
        'status_code': 200,
        'content': '{"answers": {"urgent": {"type": "noul", "noul": 0.9}}, "model": "d1", "usage": {"input_tokens": 40, "output_tokens": 2}}',
        'media_type': 'application/json',
        'model_id': 'd1',
        'input_tokens': 40,
    },
    'audio_entry': {
        'text': 'hello',
        'languages': None,
        'logprobs': None,
        'usage': {
            'input_tokens': 10,
            'output_tokens': 3,
            'total_tokens': 13,
            'type': 'tokens',
            'input_token_details': {'audio_tokens': 8, 'text_tokens': 2},
        },
    },
    'buffered_stream_hit': [
        {
            'choices': [
                {
                    'delta': {'content': 'Paris is in France', 'role': 'assistant'},
                    'finish_reason': 'stop',
                    'index': 0,
                }
            ],
            'model': 'guarded',
            'object': 'chat.completion.chunk',
            'usage': {'completion_tokens': 5, 'prompt_tokens': 11, 'total_tokens': 16},
        },
        {
            'choices': [],
            'model': 'guarded',
            'object': 'chat.completion.chunk',
            'usage': {'completion_tokens': 5, 'prompt_tokens': 11, 'total_tokens': 16},
        },
        '[DONE]',
    ],
    'chat_body': {
        'choices': [
            {
                'finish_reason': 'stop',
                'index': 0,
                'logprobs': None,
                'message': {
                    'content': 'Paris is in France',
                    'refusal': None,
                    'role': 'assistant',
                    'annotations': None,
                    'audio': None,
                    'function_call': None,
                    'tool_calls': None,
                },
            }
        ],
        'model': 'chat',
        'object': 'chat.completion',
        'metadata': None,
        'moderation': None,
        'service_tier': None,
        'system_fingerprint': None,
        'usage': {
            'completion_tokens': 5,
            'prompt_tokens': 11,
            'total_tokens': 16,
            'completion_tokens_details': None,
            'prompt_tokens_details': None,
        },
    },
    'chat_entry': {
        'choices': [
            {
                'finish_reason': 'stop',
                'index': 0,
                'logprobs': None,
                'message': {
                    'content': 'Paris is in France',
                    'refusal': None,
                    'role': 'assistant',
                    'annotations': None,
                    'audio': None,
                    'function_call': None,
                    'tool_calls': None,
                },
            }
        ],
        'model': 'gpt',
        'object': 'chat.completion',
        'metadata': None,
        'moderation': None,
        'service_tier': None,
        'system_fingerprint': None,
        'usage': {
            'completion_tokens': 5,
            'prompt_tokens': 11,
            'total_tokens': 16,
            'completion_tokens_details': None,
            'prompt_tokens_details': None,
        },
    },
    'embed_entry': {
        'data': [
            {'embedding': [0.1, 0.11, 0.12, 0.13], 'index': 0, 'object': 'embedding'},
            {'embedding': [0.2, 0.21, 0.22, 0.23], 'index': 1, 'object': 'embedding'},
        ],
        'model': 'text-embedding-3-small',
        'object': 'list',
        'usage': {'prompt_tokens': 2, 'total_tokens': 2},
    },
    'live_stream_hit': [
        {
            'choices': [
                {
                    'delta': {'content': 'Paris is in France', 'role': 'assistant'},
                    'finish_reason': 'stop',
                    'index': 0,
                }
            ],
            'model': 'chat',
            'object': 'chat.completion.chunk',
            'usage': {'completion_tokens': 5, 'prompt_tokens': 11, 'total_tokens': 16},
        },
        '[DONE]',
    ],
    'responses_body': {
        'object': 'response',
        'status': 'completed',
        'model': 'chat',
        'output': [
            {
                'type': 'reasoning',
                'id': 'rs_golden_1',
                'summary': [{'type': 'summary_text', 'text': 'Thinking.'}],
            },
            {
                'type': 'message',
                'id': 'msg_golden_1',
                'status': 'completed',
                'role': 'assistant',
                'content': [
                    {
                        'type': 'output_text',
                        'text': 'Paris is in France',
                        'annotations': [],
                    }
                ],
            },
        ],
        'error': None,
        'incomplete_details': None,
        'instructions': None,
        'metadata': {},
        'parallel_tool_calls': True,
        'temperature': 1.0,
        'top_p': 1.0,
        'tool_choice': 'auto',
        'tools': [],
        'text': {'format': {'type': 'text'}},
        'usage': {
            'input_tokens': 21,
            'input_tokens_details': {'cached_tokens': 4},
            'output_tokens': 7,
            'output_tokens_details': {'reasoning_tokens': 3},
            'total_tokens': 28,
        },
    },
    'responses_entry': {
        'object': 'response',
        'status': 'completed',
        'model': 'gpt',
        'output': [
            {
                'type': 'reasoning',
                'id': 'rs_golden_1',
                'summary': [{'type': 'summary_text', 'text': 'Thinking.'}],
            },
            {
                'type': 'message',
                'id': 'msg_golden_1',
                'status': 'completed',
                'role': 'assistant',
                'content': [
                    {
                        'type': 'output_text',
                        'text': 'Paris is in France',
                        'annotations': [],
                    }
                ],
            },
        ],
        'error': None,
        'incomplete_details': None,
        'instructions': None,
        'metadata': {},
        'parallel_tool_calls': True,
        'temperature': 1.0,
        'top_p': 1.0,
        'tool_choice': 'auto',
        'tools': [],
        'text': {'format': {'type': 'text'}},
        'usage': {
            'input_tokens': 21,
            'input_tokens_details': {'cached_tokens': 4},
            'output_tokens': 7,
            'output_tokens_details': {'reasoning_tokens': 3},
            'total_tokens': 28,
        },
    },
    'semantic_chat_key': 'response:aigateway:cache:11111111-1111-1111-1111-111111111111:semantic:00000000-0000-0000-0000-000000000000:a05886ad5eb0e3ac7ea0bba408fa8a598fe038eb0e4c83e6df5be82b053f5dbc',
    'semantic_responses_key': 'response:aigateway:cache:11111111-1111-1111-1111-111111111111:semantic:00000000-0000-0000-0000-000000000000:d44bdef4c1e59fbd2d6df44325002c250dc24d2a3013b25d528df80df13d5034',
    'stream_entry': {
        'choices': [
            {
                'finish_reason': 'stop',
                'index': 0,
                'logprobs': None,
                'message': {
                    'content': 'Paris is in France',
                    'refusal': None,
                    'role': 'assistant',
                    'annotations': None,
                    'audio': None,
                    'function_call': None,
                    'tool_calls': None,
                },
            }
        ],
        'model': 'gpt',
        'object': 'chat.completion',
        'metadata': None,
        'moderation': None,
        'service_tier': None,
        'system_fingerprint': None,
        'usage': {
            'completion_tokens': 5,
            'prompt_tokens': 11,
            'total_tokens': 16,
            'completion_tokens_details': None,
            'prompt_tokens_details': None,
        },
    },
}


# ---------------------------------------------------------------------------
# Trace spans: the cache's spans, in the order they end, and their category
# ---------------------------------------------------------------------------

CACHE_SPANS = {
    'lookup_cache',
    'get_cached_response',
    'set_cached_response',
    'set_cached_stream_response',
    'generate_semantic_cache_embedding',
    'lookup_responses_cache',
    'get_in_memory_cache',
    'set_in_memory_cache',
}
CATEGORY = 'traceloop.association.properties.rb.gateway.operation_category'


class _SpanCollector(SpanProcessor):
    """Keeps the spans that end while it is on."""

    def __init__(self):
        self.on = False
        self.spans: list = []

    def on_end(self, span) -> None:
        if self.on:
            self.spans.append(span)


@pytest.fixture(scope='module')
def span_collector():
    collector = _SpanCollector()
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


@pytest.fixture
def spans(span_collector):
    def collect(send) -> list[tuple[str, str]]:
        span_collector.spans.clear()
        span_collector.on = True
        try:
            send()
        finally:
            span_collector.on = False
        return [
            (span.name.rsplit('.', 1)[0], span.attributes.get(CATEGORY))
            for span in span_collector.spans
            if span.name.rsplit('.', 1)[0] in CACHE_SPANS
        ]

    return collect


def test_spans_of_chat(gateway, spans):
    assert spans(lambda: gateway.chat([_completion()])) == GOLDEN_SPANS['chat_miss']
    assert spans(lambda: gateway.chat([])) == GOLDEN_SPANS['chat_hit']
    stream = {'stream': True, 'text': 'Where is Rome?'}
    assert (
        spans(lambda: gateway.chat([_stream()], **stream))
        == GOLDEN_SPANS['live_stream_miss']
    )
    assert (
        spans(lambda: gateway.chat([_stream()], route='guarded', **stream))
        == GOLDEN_SPANS['buffered_stream_miss']
    )
    assert (
        spans(
            lambda: gateway.chat(
                [upstream.openai_embeddings(count=1), _completion()], route='semantic'
            )
        )
        == GOLDEN_SPANS['semantic_miss']
    )


def test_spans_of_other_endpoints(gateway, spans):
    reply = upstream.openai_response('Paris is in France')
    assert spans(lambda: gateway.responses([reply])) == GOLDEN_SPANS['responses_miss']
    assert spans(lambda: gateway.responses([])) == GOLDEN_SPANS['responses_hit']
    assert (
        spans(lambda: gateway.embed([upstream.openai_embeddings()]))
        == (GOLDEN_SPANS['embed_miss'])
    )
    assert spans(lambda: gateway.embed([])) == GOLDEN_SPANS['embed_hit']
    assert (
        spans(lambda: gateway.transcribe([_transcription()]))
        == (GOLDEN_SPANS['audio_miss'])
    )
    assert spans(lambda: gateway.decide([_typesafe()])) == GOLDEN_SPANS['agent_miss']


GOLDEN_SPANS = {
    'chat_miss': [
        ('get_in_memory_cache', 'cache'),
        ('get_cached_response', 'cache'),
        ('lookup_cache', 'cache'),
        ('set_in_memory_cache', 'cache'),
        ('set_cached_response', 'cache'),
    ],
    'chat_hit': [
        ('get_in_memory_cache', 'cache'),
        ('get_cached_response', 'cache'),
        ('lookup_cache', 'cache'),
    ],
    'live_stream_miss': [
        ('get_in_memory_cache', 'cache'),
        ('get_cached_response', 'cache'),
        ('lookup_cache', 'cache'),
        ('set_in_memory_cache', 'cache'),
        ('set_cached_response', 'cache'),
        ('set_cached_stream_response', 'cache'),
    ],
    'buffered_stream_miss': [
        ('get_in_memory_cache', 'cache'),
        ('get_cached_response', 'cache'),
        ('lookup_cache', 'cache'),
        ('set_in_memory_cache', 'cache'),
        ('set_cached_response', 'cache'),
        ('set_cached_stream_response', 'cache'),
    ],
    'semantic_miss': [
        ('generate_semantic_cache_embedding', 'cache'),
        ('get_cached_response', 'cache'),
        ('lookup_cache', 'cache'),
        ('set_cached_response', 'cache'),
    ],
    'responses_miss': [
        ('get_in_memory_cache', 'cache'),
        ('lookup_responses_cache', 'cache'),
        ('set_in_memory_cache', 'cache'),
    ],
    'responses_hit': [
        ('get_in_memory_cache', 'cache'),
        ('lookup_responses_cache', 'cache'),
    ],
    # The cache marks its writes CACHE on every endpoint.
    'embed_miss': [
        ('get_in_memory_cache', 'cache'),
        ('set_in_memory_cache', 'cache'),
    ],
    'embed_hit': [('get_in_memory_cache', 'cache')],
    'audio_miss': [
        ('get_in_memory_cache', 'cache'),
        ('set_in_memory_cache', 'cache'),
    ],
    'agent_miss': [
        ('get_in_memory_cache', 'cache'),
        ('set_in_memory_cache', 'cache'),
    ],
}


# ---------------------------------------------------------------------------
# Fixed defects
# ---------------------------------------------------------------------------


def test_semantic_chat_that_cannot_be_embedded_skips_the_cache(gateway):
    """D11: no embedding is a request the cache does not serve, not a 500."""
    for _ in range(2):
        response = gateway.chat([upstream.error(500), _completion()], route='semantic')
        assert response.status_code == 200
        assert _cache_headers(response) == {}

    response = gateway.post(
        '/v1/chat/completions',
        [_completion()],
        json={
            'model': 'proj/semantic',
            'messages': [{'role': 'system', 'content': 'Be brief.'}],
        },
    )
    assert response.status_code == 200
    assert gateway.stored('semantic') == {}


def test_a_responses_request_over_its_limit_is_not_served_from_the_cache(gateway):
    """D10: the limits are checked before the lookup, as on chat."""
    first = gateway.responses([upstream.openai_response('Paris')], route='limited')
    second = gateway.responses([], route='limited')

    assert first.status_code == 200
    assert second.status_code == 429
    assert _cache_headers(second) == {}
    assert gateway.cache_events() == []


def test_a_transcription_over_its_limit_is_not_served_from_the_cache(gateway):
    """D10: the limits are checked before the lookup, as on chat."""
    first = gateway.transcribe([_transcription()], route='audio_limited')
    second = gateway.transcribe([], route='audio_limited')

    assert first.status_code == 200
    assert second.status_code == 429
    assert gateway.cache_events() == []


def test_a_semantic_responses_request_over_its_limit_embeds_nothing(gateway):
    """D10: the limit check comes before the embedding call spends."""
    limited = gateway.routes['proj/limited']
    _use_semantic_index(limited, FakeSemanticIndex())
    gateway.responses(
        [upstream.openai_embeddings(count=1), upstream.openai_response('Paris')],
        route='limited',
    )

    response = gateway.responses([], route='limited')

    assert response.status_code == 429
    assert gateway.upstream == []


INPUT_WARN = {
    'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true',
    'X-RB-AIGATEWAY-GUARDRAILS-INPUT-WARN': 'true',
}


def test_chat_keys_on_the_redacted_text(gateway):
    """D13: messages that differ only in what a redaction masks share an
    entry, as on Responses and embeddings.
    """
    miss = gateway.chat([_completion()], route='redacted', text=f'Mail {EMAIL}')
    hit = gateway.chat([], route='redacted', text='Mail grace.hopper@navy.example.com')

    assert _cache_headers(miss) == INPUT_WARN
    assert _cache_headers(hit) == {CACHE_HIT: 'true', **INPUT_WARN}
    # The key of the redacted turn, 'Mail <EMAIL_ADDRESS>'.
    assert list(gateway.stored('redacted')) == [
        KEY.format(
            route='redacted',
            sha='10e99a91147f96fc8e87033e0d16e9d7c099793a5b7f18e51e59f791efa07b74',
        )
    ]


def test_semantic_chat_embeds_the_redacted_text(gateway):
    """D13: no text a redaction masks reaches the embedding provider (ADR 0010)."""
    response = gateway.chat(
        [upstream.openai_embeddings(count=1), _completion()],
        route='semantic_redacted',
        text=f'Mail {EMAIL}',
    )

    assert response.status_code == 200
    assert gateway.upstream[0]['url'] == 'https://api.openai.com/v1/embeddings'
    assert gateway.upstream[0]['body']['input'] == [_tokens('Mail <EMAIL_ADDRESS>')]
    assert EMAIL not in json.dumps(gateway.upstream)


def test_stream_and_non_stream_requests_share_an_entry(gateway):
    """D17: chat keys leave out stream and stream_options, as Responses keys
    do. An entry stored by either shape answers both.
    """
    gateway.chat([_completion()], stream=False)
    live = gateway.chat([], stream=True, stream_options={'include_usage': True})
    plain = gateway.chat([])

    assert _cache_headers(live) == _cache_headers(plain) == {CACHE_HIT: 'true'}
    assert _sse(live) == GOLDEN['live_stream_hit']
    assert list(gateway.stored('chat')) == [GOLDEN_KEYS['chat']]

    gateway.chat([_stream()], route='guarded', stream=True)
    hit = gateway.chat([], route='guarded')

    assert _cache_headers(hit) == {CACHE_HIT: 'true'}
    assert _body(hit) == {**GOLDEN['chat_body'], 'model': 'guarded'}


def test_a_stream_does_not_replay_a_reply_with_tool_calls(gateway):
    """D17: a stream hit replays text only, so a stored tool call is a miss
    for a stream, not an empty reply.
    """
    gateway.chat(
        [
            upstream.openai_completion(
                None, model='gpt-4o', tool_calls=[upstream.WEATHER_TOOL_CALL]
            )
        ]
    )

    stream = gateway.chat([_stream()], stream=True)

    assert stream.status_code == 200
    assert _cache_headers(stream) == {}
    assert len(gateway.upstream) == 1


def test_a_streamed_tool_call_is_stored_whole(gateway):
    """D17: a streamed reply is stored as the completion a non-streamed call
    would get: a tool call answers a plain request with the tool call, and
    is a miss for a stream, which replays text only.
    """
    gateway.chat(
        [
            upstream.openai_stream(
                [], model='gpt-4o', tool_calls=[upstream.WEATHER_TOOL_CALL]
            )
        ],
        route='guarded',
        stream=True,
    )
    plain = gateway.chat([], route='guarded')
    stream = gateway.chat([_stream()], route='guarded', stream=True)

    assert _cache_headers(plain) == {CACHE_HIT: 'true'}
    (choice,) = _body(plain)['choices']
    assert choice['finish_reason'] == 'tool_calls'
    assert [call['id'] for call in choice['message']['tool_calls']] == [
        upstream.WEATHER_TOOL_CALL['id']
    ]
    assert _cache_headers(stream) == {}


@pytest.mark.parametrize('stream_route', ['chat', 'guarded'])
def test_a_streamed_reply_with_text_and_a_tool_call_keeps_the_tool_call(
    gateway, stream_route
):
    """D17: text before a tool call does not make a streamed reply a text
    reply: a plain request served from it gets the tool call (live and
    buffered streams alike).
    """
    gateway.chat(
        [
            upstream.openai_stream(
                ['Let me check'],
                model='gpt-4o',
                tool_calls=[upstream.WEATHER_TOOL_CALL],
            )
        ],
        route=stream_route,
        stream=True,
    )
    plain = gateway.chat([], route=stream_route)

    assert _cache_headers(plain) == {CACHE_HIT: 'true'}
    (choice,) = _body(plain)['choices']
    assert choice['finish_reason'] == 'tool_calls'
    assert choice['message']['tool_calls']


def test_a_truncated_stream_keeps_its_finish_reason(gateway):
    gateway.chat(
        [
            upstream.openai_stream(
                ['Paris', ' is'], model='gpt-4o', finish_reason='length'
            )
        ],
        stream=True,
    )
    plain = gateway.chat([])

    assert _cache_headers(plain) == {CACHE_HIT: 'true'}
    assert _body(plain)['choices'][0]['finish_reason'] == 'length'


OUTPUT_WARN = {
    'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true',
    'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN': 'true',
}


def _stream_text(response) -> str:
    return ''.join(
        frame['choices'][0]['delta'].get('content') or ''
        for frame in _sse(response)
        if frame != '[DONE]' and frame['choices']
    )


def _entry_text(gateway, route: str) -> str:
    (raw,) = gateway.stored(route).values()
    return json.loads(raw)['choices'][0]['message']['content']


def test_a_buffered_stream_stores_its_screened_reply(gateway):
    """D9: the cache holds only text the output guardrails passed."""
    miss = gateway.chat([_stream(f'Mail {EMAIL}')], route='masked', stream=True)
    hit = gateway.chat([], route='masked', stream=True)

    assert _stream_text(miss) == _stream_text(hit) == 'Mail <EMAIL_ADDRESS>'
    assert _cache_headers(miss) == OUTPUT_WARN
    assert _entry_text(gateway, 'masked') == 'Mail <EMAIL_ADDRESS>'


def test_a_buffered_stream_hit_is_screened(gateway):
    """D9: a hit runs the output guardrails, as a model's reply does."""
    gateway.chat([_stream('Paris')], route='masked', stream=True)
    route = gateway.routes['proj/masked']
    (key,) = gateway.stored('masked')
    unscreened = _completion(f'Mail {EMAIL}').json_body
    _plant(route, key, json.dumps({**unscreened, 'model': 'gpt'}))

    hit = gateway.chat([], route='masked', stream=True)

    assert _stream_text(hit) == 'Mail <EMAIL_ADDRESS>'
    assert _cache_headers(hit) == {CACHE_HIT: 'true', **OUTPUT_WARN}


def test_a_soft_blocked_buffered_stream_hit_answers_400_as_a_miss_does(gateway):
    """D9: a hit the output guardrails soft-block answers the 400 a
    soft-blocked buffered reply answers.
    """
    miss = gateway.chat([_stream('softout')], route='blocked', stream=True)
    gateway.chat([_stream('Paris')], route='blocked', stream=True, text='Rome?')
    route = gateway.routes['proj/blocked']
    (key,) = gateway.stored('blocked')
    unscreened = _completion('softout').json_body
    _plant(route, key, json.dumps({**unscreened, 'model': 'gpt'}))

    hit = gateway.chat([], route='blocked', stream=True, text='Rome?')

    assert miss.status_code == hit.status_code == 400
    assert hit.json() == miss.json()
    soft_block = {
        'X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-TRIGGERED': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-WARN': 'true',
        'X-RB-AIGATEWAY-GUARDRAILS-OUTPUT-WARN': 'true',
    }
    assert _cache_headers(miss) == soft_block
    assert _cache_headers(hit) == {**soft_block, 'X-RB-AIGATEWAY-CACHE-HIT': 'true'}


@pytest.mark.parametrize('send', ['chat', 'responses'])
def test_the_semantic_cache_embedding_counts_on_the_callers_limits(gateway, send):
    """D15 (ADR 0006): the embedding call is charged to the request, as
    semantic routing's is. Its events stay flagged semantic.
    """
    # Both replies count 21 input tokens; the embedding of 'Hi' counts one.
    reply = (
        upstream.openai_completion('Paris', model='gpt-4o', prompt_tokens=21)
        if send == 'chat'
        else upstream.openai_response('Paris')
    )
    first = getattr(gateway, send)(
        [upstream.openai_embeddings(count=1), reply],
        route='semantic_limited',
        text='Hi',
    )

    assert first.status_code == 200
    assert gateway.model_events()[:2] == [
        ('MODEL_INVOCATION', 'e1', 'embeddings', 'semantic', 1.0),
        ('INPUT_TOKEN_PROCESSED', 'e1', 'embeddings', 'semantic', 1.0),
    ]
    # 21 + 1 tokens counted: the next request's one does not fit in 22.
    second = getattr(gateway, send)([], route='semantic_limited', text='Hi')
    assert second.status_code == 429


def test_a_transcription_hit_uses_none_of_the_audio_limit(gateway):
    """D10 follow-up: the audio limit is checked before the lookup, but its
    seconds are counted only when the model transcribes.
    """
    route = 'audio_two_seconds'
    first = gateway.transcribe([_transcription()], route=route)
    hit = gateway.transcribe([], route=route)
    # One second counted of two: another second of new audio still fits.
    other = gateway.transcribe(
        [_transcription('other')], route=route, audio=make_wav_bytes(1.0, 16000)
    )
    over = gateway.transcribe([], route=route)

    assert (first.status_code, hit.status_code, other.status_code) == (200,) * 3
    assert over.status_code == 429


def test_the_semantic_cache_embedding_is_charged_at_the_answering_models_price(
    gateway,
):
    """D15 follow-up: when a fallback answers the embedding call, the call is
    charged at the fallback's price, as its events price it.
    """
    first = gateway.chat(
        [upstream.error(500), upstream.openai_embeddings(count=1), _completion()],
        route='semantic_fallback',
        text='Hi',
    )

    assert first.status_code == 200
    assert ('INPUT_TOKEN_PROCESSED', 'e3', 'embeddings', 'semantic', 1.0) in (
        gateway.model_events()
    )
    # One token at a dollar: the 0.50 budget is spent.
    second = gateway.chat([], route='semantic_fallback', text='Hi')
    assert second.status_code == 429


def test_a_tool_call_reply_passes_the_output_guardrails(gateway):
    """A reply with no text, only a tool call, has nothing for the output
    guardrails to read: it is answered, not failed.
    """
    response = gateway.chat(
        [
            upstream.openai_completion(
                None, model='gpt-4o', tool_calls=[upstream.WEATHER_TOOL_CALL]
            )
        ],
        route='guarded',
    )

    assert response.status_code == 200
    assert _body(response)['choices'][0]['message']['tool_calls']


class _BrokenBackend:
    """A cache backend whose store is down."""

    def __init__(self, backend):
        self.cache_type = backend.cache_type

    async def get(self, *args, **kwargs):
        raise ConnectionError('cache down')

    async def set(self, *args, **kwargs):
        raise ConnectionError('cache down')


@pytest.mark.parametrize('stream', [False, True])
def test_a_cache_that_is_down_is_skipped(gateway, stream):
    """A failing cache backend costs the request its cache, not the reply:
    the lookup is a miss and the store is skipped.
    """
    route = gateway.routes['proj/chat']
    saved = route.cache
    route.cache = replace(route.cache, backend=_BrokenBackend(route.cache.backend))
    try:
        response = gateway.chat([_stream() if stream else _completion()], stream=stream)
    finally:
        route.cache = saved

    assert response.status_code == 200
    assert _cache_headers(response) == {}
