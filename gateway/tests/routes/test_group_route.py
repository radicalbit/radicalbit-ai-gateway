from unittest.mock import AsyncMock, MagicMock
import uuid

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
import pytest
from starlette.testclient import TestClient

from tests.common import db_mock

from radicalbit_ai_gateway.models.auth_dto import (
    GroupFullOut,
    GroupRouteOut,
    KeyFullOut,
)
from radicalbit_ai_gateway.models.credential_limiting import CredentialLimitCategory
from radicalbit_ai_gateway.models.group_limiting import (
    GroupLimitOutcome,
    GroupLimitResultOut,
    GroupLimitsApplyOut,
    GroupLimitsIn,
    GroupMemberLimitsOut,
)
from radicalbit_ai_gateway.models.limiting import LimitingAlgorithmType
from radicalbit_ai_gateway.routes.group_route import GroupRoute
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.utils.exceptions import (
    AuthRegistryError,
    ErrorOut,
    GroupHasNoCredentialsError,
    GroupInternalError,
    GroupNotFoundError,
    KeyNotFoundError,
    ProjectNotFoundError,
    RouteNotFoundError,
    auth_registry_exception_handler,
)

PREFIX = '/public/api/v1'
GROUP_UUID = db_mock.RANDOM_UUID
PROJECT_UUID = uuid.UUID('77777777-7777-7777-7777-777777777777')
PROJECT_ROUTES = f'{PREFIX}/groups/{GROUP_UUID}/projects/{PROJECT_UUID}'


@pytest.fixture
def group_service():
    return MagicMock(spec_set=GroupService)


@pytest.fixture
def project_service():
    service = MagicMock(spec_set=ProjectService)
    service.get_by_uuid.return_value = db_mock.get_sample_project_out(
        uuid=PROJECT_UUID, name='my-project'
    )
    return service


def _client(group_service, project_service) -> TestClient:
    app = FastAPI(title='AI Gateway', debug=True)
    app.add_exception_handler(AuthRegistryError, auth_registry_exception_handler)
    app.include_router(
        GroupRoute.get_group_router(group_service, project_service), prefix=PREFIX
    )
    return TestClient(app)


@pytest.fixture
def client(group_service, project_service):
    return _client(group_service, project_service)


def test_create_group(client, group_service):
    group_in = db_mock.get_sample_group_in()
    group_out = GroupFullOut.from_group(db_mock.get_sample_group())
    group_service.create_group.return_value = group_out

    res = client.post(f'{PREFIX}/groups', json=jsonable_encoder(group_in))

    assert res.status_code == 201
    assert res.json() == jsonable_encoder(group_out)
    group_service.create_group.assert_called_once_with(group_in)


def test_get_all(client, group_service):
    groups = [
        GroupFullOut.from_group(db_mock.get_sample_group(uuid=uuid.uuid4(), name=n))
        for n in ('one', 'two', 'three')
    ]
    group_service.get_all.return_value = groups

    res = client.get(f'{PREFIX}/groups')

    assert res.status_code == 200
    assert res.json() == jsonable_encoder(groups)
    group_service.get_all.assert_called_once()


def test_add_key(client, group_service):
    keys_uuid = [uuid.uuid4() for _ in range(3)]
    group = db_mock.get_sample_group(
        keys=[db_mock.get_sample_key(uuid=i) for i in keys_uuid]
    )
    key_uuids_in = db_mock.get_sample_keys_uuid_in(keys_uuid)
    group_out = GroupFullOut.from_group(group)
    group_service.add_keys.return_value = group_out

    res = client.patch(
        f'{PREFIX}/groups/{group.uuid}/keys', json=jsonable_encoder(key_uuids_in)
    )

    assert res.status_code == 201
    assert res.json() == jsonable_encoder(group_out)
    group_service.add_keys.assert_called_once_with(
        group.uuid, key_uuids_in, False, False
    )


def test_remove_key(client, group_service):
    key = db_mock.get_sample_key()
    group = db_mock.get_sample_group(keys=[key])
    group_out = GroupFullOut.from_group(group, False, True)
    group_service.remove_key = AsyncMock(return_value=group_out)

    res = client.delete(f'{PREFIX}/groups/{group.uuid}/keys/{key.uuid}')

    assert res.status_code == 200
    assert res.json() == jsonable_encoder(group_out)
    group_service.remove_key.assert_awaited_once_with(group.uuid, key.uuid)


