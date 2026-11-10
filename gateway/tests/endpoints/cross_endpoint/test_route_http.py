"""What a route does on the HTTP path, on real routes with the providers faked
at the transport: which budget blocks a request first, the usage a
transcription stream counts, and what preprocessing plugins see and send.
"""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.common import db_mock
from tests.common.gateway_harness import LOGGER, build_routes, open_gateway
from tests.common.limits import consumed
from tests.common.provider_recorder import CannedResponse
from tests.endpoints.cross_endpoint.test_pipeline_golden import _completion

from radicalbit_ai_gateway import server
from radicalbit_ai_gateway.limiting.limits import Demand, RequestLimits, Usage
from radicalbit_ai_gateway.limiting.windows import Category
from radicalbit_ai_gateway.models.credential_limiting import (
    CredentialLimitCategory,
    CredentialLimitOut,
)
from radicalbit_ai_gateway.models.event_type import EventType
import radicalbit_ai_gateway.preprocessing as preprocessing_module
from radicalbit_ai_gateway.preprocessing import (
    PreprocessingPlugin,
    register_preprocessing_plugin,
)
from radicalbit_ai_gateway.server import app
from radicalbit_ai_gateway.utils import config_hooks

CREDENTIALS = {'api_key': 'sk-test'}
PROJECT = str(db_mock.RANDOM_UUID)
SPENT = 0  # A budget of 0 blocks every request.
BUDGET_SPENT = {'max_budget': SPENT, 'window_size': '1 minute'}

CONFIG = {
    'chat_models': [
        {
            'model_id': 'gpt',
            'model': 'openai/gpt-4o-mini',
            'credentials': CREDENTIALS,
            'input_cost_per_million_tokens': 1,
            'output_cost_per_million_tokens': 2,
        }
    ],
    'embedding_models': [
        {
            'model_id': 'emb',
            'model': 'openai/text-embedding-3-small',
            'credentials': CREDENTIALS,
            'input_cost_per_million_tokens': 0.25,
        }
    ],
    'routes': {
        'chat': {'chat_models': ['gpt']},
        'embed': {'embedding_models': ['emb']},
        'embed_spent': {'embedding_models': ['emb'], 'budget_limiting': BUDGET_SPENT},
    },
}


# Priced per audio token, text token and output token.
AUDIO_CONFIG = {
    'transcription_models': [
        {
            'model_id': 'transcribe',
            'model': 'openai/gpt-4o-transcribe',
            'credentials': CREDENTIALS,
            'input_cost_per_million_tokens': 2.5,
            'output_cost_per_million_tokens': 10.0,
            'input_cost_per_audio_token': 0.000006,
        }
    ],
    'routes': {
        'audio': {
            'transcription_models': ['transcribe'],
            'budget_limiting': {'max_budget': 10.0, 'window_size': '1 hour'},
        }
    },
}


@pytest.fixture
def gateway(caplog):
    with open_gateway(
        build_routes(CONFIG, project_uuid=PROJECT), caplog=caplog
    ) as gateway:
        yield gateway


def _spend_the_credential_budget(gateway) -> None:
    """Give the caller's credential a spent budget, as its key record holds it."""
    key = gateway.api_key
    limit = db_mock.get_sample_key_limit(
        category=CredentialLimitCategory.BUDGET.value,
        window_size='1 minute',
        max_value=SPENT,
    )
    server.key_service.get_key_by_hashed_key.return_value = SimpleNamespace(
        uuid=key.uuid,
        name=key.name,
        hashed_key=key.hashed_key,
        group=key.group,
        limits=[CredentialLimitOut.from_key_limit(limit)],
        expires_on=None,
    )


def _spend_the_project_budget():
    budget = db_mock.get_sample_project_budget_limit(
        window_size='1 minute', max_value=SPENT
    )
    return patch.object(
        server.project_budget_limit_dao, 'get_by_project_uuid', return_value=[budget]
    )


def _limit_logs(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == LOGGER and 'BUDGET LIMIT]' in r.getMessage()
    ]


@pytest.mark.parametrize(
    ('route', 'credential', 'project', 'reported'),
    [
        ('embed_spent', False, False, '[BUDGET LIMIT]'),
        # The credential's, then the project's, before the route's.
        ('embed_spent', True, False, '[CREDENTIAL BUDGET LIMIT]'),
        ('embed_spent', False, True, '[PROJECT BUDGET LIMIT]'),
        ('embed', True, True, '[CREDENTIAL BUDGET LIMIT]'),
        # A project budget blocks with no other limit configured.
        ('embed', False, True, '[PROJECT BUDGET LIMIT]'),
    ],
)
def test_the_first_spent_budget_blocks_an_embedding_request(
    gateway, caplog, route, credential, project, reported
):
    if credential:
        _spend_the_credential_budget(gateway)
    with _spend_the_project_budget() if project else nullcontext():
        response = gateway.embed([], route=route)

    assert response.status_code == 429
    assert gateway.upstream == []
    [log] = _limit_logs(caplog)
    assert log.startswith(reported)


