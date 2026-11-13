"""The SDK against the gateway's real routes and error handlers.

Every SDK operation is sent to the real app (``server.app``) in-process, with
the services mocked as in the route tests: the path, the method, the body and
the response model of each SDK method must fit the route it calls, and the
gateway's errors must reach the pipeline as the SDK's typed errors. What the
services do is covered by their own tests.
"""

import asyncio
import datetime
import inspect
from unittest.mock import AsyncMock, MagicMock
import uuid

from fastapi.testclient import TestClient
import httpx2
import pytest
from radicalbit_gateway import AsyncGateway, Gateway, errors

from tests.common import db_mock

from radicalbit_ai_gateway import server
from radicalbit_ai_gateway.models.auth_dto import GroupFullOut
from radicalbit_ai_gateway.sdk_spec import SDK_OPERATION_IDS
from radicalbit_ai_gateway.utils.exceptions import (
    KeyExternallyManagedError,
    KeyNotFoundError,
    KeyRotationConflictError,
    ProjectConfigStateError,
)

BASE_URL = 'http://testserver'
VALID_YAML = """\
chat_models:
  - model_id: mock-chat
    model: mock/gateway
routes:
  test-route:
    chat_models:
      - mock-chat
"""

_client = TestClient(server.app, raise_server_exceptions=False)


def _forward(request: httpx2.Request) -> httpx2.Response:
    """Send the SDK's request to the app, and its answer back to the SDK."""
    res = _client.request(
        request.method,
        str(request.url),
        headers=request.headers.multi_items(),
        content=request.read(),
    )
    return httpx2.Response(
        res.status_code, headers=res.headers.multi_items(), content=res.content
    )


@pytest.fixture
def gw():
    with Gateway(
        BASE_URL, transport=httpx2.MockTransport(_forward), max_retries=0
    ) as client:
        yield client


def _mock(monkeypatch, service, method: str, result=None, *, side_effect=None):
    """Replace one method of a service of the app; return the mock."""
    is_async = inspect.iscoroutinefunction(getattr(service, method))
    cls = AsyncMock if is_async else MagicMock
    mock = cls(return_value=result, side_effect=side_effect)
    monkeypatch.setattr(service, method, mock)
    return mock


KEY = db_mock.get_sample_key_full_out(uuid=uuid.uuid4(), api_key='sk-the-value')
GROUP = GroupFullOut.from_group(db_mock.get_sample_group(uuid=uuid.uuid4()))
PROJECT = db_mock.get_sample_project_out(uuid=uuid.uuid4())
SLOT_A = PROJECT.configs[0]