def test_apply_limits_to_group(client, group_service):
    key_uuid = uuid.uuid4()
    body = {
        'limits': [
            {
                'category': 'request_rate',
                'algorithm': 'FIXED_WINDOW',
                'windowSize': '60 seconds',
                'value': 50,
            }
        ],
        'skip': [
            {
                'keyUuid': str(key_uuid),
                'category': 'request_rate',
                'algorithm': 'FIXED_WINDOW',
                'windowSize': '1 minute',
            }
        ],
    }
    group_service.apply_limits_to_group.return_value = GroupLimitsApplyOut(
        members=[
            GroupMemberLimitsOut(
                key_uuid=key_uuid,
                key_name='billing-service',
                expired=False,
                limits=[
                    GroupLimitResultOut(
                        category=CredentialLimitCategory.RATE,
                        algorithm=LimitingAlgorithmType.FIXED_WINDOW,
                        window_size='1 minute',
                        outcome=GroupLimitOutcome.SKIPPED,
                        previous_value=100,
                        new_value=50,
                    )
                ],
                warnings=[],
            )
        ]
    )

    res = client.post(f'{PREFIX}/groups/{GROUP_UUID}/limits', json=body)

    assert res.status_code == 201
    assert res.json() == {
        'members': [
            {
                'keyUuid': str(key_uuid),
                'keyName': 'billing-service',
                'expired': False,
                'limits': [
                    {
                        'category': 'request_rate',
                        'algorithm': 'FIXED_WINDOW',
                        'windowSize': '1 minute',
                        'outcome': 'skipped',
                        'previousValue': 100.0,
                        'newValue': 50.0,
                    }
                ],
                'warnings': [],
            }
        ]
    }
    group_service.apply_limits_to_group.assert_called_once_with(
        GROUP_UUID, GroupLimitsIn.model_validate(body), {}
    )


def test_a_group_has_no_limits_to_read_or_delete(group_service, project_service):
    # Builds its own router, so the router's construction runs inside a test
    client = _client(group_service, project_service)
    assert client.get(f'{PREFIX}/groups/{GROUP_UUID}/limits').status_code == 405
    res = client.delete(f'{PREFIX}/groups/{GROUP_UUID}/limits/{uuid.uuid4()}')
    assert res.status_code == 404


@pytest.mark.parametrize(
    ('query', 'group', 'include_routes'),
    [
        pytest.param('', db_mock.get_sample_group_plain(), False, id='default'),
        pytest.param(
            '?include_routes=true',
            db_mock.get_sample_group(
                uuid=GROUP_UUID,
                group_routes=[
                    db_mock.get_sample_group_route_plain(group_uuid=GROUP_UUID)
                ],
            ),
            True,
            id='include-routes',
        ),
    ],
)
def test_delete_group(client, group_service, query, group, include_routes):
    group_full_out = GroupFullOut.from_group(group, include_routes)
    group_service.delete_group.return_value = group_full_out

    res = client.delete(f'{PREFIX}/groups/{GROUP_UUID}{query}')

    assert res.status_code == 200
    assert res.json() == jsonable_encoder(group_full_out)
    group_service.delete_group.assert_called_once_with(
        GROUP_UUID, include_routes, False
    )


def test_get_group_by_uuid(client, group_service):
    group = db_mock.get_sample_group()
    group_out = GroupFullOut.from_group(group)
    group_service.get_group_by_uuid.return_value = group_out

    res = client.get(f'{PREFIX}/groups/{group.uuid}')

    assert res.status_code == 200
    assert res.json() == jsonable_encoder(group_out)
    group_service.get_group_by_uuid.assert_called_once_with(group.uuid, False, False)


def test_update_group_name(client, group_service):
    group = db_mock.get_sample_group()
    group_in = db_mock.get_sample_group_in()
    group_out = GroupFullOut.from_group(group)
    group_service.update_group_name.return_value = group_out

    res = client.patch(f'{PREFIX}/groups/{group.uuid}', json=jsonable_encoder(group_in))

    assert res.status_code == 200
    assert res.json() == jsonable_encoder(group_out)
    group_service.update_group_name.assert_called_once_with(group.uuid, group_in)


def test_get_associable_keys(client, group_service):
    keys_out = [
        KeyFullOut.from_key_obscured(db_mock.get_sample_key(uuid=uuid.uuid4(), name=n))
        for n in ('k1', 'k2')
    ]
    group_service.get_associable_keys.return_value = keys_out

    res = client.get(f'{PREFIX}/groups/{GROUP_UUID}/associable-keys')

    assert res.status_code == 200
    assert res.json() == jsonable_encoder(keys_out)
    group_service.get_associable_keys.assert_called_once_with(GROUP_UUID)


def test_add_project_route(client, group_service):
    group_route = db_mock.get_sample_group_route(
        route_name='my-route', project_uuid=PROJECT_UUID
    )
    group_out = GroupFullOut.from_group(
        db_mock.get_sample_group(uuid=GROUP_UUID, group_routes=[group_route]), True
    )
    group_routes_in = db_mock.get_sample_group_routes_in(['my-route'])
    group_service.add_project_routes.return_value = group_out

    res = client.patch(
        f'{PROJECT_ROUTES}/routes', json=jsonable_encoder(group_routes_in)
    )

    assert res.status_code == 201
    assert res.json() == jsonable_encoder(group_out)
    group_service.add_project_routes.assert_called_once_with(
        GROUP_UUID, PROJECT_UUID, 'my-project', group_routes_in, False, False
    )


def test_remove_project_route(client, group_service):
    group_out = GroupFullOut.from_group(db_mock.get_sample_group())
    group_service.remove_project_route.return_value = group_out

    res = client.delete(f'{PROJECT_ROUTES}/routes/my-route')

    assert res.status_code == 200
    assert res.json() == jsonable_encoder(group_out)
    group_service.remove_project_route.assert_called_once_with(
        GROUP_UUID, PROJECT_UUID, 'my-project', 'my-route'
    )