def test_a_project_budget_blocks_a_chat_route_without_limits(gateway):
    """Regression: the limits were once checked only when a route or
    credential limit was configured: a project-only budget must still be.
    """
    assert app.state.routes['proj/chat'].route_limits.windows == ()

    with _spend_the_project_budget():
        response = gateway.chat([], text='What is the capital of France?')

    assert response.status_code == 429
    assert 'Project budget limit exceeded' in response.json()['error']['message']
    assert gateway.upstream == []
    # The block event names the caller and the route actually called.
    [event] = [
        e
        for e in gateway.event_rows
        if e['EVENT_TYPE'] is EventType.PROJECT_BUDGET_LIMIT
    ]
    assert (event['REQUEST_UUID'], event['API_KEY_UUID'], event['ROUTE_NAME']) == (
        str(db_mock.REQUEST_UUID),
        str(gateway.api_key.uuid),
        'chat',
    )


async def test_a_transcription_stream_counts_its_usage_once(gateway):
    """Usage comes on the final event only: the budget counts that one, not
    the deltas before it (``usage`` is ``None`` on them).
    """
    checks, counts = [], []
    check, count = RequestLimits.check, RequestLimits.count

    async def check_spy(limits, demand):
        checks.append(demand)
        return await check(limits, demand)

    async def count_spy(limits, usage):
        counts.append(usage)
        await count(limits, usage)

    usage = {
        'type': 'tokens',
        'input_tokens': 87,
        'output_tokens': 38,
        'total_tokens': 125,
        'input_token_details': {'audio_tokens': 82, 'text_tokens': 5},
    }
    stream = CannedResponse(
        sse_events=[
            {'type': 'transcript.text.delta', 'delta': 'hello'},
            {'type': 'transcript.text.done', 'text': 'hello', 'usage': usage},
        ]
    )
    app.state.routes = build_routes(AUDIO_CONFIG)
    with (
        patch.object(RequestLimits, 'check', check_spy),
        patch.object(RequestLimits, 'count', count_spy),
    ):
        response = gateway.transcribe([stream], stream=True)

    assert response.status_code == 200
    assert 'transcript.text.delta' in response.text
    # The request is admitted, then its budget and audio checked once.
    assert checks == [
        Demand(request=True),
        Demand(cost_room=True, audio_seconds=1.0),
    ]
    # Audio tokens, text tokens and output tokens, each at its price.
    assert counts == [Usage(costs=(492_000, 12_500, 380_000))]
    window = app.state.routes['proj/audio'].route_limits.window(Category.COST)
    assert await consumed(window) == 492_000 + 12_500 + 380_000


class _Uppercase(PreprocessingPlugin):
    """Records the messages it is given, then uppercases their text."""

    def __init__(self):
        self.seen: list[tuple[str, str]] = []

    async def preprocess(self, messages, config):
        self.seen.extend((type(m).__name__, m.content) for m in messages)
        for m in messages:
            if isinstance(m.content, str):
                m.content = m.content.upper()
        return messages


@pytest.fixture
def uppercase(gateway):
    """Serve a route whose model has a system prompt and whose plugin
    uppercases the client's messages.
    """
    plugin = _Uppercase()
    register_preprocessing_plugin(plugin, name='uppercase')
    try:
        app.state.routes = build_routes(
            {
                'chat_models': [
                    {
                        'model_id': 'm',
                        'model': 'openai/gpt-4o',
                        'credentials': CREDENTIALS,
                        'prompt': 'Route prompt.',
                    }
                ],
                'routes': {
                    'chat': {
                        'chat_models': ['m'],
                        'plugins': {'uppercase': {'enabled': True}},
                    }
                },
            }
        )
        yield plugin
    finally:
        preprocessing_module._registered.clear()
        config_hooks._plugins_validators.clear()
        config_hooks._known_plugin_keys.clear()


def test_preprocessing_runs_before_the_route_prompt_is_added(gateway, uppercase):
    """The plugin sees only the client's messages; the route's prompt is
    added afterwards, so no plugin can change it.
    """
    response = gateway.chat([_completion('hi')], text='hello')

    assert response.status_code == 200
    assert uppercase.seen == [('HumanMessage', 'hello')]
    [call] = gateway.upstream
    assert call['body']['messages'] == [
        {'role': 'system', 'content': 'Route prompt.'},
        {'role': 'user', 'content': 'HELLO'},
    ]


def test_preprocessing_sees_a_system_prompt_the_client_sends(gateway, uppercase):
    """Only the route's prompt is shielded from plugins: a system message the
    client sends is one of its messages.
    """
    response = gateway.post(
        '/v1/chat/completions',
        [_completion('hi')],
        json={
            'model': 'proj/chat',
            'messages': [
                {'role': 'system', 'content': 'client system'},
                {'role': 'user', 'content': 'hello'},
            ],
        },
    )

    assert response.status_code == 200
    assert uppercase.seen == [
        ('SystemMessage', 'client system'),
        ('HumanMessage', 'hello'),
    ]
    [call] = gateway.upstream
    assert call['body']['messages'] == [
        {'role': 'system', 'content': 'Route prompt.'},
        {'role': 'system', 'content': 'CLIENT SYSTEM'},
        {'role': 'user', 'content': 'HELLO'},
    ]