# One call per SDK operation: (operation id, service, method, result, call)
OPERATIONS = [
    ('credentials_create', 'key', 'create_key', KEY,
     lambda gw: gw.credentials.create(name='k')),
    ('credentials_list', 'key', 'get_all', [KEY],
     lambda gw: gw.credentials.list()),
    ('credentials_get', 'key', 'get_key_by_uuid', KEY,
     lambda gw: gw.credentials.get(KEY.uuid)),
    ('credentials_delete', 'key', 'delete_key', KEY,
     lambda gw: gw.credentials.delete(KEY.uuid)),
    ('credentials_rotate', 'key', 'rotate_key', KEY,
     lambda gw: gw.credentials.rotate(KEY.uuid, grace_period='1 hours')),
    ('credentials_end_grace_period', 'key', 'end_grace_period', KEY,
     lambda gw: gw.credentials.end_grace_period(KEY.uuid)),
    ('groups_create', 'group', 'create_group', GROUP,
     lambda gw: gw.groups.create(name='g')),
    ('groups_list', 'group', 'get_all', [GROUP],
     lambda gw: gw.groups.list()),
    ('groups_get', 'group', 'get_group_by_uuid', GROUP,
     lambda gw: gw.groups.get(GROUP.uuid)),
    ('groups_add_credentials', 'group', 'add_keys', GROUP,
     lambda gw: gw.groups.add_credentials(GROUP.uuid, keys=[KEY.uuid])),
    ('groups_remove_credential', 'group', 'remove_key', GROUP,
     lambda gw: gw.groups.remove_credential(GROUP.uuid, KEY.uuid)),
    ('groups_add_routes', 'group', 'add_project_routes', GROUP,
     lambda gw: gw.groups.add_routes(GROUP.uuid, PROJECT.uuid, routes=['r'])),
    ('groups_remove_route', 'group', 'remove_project_route', GROUP,
     lambda gw: gw.groups.remove_route(GROUP.uuid, PROJECT.uuid, 'r')),
    ('projects_create', 'project', 'create_project', PROJECT,
     lambda gw: gw.projects.create(name='p')),
    ('projects_list', 'project', 'get_all_filtered', [PROJECT],
     lambda gw: gw.projects.list()),
    ('projects_get', 'project', 'get_by_uuid', PROJECT,
     lambda gw: gw.projects.get(PROJECT.uuid)),
    ('configs_save', 'project', 'update_config', PROJECT,
     lambda gw: gw.configs.save(PROJECT.uuid, SLOT_A.uuid, config_file=VALID_YAML)),
    ('configs_upload', 'project', 'import_config', PROJECT,
     lambda gw: gw.configs.upload(
         PROJECT.uuid, SLOT_A.uuid, file=('c.yaml', VALID_YAML.encode()))),
    ('configs_approve', 'project', 'approve_config', PROJECT,
     lambda gw: gw.configs.approve(PROJECT.uuid, SLOT_A.uuid)),
    ('configs_cancel_approval', 'project', 'cancel_approval', PROJECT,
     lambda gw: gw.configs.cancel_approval(PROJECT.uuid, SLOT_A.uuid)),
    ('configs_serve', 'project', 'serve_config', PROJECT,
     lambda gw: gw.configs.serve(PROJECT.uuid, SLOT_A.uuid)),
    ('configs_unserve', 'project', 'unserve_config', PROJECT,
     lambda gw: gw.configs.unserve(PROJECT.uuid, SLOT_A.uuid)),
]  # fmt: skip

_SERVICES = {
    'key': server.key_service,
    'group': server.group_service,
    'project': server.project_service,
}


@pytest.fixture(autouse=True)
def _side_services(monkeypatch):
    """Mock what some routes call besides their own service method."""
    # The served projects' routes and configs, set by the app's lifespan (not
    # run here): serve and unserve deregister the project's from them
    monkeypatch.setattr(server.app.state, 'routes', {}, raising=False)
    monkeypatch.setattr(server.app.state, 'project_configs', {}, raising=False)
    _mock(monkeypatch, server.project_service, 'get_by_uuid', PROJECT)
    _mock(monkeypatch, server.group_service, 'cleanup_orphaned_associations', 0)


def test_every_sdk_operation_has_a_case():
    # configs_validate needs no service: it has tests of its own below
    assert {op for op, *_ in OPERATIONS} | {'configs_validate'} == set(
        SDK_OPERATION_IDS
    )


@pytest.mark.parametrize(
    ('service', 'method', 'result', 'call'),
    [pytest.param(*case[1:], id=case[0]) for case in OPERATIONS],
)
def test_the_sdk_operation_reaches_its_route(
    gw, monkeypatch, service, method, result, call
):
    mock = _mock(monkeypatch, _SERVICES[service], method, result)
    out = call(gw)
    assert mock.call_count == 1
    expected = result if isinstance(result, list) else [result]
    got = out if isinstance(out, list) else [out]
    assert [str(o.uuid) for o in got] == [str(r.uuid) for r in expected]


def test_the_request_bodies_reach_the_services(gw, monkeypatch):
    create = _mock(monkeypatch, server.key_service, 'create_key', KEY)
    rotate = _mock(monkeypatch, server.key_service, 'rotate_key', KEY)
    add = _mock(monkeypatch, server.group_service, 'add_keys', GROUP)
    upload = _mock(monkeypatch, server.project_service, 'import_config', PROJECT)

    created = gw.credentials.create(name='k', expires_on=datetime.date(2030, 1, 2))
    gw.credentials.rotate(KEY.uuid, grace_period=None)
    gw.groups.add_credentials(GROUP.uuid, keys=[KEY.uuid])
    gw.configs.upload(PROJECT.uuid, SLOT_A.uuid, file=('c.yaml', b'routes: {}'))

    assert created.api_key == 'sk-the-value'
    assert create.call_args.args[0].expires_on == datetime.date(2030, 1, 2)
    assert rotate.call_args.args[1].grace_period is None
    assert add.call_args.args[1].keys == [KEY.uuid]
    assert upload.call_args.args[2] == b'routes: {}'