def test_get_associable_routes(client, group_service):
    routes_out = [
        GroupRouteOut(name=n, project_uuid=PROJECT_UUID, project_name='my-project')
        for n in ('route-A', 'route-B')
    ]
    group_service.get_associable_routes.return_value = routes_out

    res = client.get(f'{PROJECT_ROUTES}/associable-routes')

    assert res.status_code == 200
    assert res.json() == jsonable_encoder(routes_out)
    group_service.get_associable_routes.assert_called_once_with(
        GROUP_UUID, 'my-project'
    )


def test_associable_routes_of_an_unknown_project_are_not_looked_up(
    client, group_service, project_service
):
    project_service.get_by_uuid.side_effect = ProjectNotFoundError('error')

    res = client.get(f'{PROJECT_ROUTES}/associable-routes')

    assert res.status_code == 404
    assert (
        res.json()['error']
        == ErrorOut('error', 'auth_registry_error', code='project_not_found').error
    )
    group_service.get_associable_routes.assert_not_called()


KEY_UUID = uuid.UUID('88888888-8888-8888-8888-888888888888')

# (HTTP method, path, service method, body, raised error, status, error code).
# The handler is global: one row per endpoint, each error type at least once.
GROUP_ERRORS = [
    pytest.param(
        'POST',
        f'{PREFIX}/groups',
        'create_group',
        jsonable_encoder(db_mock.get_sample_group_in()),
        GroupInternalError('error'),
        500,
        'group_internal_error',
        id='create-internal-error',
    ),
    pytest.param(
        'PATCH',
        f'{PREFIX}/groups/{GROUP_UUID}/keys',
        'add_keys',
        jsonable_encoder(db_mock.get_sample_keys_uuid_in([KEY_UUID])),
        KeyNotFoundError('error'),
        404,
        'key_not_found',
        id='add-missing-key',
    ),
    pytest.param(
        'DELETE',
        f'{PREFIX}/groups/{GROUP_UUID}/keys/{KEY_UUID}',
        'remove_key',
        None,
        GroupNotFoundError('error'),
        404,
        'group_not_found',
        id='remove-key-missing-group',
    ),
    pytest.param(
        'POST',
        f'{PREFIX}/groups/{GROUP_UUID}/limits',
        'apply_limits_to_group',
        jsonable_encoder(db_mock.get_sample_group_limits_in()),
        GroupHasNoCredentialsError('error'),
        400,
        'group_has_no_credentials_bad_request',
        id='apply-limits-no-credentials',
    ),
    pytest.param(
        'DELETE',
        f'{PREFIX}/groups/{GROUP_UUID}',
        'delete_group',
        None,
        GroupInternalError('error'),
        500,
        'group_internal_error',
        id='delete-internal-error',
    ),
    pytest.param(
        'GET',
        f'{PREFIX}/groups/{GROUP_UUID}',
        'get_group_by_uuid',
        None,
        GroupNotFoundError('error'),
        404,
        'group_not_found',
        id='get-missing-group',
    ),
    pytest.param(
        'PATCH',
        f'{PREFIX}/groups/{GROUP_UUID}',
        'update_group_name',
        jsonable_encoder(db_mock.get_sample_group_in()),
        GroupNotFoundError('error'),
        404,
        'group_not_found',
        id='update-missing-group',
    ),
    pytest.param(
        'GET',
        f'{PREFIX}/groups/{GROUP_UUID}/associable-keys',
        'get_associable_keys',
        None,
        GroupNotFoundError('error'),
        404,
        'group_not_found',
        id='associable-keys-missing-group',
    ),
    pytest.param(
        'PATCH',
        f'{PROJECT_ROUTES}/routes',
        'add_project_routes',
        jsonable_encoder(db_mock.get_sample_group_routes_in(['nonexistent'])),
        RouteNotFoundError('error'),
        404,
        'route_not_found',
        id='add-missing-project-route',
    ),
    pytest.param(
        'DELETE',
        f'{PROJECT_ROUTES}/routes/my-route',
        'remove_project_route',
        None,
        RouteNotFoundError('error'),
        404,
        'route_not_found',
        id='remove-missing-project-route',
    ),
    pytest.param(
        'GET',
        f'{PROJECT_ROUTES}/associable-routes',
        'get_associable_routes',
        None,
        GroupNotFoundError('error'),
        404,
        'group_not_found',
        id='associable-routes-missing-group',
    ),
]


@pytest.mark.parametrize(
    ('method', 'path', 'service_method', 'body', 'error', 'status_code', 'code'),
    GROUP_ERRORS,
)
def test_a_service_error_becomes_its_auth_registry_error_response(
    client, group_service, method, path, service_method, body, error, status_code, code
):
    getattr(group_service, service_method).side_effect = error

    res = client.request(method, path, json=body)

    assert res.status_code == status_code
    assert (
        res.json()['error']
        == ErrorOut('error', 'auth_registry_error', code=code, param=None).error
    )
