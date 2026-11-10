"""What the HTTP handlers do that the golden scenarios leave open, on real
routes with the providers faked at the transport: validation errors, health,
transcription formats, the OpenAI SDK as a client, the tags header, and the
limits a live stream counts on.
"""

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient
from openai import AsyncOpenAI
import pytest
from starlette.datastructures import State

from tests.common import db_mock
from tests.common.gateway_harness import HEADERS, WAV, build_routes, open_gateway
from tests.common.limits import consumed, project_limit
from tests.common.provider_recorder import CannedResponse, ProviderRecorder
from tests.endpoints.test_pipeline_golden import CONFIG, _completion, _stream

from radicalbit_ai_gateway import server
from radicalbit_ai_gateway.limiting.limits import RequestLimits
from radicalbit_ai_gateway.limiting.windows import Category
from radicalbit_ai_gateway.models.event_payload import LimitScope
from radicalbit_ai_gateway.server import app, secret_service
from radicalbit_ai_gateway.utils.app_config import OtlpExporterConfig, TelemetryConfig
from radicalbit_ai_gateway.utils.exceptions import SecretsBackendError


@pytest.fixture
def gateway(caplog):
    with open_gateway(build_routes(CONFIG), caplog=caplog) as gateway:
        yield gateway


def _send(gateway, replies, path, **kwargs):
    """Post to the gateway; return the response and the provider requests."""
    with ProviderRecorder(replies) as recorder:
        response = gateway.client.post(path, **kwargs)
    assert recorder.unused == 0, 'a canned reply was not asked for'
    return response, recorder.requests


def _transcribe(gateway, replies, route='proj/audio', file=None, **data):
    return _send(
        gateway,
        replies,
        '/v1/audio/transcriptions',
        headers=HEADERS,
        data={'model': route, **data},
        files={'file': file or ('a.wav', WAV, 'audio/wav')},
    )


def test_health(gateway):
    response = gateway.client.get('/health')

    assert response.status_code == 200
    assert response.json() == {
        'status': 'ok',
        'service': 'Radicalbit AI Gateway',
        'version': '0.1.0',
        'gateway_initialized': True,
    }


def test_an_invalid_body_answers_422_and_echoes_it(gateway):
    response, upstream = _send(
        gateway,
        [],
        '/v1/chat/completions',
        headers=HEADERS,
        json={'model': 'proj/chat_metered'},
    )

    assert response.status_code == 422
    assert response.json()['body'] == '{"model":"proj/chat_metered"}'
    assert response.json()['detail']
    assert upstream == []


def test_an_unsupported_transcription_format_answers_422_without_a_body(gateway):
    response, upstream = _transcribe(gateway, [], response_format='text')

    assert response.status_code == 422
    assert response.json()['body'] == ''
    assert upstream == []


def test_verbose_json_on_a_model_other_than_whisper_is_refused_before_the_call(
    gateway,
):
    response, upstream = _transcribe(gateway, [], response_format='verbose_json')

    assert response.status_code == 400
    assert 'only supported for whisper-1' in response.json()['error']['message']
    assert upstream == []


def test_a_file_is_not_rejected_by_its_extension(gateway):
    response, [call] = _transcribe(
        gateway,
        [CannedResponse(json_body={'text': 'irrelevant'})],
        file=('a.txt', b'not-audio', 'text/plain'),
    )

    assert response.status_code == 200
    assert call['url'] == 'https://api.openai.com/v1/audio/transcriptions'
    assert 'filename="a.txt"' in call['body']


@pytest.mark.parametrize(
    ('route', 'stream'),
    [
        ('proj/nowhere', 'false'),
        ('proj/chat_metered', 'false'),
        ('proj/chat_metered', 'true'),
    ],
    ids=['unknown_route', 'no_transcription_models', 'stream_no_transcription_models'],
)
def test_a_transcription_a_route_cannot_serve_answers_400(gateway, route, stream):
    response, upstream = _transcribe(gateway, [], route=route, stream=stream)

    assert response.status_code == 400
    assert upstream == []


def test_the_tags_header_is_not_forwarded_upstream(gateway):
    response, [call] = _send(
        gateway,
        [_completion()],
        '/v1/chat/completions',
        headers={**HEADERS, 'X-RB-Tags': 'cost_center=retail,env=prod'},
        json={
            'model': 'proj/chat_metered',
            'messages': [{'role': 'user', 'content': 'Hello!'}],
        },
    )

    assert response.status_code == 200
    assert 'x-rb-tags' not in call['headers']
    assert 'cost_center' not in str(call)


async def test_a_live_stream_counts_its_cost_on_the_project_limits(gateway):
    """The handler returns before the stream body runs: the body still counts
    its usage on the request's limits, the project's included.
    """
    counted = []
    count = RequestLimits.count

    async def spy(limits, usage):
        counted.append(limits)
        await count(limits, usage)

    with (
        patch(
            'radicalbit_ai_gateway.endpoints.common.admission.load_project_limits',
            return_value=[project_limit(10)],
        ),
        patch.object(RequestLimits, 'count', spy),
    ):
        response, _ = _send(
            gateway,
            [_stream()],
            '/v1/chat/completions',
            headers=HEADERS,
            json={
                'model': 'proj/chat_metered',
                'messages': [{'role': 'user', 'content': 'Hi'}],
                'stream': True,
                'stream_options': {'include_usage': True},
            },
        )

    assert response.status_code == 200
    [limits] = counted
    [window] = limits._windows_of(LimitScope.PROJECT, Category.COST)
    assert await consumed(window) > 0


