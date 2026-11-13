"""The client's own behaviour: retries, network errors, options, the async twin,
and the models' tolerance of what newer gateways add.
"""

import asyncio
from collections.abc import Callable
import io
from uuid import uuid4

import httpx2
import pytest

from radicalbit_gateway import AsyncGateway, Gateway, _client, errors, models

URL = 'http://gateway.test'
KEY = {
    'uuid': str(uuid4()),
    'name': 'k',
    'apiKey': 'v',
    'hashedKey': 'h',
    'group': None,
    'metadata': None,
    'owner': 'o',
    'createdAt': 'now',
    'updatedAt': 'now',
}
Reply = httpx2.Response | Exception


@pytest.fixture
def waits(monkeypatch) -> list[float]:
    """The waits between attempts, recorded instead of slept."""
    recorded: list[float] = []
    monkeypatch.setattr(_client, '_sleep', recorded.append)

    async def record(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(_client, '_async_sleep', record)
    return recorded


def _replying(*replies: Reply, seen: list | None = None) -> Callable:
    """A transport handler answering with ``replies`` in order (an exception is raised)."""
    queue = list(replies)

    def handler(request: httpx2.Request) -> httpx2.Response:
        if seen is not None:
            seen.append(request)
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    return handler


def _gateway(*replies: Reply, seen: list | None = None, **kwargs) -> Gateway:
    return Gateway(
        URL, transport=httpx2.MockTransport(_replying(*replies, seen=seen)), **kwargs
    )


def _ok(body=None) -> httpx2.Response:
    return httpx2.Response(200, json=[] if body is None else body)


def _error(status: int, **headers: str) -> httpx2.Response:
    return httpx2.Response(
        status, json={'error': {'message': 'm', 'type': 't'}}, headers=headers
    )


# ── Retries ──────────────────────────────────────────────────────────────────


def test_a_read_is_retried_after_a_server_error(waits):
    seen: list = []
    gw = _gateway(_error(502), _error(500), _ok(), seen=seen)
    assert gw.keys.list() == []
    assert len(seen) == 3
    assert len(waits) == 2
    assert 0.375 <= waits[0] <= 0.5  # 0.5 s, with jitter
    assert 0.75 <= waits[1] <= 1.0  # doubled


def test_a_create_is_not_retried_after_a_server_error(waits):
    seen: list = []
    gw = _gateway(_error(500), seen=seen)
    with pytest.raises(errors.GatewayError) as error:
        gw.keys.create(name='k')
    assert error.value.status == 500
    assert len(seen) == 1
    assert waits == []


@pytest.mark.parametrize('status', [429, 503])
def test_a_create_refused_unprocessed_is_retried(waits, status):
    seen: list = []
    gw = _gateway(_error(status), _ok(KEY), seen=seen)
    assert gw.keys.create(name='k').name == 'k'
    assert len(seen) == 2


def test_retry_after_sets_the_wait(waits):
    gw = _gateway(
        _error(429, **{'Retry-After': '3'}),
        _error(429, **{'retry-after-ms': '1500'}),
        _ok(),
    )
    gw.keys.list()
    assert waits == [3.0, 1.5]


def test_a_retry_after_beyond_a_minute_falls_back_to_the_backoff(waits):
    gw = _gateway(_error(503, **{'Retry-After': '3600'}), _ok())
    gw.keys.list()
    assert waits[0] <= 0.5


def test_the_last_answer_is_raised_when_the_retries_run_out(waits):
    seen: list = []
    gw = _gateway(_error(503), _error(503), _error(503), seen=seen)
    with pytest.raises(errors.GatewayError) as error:
        gw.keys.list()
    assert error.value.status == 503
    assert len(seen) == 3  # 1 + max_retries (2)


def test_max_retries_zero_sends_once(waits):
    seen: list = []
    gw = _gateway(_error(503), seen=seen, max_retries=0)
    with pytest.raises(errors.GatewayError):
        gw.keys.list()
    assert len(seen) == 1


def test_a_client_error_is_not_retried(waits):
    seen: list = []
    gw = _gateway(_error(404), seen=seen)
    with pytest.raises(errors.NotFoundError):
        gw.keys.get(KEY['uuid'])
    assert len(seen) == 1


def test_an_upload_of_an_open_file_is_not_retried(waits):
    seen: list = []
    gw = _gateway(_error(503), seen=seen)
    with pytest.raises(errors.GatewayError):
        gw.configs.upload(uuid4(), uuid4(), file=io.BytesIO(b'routes: {}'))
    assert len(seen) == 1


def test_an_upload_of_bytes_is_retried(waits):
    seen: list = []
    gw = _gateway(_error(503), _error(404), seen=seen)
    with pytest.raises(errors.NotFoundError):
        gw.configs.upload(uuid4(), uuid4(), file=b'routes: {}')
    assert len(seen) == 2
    assert all(b'routes: {}' in r.read() for r in seen)  # sent again, whole


# ── Network errors ───────────────────────────────────────────────────────────


def test_a_refused_connection_is_retried_then_raised(waits):
    refused = httpx2.ConnectError('refused')
    gw = _gateway(refused, refused, refused)
    with pytest.raises(errors.APIConnectionError) as error:
        gw.keys.create(name='k')  # never sent: retried even for a create
    assert error.value.status is None
    assert isinstance(error.value.__cause__, httpx2.ConnectError)
    assert len(waits) == 2


def test_a_read_timeout_on_a_create_is_not_retried(waits):
    seen: list = []
    gw = _gateway(httpx2.ReadTimeout('slow'), seen=seen)
    with pytest.raises(errors.APITimeoutError):
        gw.keys.create(name='k')  # it may have been created
    assert len(seen) == 1


def test_a_read_timeout_on_a_read_is_retried(waits):
    gw = _gateway(httpx2.ReadTimeout('slow'), _ok())
    assert gw.keys.list() == []


def test_network_errors_are_gateway_errors():
    assert issubclass(errors.APITimeoutError, errors.APIConnectionError)
    assert issubclass(errors.APIConnectionError, errors.GatewayError)


# ── Options ──────────────────────────────────────────────────────────────────


def test_with_options_changes_only_the_copy(waits):
    seen: list = []
    gw = _gateway(_error(503), _error(503), seen=seen, headers={'X-Team': 'ml'})
    impatient = gw.with_options(max_retries=0, headers={'X-Run': '1'})
    with pytest.raises(errors.GatewayError):
        impatient.keys.list()
    assert len(seen) == 1
    assert seen[0].headers['X-Team'] == 'ml'
    assert seen[0].headers['X-Run'] == '1'
    assert gw._max_retries == 2
    assert gw._headers == {}


def test_with_options_sets_the_timeout_of_its_calls():
    seen: list = []
    gw = _gateway(_ok(), _ok(), seen=seen)
    gw.with_options(timeout=120).keys.list()
    gw.keys.list()
    assert seen[0].extensions['timeout']['read'] == 120
    assert seen[1].extensions['timeout']['read'] == 30


def test_the_user_agent_names_the_sdk_and_its_version():
    seen: list = []
    _gateway(_ok(), seen=seen).keys.list()
    assert seen[0].headers['User-Agent'].startswith('radicalbit-gateway-python/')


def test_the_url_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv('RADICALBIT_GATEWAY_BASE_URL', 'http://from-env.test/')
    seen: list = []
    gw = Gateway(transport=httpx2.MockTransport(_replying(_ok(), seen=seen)))
    gw.keys.list()
    assert str(seen[0].url).startswith('http://from-env.test/public/api/v1/')


def test_no_url_at_all_is_an_error(monkeypatch):
    monkeypatch.delenv('RADICALBIT_GATEWAY_BASE_URL', raising=False)
    with pytest.raises(ValueError, match='RADICALBIT_GATEWAY_BASE_URL'):
        Gateway()


def test_an_id_can_be_a_string():
    seen: list = []
    _gateway(_ok(KEY), seen=seen).keys.get(KEY['uuid'])
    assert seen[0].url.path == f'/public/api/v1/keys/{KEY["uuid"]}'


# ── Async ────────────────────────────────────────────────────────────────────


def test_the_async_client_calls_and_retries(waits):
    seen: list = []
    transport = httpx2.MockTransport(_replying(_error(503), _ok(KEY), seen=seen))

    async def call() -> models.KeyFullOut:
        async with AsyncGateway(URL, transport=transport) as gw:
            return await gw.keys.get(KEY['uuid'])

    assert asyncio.run(call()).name == 'k'
    assert len(seen) == 2
    assert len(waits) == 1


def test_the_async_client_raises_typed_errors():
    transport = httpx2.MockTransport(_replying(_error(409)))

    async def call() -> None:
        async with AsyncGateway(URL, transport=transport) as gw:
            await gw.keys.create(name='k')

    with pytest.raises(errors.ConflictError):
        asyncio.run(call())


# ── What newer gateways add ──────────────────────────────────────────────────


def test_an_unknown_value_comes_through():
    key = models.KeyFullOut.model_validate({**KEY, 'state': 'suspended'})
    assert key.state == 'suspended'


def test_an_unknown_field_is_kept():
    key = models.KeyFullOut.model_validate({**KEY, 'newField': 1})
    assert key.model_extra == {'newField': 1}


def test_a_wrong_type_still_raises():
    with pytest.raises(ValueError):
        models.KeyFullOut.model_validate({**KEY, 'createdAt': 3})


def test_a_delete_is_not_retried_after_a_lost_answer(waits):
    seen: list = []
    gw = _gateway(httpx2.ReadTimeout('slow'), seen=seen)
    with pytest.raises(errors.APITimeoutError):
        gw.keys.delete(KEY['uuid'])  # a retry would answer 404 if it went through
    assert len(seen) == 1