# ── Errors ───────────────────────────────────────────────────────────────────


def test_validate_a_valid_config(gw):
    assert gw.configs.validate(config_file=VALID_YAML).valid is True


def test_validate_an_invalid_config_is_a_validation_error(gw):
    with pytest.raises(errors.ValidationError) as error:
        gw.configs.validate(config_file='routes:\n  r:\n    chat_models:\n      - x\n')
    assert error.value.status == 400
    assert error.value.details
    assert {'loc', 'msg', 'type'} <= set(error.value.details[0])


def test_an_invalid_request_body_is_a_validation_error(gw):
    with pytest.raises(errors.ValidationError) as error:
        gw.credentials.rotate(KEY.uuid, grace_period='forever')
    assert error.value.status == 422


def test_an_upload_that_is_not_yaml_is_a_validation_error(gw, monkeypatch):
    upload = _mock(monkeypatch, server.project_service, 'import_config', PROJECT)
    with pytest.raises(errors.ValidationError):
        gw.configs.upload(PROJECT.uuid, SLOT_A.uuid, file=('c.txt', b'routes: {}'))
    upload.assert_not_called()


@pytest.mark.parametrize(
    ('service', 'method', 'error', 'call', 'expected', 'code'),
    [
        pytest.param(
            'key', 'get_key_by_uuid', KeyNotFoundError('no key'),
            lambda gw: gw.credentials.get(KEY.uuid),
            errors.NotFoundError, 'key_not_found', id='not-found',
        ),
        pytest.param(
            'key', 'rotate_key', KeyRotationConflictError('grace period running'),
            lambda gw: gw.credentials.rotate(KEY.uuid, grace_period=None),
            errors.ConflictError, 'key_rotation_conflict', id='rotation-conflict',
        ),
        pytest.param(
            'key', 'delete_key', KeyExternallyManagedError('managed outside the gateway'),
            lambda gw: gw.credentials.delete(KEY.uuid),
            errors.ConflictError, 'key_externally_managed', id='externally-managed-credential',
        ),
        pytest.param(
            'project', 'serve_config',
            ProjectConfigStateError('not approved', 'config_not_approved'),
            lambda gw: gw.configs.serve(PROJECT.uuid, SLOT_A.uuid),
            errors.ConflictError, 'config_not_approved', id='serve-a-draft',
        ),
        pytest.param(
            'project', 'update_config',
            ProjectConfigStateError('served', 'config_served_not_editable'),
            lambda gw: gw.configs.save(PROJECT.uuid, SLOT_A.uuid, config_file='x'),
            errors.ConflictError, 'config_served_not_editable', id='save-served',
        ),
    ],
)  # fmt: skip
def test_gateway_errors_are_typed(
    gw, monkeypatch, service, method, error, call, expected, code
):
    _mock(monkeypatch, _SERVICES[service], method, side_effect=error)
    with pytest.raises(expected) as raised:
        call(gw)
    assert type(raised.value) is expected
    assert raised.value.code == code
    assert raised.value.message == error.client_message


def test_the_async_client_reaches_the_routes(monkeypatch):
    async def forward(request: httpx2.Request) -> httpx2.Response:
        await request.aread()
        return _forward(request)

    mock = _mock(monkeypatch, server.key_service, 'get_all', [KEY])

    async def call():
        async with AsyncGateway(
            BASE_URL, transport=httpx2.MockTransport(forward), max_retries=0
        ) as gw:
            return await gw.credentials.list()

    assert [k.uuid for k in asyncio.run(call())] == [KEY.uuid]
    mock.assert_called_once()