async def test_the_openai_sdk_reads_a_completion_and_a_stream(gateway):
    sdk = AsyncOpenAI(
        api_key=db_mock.PLAIN_KEY,
        base_url='http://gateway/v1',
        http_client=AsyncClient(
            transport=ASGITransport(app=app), base_url='http://gateway'
        ),
    )

    with ProviderRecorder([_completion('Hello World'), _stream('Hello', ' World')]):
        completion = await sdk.chat.completions.create(
            model='proj/chat_metered', messages=[{'role': 'user', 'content': 'Hi'}]
        )
        stream = await sdk.chat.completions.create(
            model='proj/chat_metered',
            messages=[{'role': 'user', 'content': 'Hi'}],
            stream=True,
        )
        chunks = [chunk async for chunk in stream]

    assert completion.choices[0].message.content == 'Hello World'
    assert ''.join(c.choices[0].delta.content or '' for c in chunks if c.choices) == (
        'Hello World'
    )


def test_an_unreachable_secrets_backend_answers_503(gateway):
    with patch.object(
        secret_service, 'get_secrets', side_effect=SecretsBackendError('refused')
    ):
        response = gateway.client.get('/public/api/v1/secrets')

    assert response.status_code == 503
    assert response.json()['error']['code'] == 'secrets_backend_unavailable'


def _project(name, served=True, config_file='routes: {}'):
    slot = SimpleNamespace(uuid=f'{name}-v1', config_file=config_file)
    return SimpleNamespace(
        uuid=name, name=name, served_config_uuid=slot.uuid if served else None,
        configs=[slot],
    )  # fmt: skip


async def test_startup_loads_served_projects_and_wires_every_trace_exporter(caplog):
    """A project without a served config, or whose config fails to load, is
    skipped; the others are loaded. Each exporter URL without a path gets
    ``/v1/traces``.
    """
    register = AsyncMock(side_effect=[None, RuntimeError('bad config')])
    traceloop = MagicMock()
    telemetry = TelemetryConfig(
        collector_base_url='http://collector:4318/',
        otlp_exporters=[
            OtlpExporterConfig(
                url='https://vendor/otel', api_key='k', headers={'x': 'y'}
            )
        ],
    )
    with ExitStack() as stack:
        # The startup resets the app's routes: put them back afterwards.
        stack.enter_context(patch.object(app, 'state', State(dict(app.state._state))))
        for target, attribute, value in [
            (server, 'database', MagicMock()),
            (server, 'ch_database', MagicMock()),
            (server, 'start_http_server', MagicMock(return_value=(MagicMock(), None))),
            (server, 'run_alert_window_scheduler', AsyncMock()),
            (server, 'build_project_route_registrar', lambda *_: (register, None)),
            (server, 'close_limit_storage', AsyncMock()),
            (server.httpx_aiohttp_client, 'aclose', AsyncMock()),
            (server.app_config, 'telemetry_config', telemetry),
            (server, 'Traceloop', traceloop),
            (server, 'BatchSpanProcessor', MagicMock()),
        ]:
            stack.enter_context(patch.object(target, attribute, value))
        exporter = stack.enter_context(patch.object(server, 'OTLPSpanExporter'))
        stack.enter_context(
            patch.object(
                server.project_service,
                'get_all_active',
                return_value=[
                    _project('a'),
                    _project('b', served=False),
                    _project('c'),
                ],
            )
        )
        async with server.lifespan(app):
            pass

    assert [c.args[:2] for c in register.call_args_list] == [('a', 'a'), ('c', 'c')]
    assert 'Skipping project b' in caplog.text
    assert 'Failed to load config for project c' in caplog.text
    assert [c.kwargs for c in exporter.call_args_list] == [
        {'endpoint': 'http://collector:4318/v1/traces'},
        {
            'endpoint': 'https://vendor/otel',
            'headers': {'x': 'y', 'Authorization': 'Bearer k'},
        },
    ]
    assert len(traceloop.init.call_args.kwargs['processor']) == 2


def test_a_live_stream_tags_the_rows_its_body_emits(gateway):
    """The handler returns before the stream body runs: the rows the body
    emits still carry the request's tags, as the request event does.
    """
    response = gateway.post(
        '/v1/chat/completions',
        [_stream()],
        headers={'X-RB-Tags': 'env=prod,app=x'},
        json={
            'model': 'proj/chat_metered',
            'messages': [{'role': 'user', 'content': 'Hi'}],
            'stream': True,
            'stream_options': {'include_usage': True},
        },
    )

    assert response.status_code == 200
    assert [(e['EVENT_TYPE'].name, e['TAGS']) for e in gateway.event_rows] == [
        ('MODEL_INVOCATION', ['app=x', 'env=prod']),
        ('INPUT_TOKEN_PROCESSED', ['app=x', 'env=prod']),
        ('OUTPUT_TOKEN_PROCESSED', ['app=x', 'env=prod']),
    ]
    [request_event] = gateway.request_events
    assert request_event.tags == ['app=x', 'env=prod']
