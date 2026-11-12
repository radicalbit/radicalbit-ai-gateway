from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import uuid

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
import pytest
from starlette.testclient import TestClient

from tests.common import db_mock
from tests.common.sse import first_events

from radicalbit_ai_gateway.models.config_slot import Slot
from radicalbit_ai_gateway.models.config_status import ConfigStatus
from radicalbit_ai_gateway.models.event_dto import WindowProgressBarDTO
from radicalbit_ai_gateway.models.project_budget_limiting import (
    ProjectBudgetLimitConflictsOut,
    ProjectBudgetLimitDraftConflictOut,
    ProjectBudgetLimitOut,
    ProjectBudgetLimitUpdatedOut,
    ProjectBudgetLimitValueIn,
)
from radicalbit_ai_gateway.models.project_dto import ProjectFilter
from radicalbit_ai_gateway.routes.project_route import ProjectRoute, ProjectRouteConfig
from radicalbit_ai_gateway.services.config_generator_service import (
    ConfigGeneratorService,
)
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.utils.exceptions import (
    AuthRegistryError,
    ProjectAlreadyExistsError,
    ProjectBudgetLimitAlreadyExistsError,
    ProjectBudgetLimitConflictError,
    ProjectBudgetLimitNotFoundError,
    ProjectConfigValidationError,
    ProjectNotFoundError,
    auth_registry_exception_handler,
)

_VALID = db_mock.VALID_CONFIG_YAML
PREFIX = '/public/api/v1'
PID = uuid.UUID('55555555-5555-5555-5555-555555555555')
CID = uuid.UUID('66666666-6666-6666-6666-666666666666')
LID = uuid.UUID('99999999-9999-9999-9999-999999999999')
PROJECT = f'{PREFIX}/projects/{PID}'
CONFIG = f'{PROJECT}/configs/{CID}'
YAML_FILE = {'file': ('c.yaml', b'yaml-bytes', 'application/x-yaml')}


@pytest.fixture
def deps():
    """Mock every collaborator of the router."""
    return SimpleNamespace(
        project_service=MagicMock(spec_set=ProjectService),
        group_service=MagicMock(spec_set=GroupService),
        config_generator_service=MagicMock(spec_set=ConfigGeneratorService),
        register=AsyncMock(),
        deregister=AsyncMock(),
    )


@pytest.fixture
def project_service(deps):
    return deps.project_service


def _app(deps, config: ProjectRouteConfig | None = None) -> FastAPI:
    router = ProjectRoute.get_project_router(
        deps.project_service,
        deps.group_service,
        register_project_routes=deps.register,
        deregister_project_routes=deps.deregister,
        config=config,
        config_generator_service=deps.config_generator_service,
    )
    app = FastAPI(title='AI Gateway', debug=True)
    app.add_exception_handler(AuthRegistryError, auth_registry_exception_handler)
    app.include_router(router, prefix=PREFIX)
    return app


def _client(deps) -> TestClient:
    return TestClient(_app(deps))


@pytest.fixture
def client(deps):
    return _client(deps)


def _limit_out(**kwargs):
    return ProjectBudgetLimitOut.from_project_budget_limit(
        db_mock.get_sample_project_budget_limit(
            uuid=kwargs.pop('uuid', uuid.uuid4()), project_uuid=PID, **kwargs
        )
    )


# --- create / list / get ---


def test_create_project(client, project_service):
    project_in = db_mock.get_sample_project_in()
    out = db_mock.get_sample_project_out()
    project_service.create_project.return_value = out

    res = client.post(f'{PREFIX}/projects', json=jsonable_encoder(project_in))

    assert res.status_code == 201
    assert res.json() == jsonable_encoder(out)
    project_service.create_project.assert_called_once_with(project_in)


@pytest.mark.parametrize(
    ('params', 'args'),
    [
        pytest.param({'filter': 'prod'}, (ProjectFilter.PROD, False), id='filter'),
        pytest.param({'include_limits': 'true'}, (None, True), id='include-limits'),
    ],
)
def test_get_all(client, project_service, params, args):
    project_service.get_all_filtered.return_value = [db_mock.get_sample_project_out()]

    res = client.get(f'{PREFIX}/projects', params=params)

    assert res.status_code == 200
    project_service.get_all_filtered.assert_called_once_with(*args)


@pytest.mark.parametrize(
    ('params', 'include_limits'),
    [
        pytest.param({}, False, id='default'),
        pytest.param({'include_limits': 'true'}, True, id='include-limits'),
    ],
)
def test_get_by_uuid(client, project_service, params, include_limits):
    limits = [_limit_out()] if include_limits else []
    project_service.get_by_uuid.return_value = db_mock.get_sample_project_out(
        uuid=PID, limits=limits
    )

    res = client.get(PROJECT, params=params)

    assert res.status_code == 200
    if include_limits:
        assert res.json()['limits'] == jsonable_encoder(limits)
    project_service.get_by_uuid.assert_called_once_with(PID, include_limits)


# --- config mutations ---


def test_update_config(client, project_service):
    project_service.update_config.return_value = db_mock.get_sample_project_out(
        uuid=PID
    )

    res = client.patch(CONFIG, json={'configFile': _VALID})

    assert res.status_code == 200
    args = project_service.update_config.call_args.args
    assert args[0] == PID and args[1] == CID
    assert args[2].config_file == _VALID


@pytest.mark.parametrize(
    ('path', 'service_method', 'args'),
    [
        pytest.param(f'{CONFIG}/export', 'export_config', (PID, CID), id='one'),
        pytest.param(
            f'{PROJECT}/configs/export', 'export_all_configs', (PID,), id='all'
        ),
    ],
)
def test_export_returns_a_zip(client, project_service, path, service_method, args):
    getattr(project_service, service_method).return_value = (
        b'zip-bytes',
        'proj_config.zip',
    )

    res = client.get(path)

    assert res.status_code == 200
    assert res.headers['content-type'] == 'application/zip'
    assert (
        res.headers['content-disposition'] == 'attachment; filename="proj_config.zip"'
    )
    assert res.content == b'zip-bytes'
    getattr(project_service, service_method).assert_called_once_with(*args)


def test_import_config_returns_project(client, project_service):
    project_service.import_config.return_value = db_mock.get_sample_project_out(
        uuid=PID
    )

    res = client.patch(f'{CONFIG}/import', files=YAML_FILE)

    assert res.status_code == 200
    project_service.import_config.assert_called_once_with(PID, CID, b'yaml-bytes')


def test_import_config_missing_file_returns_422(client):
    assert client.patch(f'{CONFIG}/import').status_code == 422


@pytest.mark.parametrize(
    'file',
    [
        pytest.param(('c.json', b'{}', 'application/json'), id='wrong-extension'),
        pytest.param(
            ('c.yaml', b'x' * (2 * 1024 * 1024 + 1), 'application/x-yaml'),
            id='too-large',
        ),
    ],
)
def test_import_config_rejects_the_file_before_the_service(
    client, project_service, file
):
    res = client.patch(f'{CONFIG}/import', files={'file': file})

    assert res.status_code == 400
    project_service.import_config.assert_not_called()


@pytest.mark.parametrize(
    ('suffix', 'service_method'),
    [
        pytest.param('approve', 'approve_config', id='approve'),
        pytest.param('cancel-approval', 'cancel_approval', id='cancel-approval'),
    ],
)
def test_approval_transitions(client, project_service, suffix, service_method):
    getattr(
        project_service, service_method
    ).return_value = db_mock.get_sample_project_out(uuid=PID)

    res = client.patch(f'{CONFIG}/{suffix}')

    assert res.status_code == 200
    getattr(project_service, service_method).assert_called_once_with(PID, CID)


def test_serve_config_swaps_the_served_routes_and_cleans_up_orphans(client, deps):
    served = db_mock.get_sample_config_slot_out(
        uuid=CID, slot=Slot.A, config_file=_VALID, config_status=ConfigStatus.SERVED
    )
    other = db_mock.get_sample_config_slot_out(uuid=uuid.uuid4(), slot=Slot.B)
    out = db_mock.get_sample_project_out(
        uuid=PID, served_config_uuid=CID, configs=[served, other]
    )
    deps.project_service.serve_config.return_value = out
    deps.group_service.cleanup_orphaned_associations.return_value = 2

    res = client.patch(f'{CONFIG}/serve')

    assert res.status_code == 200
    deps.project_service.serve_config.assert_called_once_with(PID, CID)
    deps.deregister.assert_awaited_once_with(PID)
    deps.register.assert_awaited_once_with(PID, out.name, _VALID)
    deps.group_service.cleanup_orphaned_associations.assert_called_once_with(
        PID, out.name
    )


def test_unserve_config_deregisters(client, deps):
    deps.project_service.unserve_config.return_value = db_mock.get_sample_project_out(
        uuid=PID
    )

    res = client.patch(f'{CONFIG}/unserve')

    assert res.status_code == 200
    deps.project_service.unserve_config.assert_called_once_with(PID, CID)
    deps.deregister.assert_awaited_once_with(PID)


def test_generate_config(client, deps):
    deps.project_service.get_config.return_value = db_mock.get_sample_config_slot_out(
        uuid=CID, config_file='# x'
    )
    deps.config_generator_service.generate_config = AsyncMock(
        return_value='# generated'
    )

    res = client.post(f'{CONFIG}/generate-config', json={'description': 'make it'})

    assert res.status_code == 200
    assert res.json()['configFile'] == '# generated'
    deps.project_service.get_config.assert_called_once_with(PID, CID)


def test_generate_config_rejected_when_served(client, deps):
    deps.project_service.get_config.return_value = db_mock.get_sample_config_slot_out(
        uuid=CID, config_file='# x', config_status=ConfigStatus.SERVED
    )
    deps.config_generator_service.generate_config = AsyncMock(
        return_value='# generated'
    )

    res = client.post(f'{CONFIG}/generate-config', json={'description': 'make it'})

    assert res.status_code == 400
    deps.config_generator_service.generate_config.assert_not_awaited()


@pytest.mark.parametrize(
    ('served_config_uuid', 'deregistered'),
    [
        pytest.param(uuid.uuid4(), True, id='served'),
        pytest.param(None, False, id='dev'),
    ],
)
def test_delete_project_deregisters_only_when_served(
    client, deps, served_config_uuid, deregistered
):
    deps.project_service.delete_project = AsyncMock(
        return_value=db_mock.get_sample_project_out(
            uuid=PID, served_config_uuid=served_config_uuid
        )
    )

    res = client.delete(PROJECT)

    assert res.status_code == 200
    deps.project_service.delete_project.assert_called_once_with(PID)
    assert deps.deregister.await_count == int(deregistered)
    if deregistered:
        deps.deregister.assert_awaited_once_with(PID)


# --- project budget limits ---


def test_add_budget_limits_to_project(client, project_service):
    limits_in = db_mock.get_sample_project_budget_limits_in()
    limit_out = _limit_out()
    project_service.add_budget_limits_to_project.return_value = [limit_out]

    res = client.post(f'{PROJECT}/budget-limits', json=jsonable_encoder(limits_in))

    assert res.status_code == 201
    assert res.json() == jsonable_encoder([limit_out])
    project_service.add_budget_limits_to_project.assert_called_once_with(PID, limits_in)


def test_add_budget_limits_conflict_names_the_routes(client, project_service):
    project_service.add_budget_limits_to_project.side_effect = (
        ProjectBudgetLimitConflictError('conflict', routes=['chat', 'search'])
    )

    res = client.post(
        f'{PROJECT}/budget-limits',
        json=jsonable_encoder(db_mock.get_sample_project_budget_limits_in()),
    )

    assert res.status_code == 400
    assert res.json()['error']['routes'] == ['chat', 'search']


def test_get_budget_limit_conflicts(client, project_service):
    config_uuid = uuid.uuid4()
    project_service.get_budget_limit_conflicts.return_value = (
        ProjectBudgetLimitConflictsOut(
            published=['chat'],
            draft=['chat', 'search'],
            budget_routing=['chat'],
            draft_configs=[
                ProjectBudgetLimitDraftConflictOut(
                    config_uuid=config_uuid, slot='B', routes=['chat', 'search']
                )
            ],
        )
    )

    res = client.get(f'{PROJECT}/budget-limits/conflicts')

    assert res.status_code == 200
    assert res.json() == {
        'published': ['chat'],
        'draft': ['chat', 'search'],
        'budgetRouting': ['chat'],
        'draftConfigs': [
            {'configUuid': str(config_uuid), 'slot': 'B', 'routes': ['chat', 'search']}
        ],
    }
    project_service.get_budget_limit_conflicts.assert_called_once_with(PID)


def test_get_budget_limits_for_project(client, project_service):
    limit_out = _limit_out()
    project_service.get_budget_limits_for_project.return_value = [limit_out]

    res = client.get(f'{PROJECT}/budget-limits')

    assert res.status_code == 200
    assert res.json() == jsonable_encoder([limit_out])
    project_service.get_budget_limits_for_project.assert_called_once_with(PID)


def test_delete_budget_limit_from_project(client, project_service):
    limit_out = _limit_out(uuid=LID)
    project_service.delete_budget_limit_from_project = AsyncMock(return_value=limit_out)

    res = client.delete(f'{PROJECT}/budget-limits/{LID}')

    assert res.status_code == 200
    assert res.json() == jsonable_encoder(limit_out)
    project_service.delete_budget_limit_from_project.assert_called_once_with(PID, LID)


def test_update_budget_limit_value_returns_the_limit_with_its_previous_max(
    client, project_service
):
    updated = ProjectBudgetLimitUpdatedOut(
        **_limit_out(uuid=LID, max_value=40.0).model_dump(), previous_value=10.0
    )
    project_service.update_budget_limit_value.return_value = updated

    res = client.patch(f'{PROJECT}/budget-limits/{LID}', json={'value': 40})

    assert res.status_code == 200
    assert res.json()['value'] == 40.0
    assert res.json()['previousValue'] == 10.0
    project_service.update_budget_limit_value.assert_called_once_with(
        PID, LID, ProjectBudgetLimitValueIn(value=40)
    )


@pytest.mark.parametrize(
    ('body', 'loc'),
    [
        pytest.param({'value': -1}, None, id='max-not-above-zero'),
        pytest.param(
            {'value': 5, 'windowSize': '1 day'},
            ['body', 'windowSize'],
            id='field-other-than-the-max',
        ),
    ],
)
def test_update_budget_limit_value_rejects_an_invalid_body(
    client, project_service, body, loc
):
    res = client.patch(f'{PROJECT}/budget-limits/{LID}', json=body)

    assert res.status_code == 422
    if loc:
        assert res.json()['detail'][0]['loc'] == loc
    project_service.update_budget_limit_value.assert_not_called()


# (HTTP method, path, service method, request kwargs, raised error, status).
# The handler is global: one row per endpoint, each error type at least once.
PROJECT_ERRORS = [
    pytest.param(
        'POST',
        f'{PREFIX}/projects',
        'create_project',
        {'json': jsonable_encoder(db_mock.get_sample_project_in())},
        ProjectAlreadyExistsError('error'),
        400,
        id='create-already-exists',
    ),
    pytest.param(
        'GET',
        PROJECT,
        'get_by_uuid',
        {},
        ProjectNotFoundError('nope'),
        404,
        id='get-missing-project',
    ),
    pytest.param(
        'PATCH',
        CONFIG,
        'update_config',
        {'json': {'configFile': _VALID}},
        ProjectConfigValidationError('served read-only'),
        400,
        id='update-config-invalid',
    ),
    pytest.param(
        'GET',
        f'{CONFIG}/export',
        'export_config',
        {},
        ProjectNotFoundError('nope'),
        404,
        id='export-missing-project',
    ),
    pytest.param(
        'GET',
        f'{PROJECT}/configs/export',
        'export_all_configs',
        {},
        ProjectConfigValidationError('empty'),
        400,
        id='export-all-empty',
    ),
    pytest.param(
        'PATCH',
        f'{CONFIG}/import',
        'import_config',
        {'files': YAML_FILE},
        ProjectNotFoundError('nope'),
        404,
        id='import-missing-project',
    ),
    pytest.param(
        'POST',
        f'{PROJECT}/budget-limits',
        'add_budget_limits_to_project',
        {'json': jsonable_encoder(db_mock.get_sample_project_budget_limits_in())},
        ProjectBudgetLimitAlreadyExistsError('dup'),
        400,
        id='add-budget-limit-already-exists',
    ),
    pytest.param(
        'GET',
        f'{PROJECT}/budget-limits',
        'get_budget_limits_for_project',
        {},
        ProjectNotFoundError('nope'),
        404,
        id='get-budget-limits-missing-project',
    ),
    pytest.param(
        'DELETE',
        f'{PROJECT}/budget-limits/{LID}',
        'delete_budget_limit_from_project',
        {},
        ProjectBudgetLimitNotFoundError('nope'),
        404,
        id='delete-missing-budget-limit',
    ),
    pytest.param(
        'PATCH',
        f'{PROJECT}/budget-limits/{LID}',
        'update_budget_limit_value',
        {'json': {'value': 5}},
        ProjectBudgetLimitNotFoundError('nope'),
        404,
        id='update-missing-budget-limit',
    ),
]


@pytest.mark.parametrize(
    ('method', 'path', 'service_method', 'request_kwargs', 'error', 'status_code'),
    PROJECT_ERRORS,
)
def test_a_service_error_becomes_its_error_response(
    client,
    project_service,
    method,
    path,
    service_method,
    request_kwargs,
    error,
    status_code,
):
    getattr(project_service, service_method).side_effect = error

    res = client.request(method, path, **request_kwargs)

    assert res.status_code == status_code
    assert res.json()['error']['code'] == error.code


# --- route_meta ---


def _get_endpoint(app, path_suffix: str, method: str = 'PATCH') -> object:
    """Return the endpoint function for a given path suffix and method."""

    def _find_route(routes):
        for route in routes:
            if hasattr(route, 'original_router') and hasattr(
                route.original_router, 'routes'
            ):
                found = _find_route(route.original_router.routes)
                if found:
                    return found
            if hasattr(route, 'routes'):
                found = _find_route(route.routes)
                if found:
                    return found
            if hasattr(route, 'path') and route.path.endswith(path_suffix):
                if method.upper() in getattr(route, 'methods', set()):
                    return route.endpoint
        return None

    endpoint = _find_route(app.routes)
    if endpoint is not None:
        return endpoint
    msg = f'No route found for {method} ...{path_suffix}'
    raise AssertionError(msg)


def test_update_budget_limit_value_is_audited_on_the_project(client):
    endpoint = _get_endpoint(client.app, 'budget-limits/{limit_uuid}', 'PATCH')

    assert endpoint._route_meta == {
        'entity_type': 'PROJECT',
        'entity_uuid_param': 'project_uuid',
    }


def test_config_mutation_routes_have_entity_uuid_param(deps):
    # Builds its own router, so the router's construction runs inside a test
    client = _client(deps)
    config_routes = [
        ('configs/{config_uuid}', 'PATCH'),
        ('configs/{config_uuid}/approve', 'PATCH'),
        ('configs/{config_uuid}/cancel-approval', 'PATCH'),
        ('configs/{config_uuid}/serve', 'PATCH'),
        ('configs/{config_uuid}/unserve', 'PATCH'),
        ('configs/{config_uuid}/generate-config', 'POST'),
    ]
    for path_suffix, method in config_routes:
        endpoint = _get_endpoint(client.app, path_suffix, method)
        meta = getattr(endpoint, '_route_meta', None)
        assert meta is not None, f'{path_suffix} missing _route_meta'
        assert meta.get('entity_uuid_param') == 'project_uuid', (
            f'{path_suffix} missing entity_uuid_param'
        )


BAR = WindowProgressBarDTO(
    window_length=86400,
    window_start_time=1_700_000_000,
    window_end_time=1_700_086_400,
    window_size=40.0,
    window_filled_size=38.0,
    window_filled_percentage=95.0,
)
BAR_JSON = {
    'windowLength': 86400,
    'windowStartTime': 1_700_000_000,
    'windowEndTime': 1_700_086_400,
    'windowSize': 40.0,
    'windowFilledSize': 38.0,
    'windowFilledPercentage': 95.0,
    'windowStatus': 'critical',
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('requested', 'readable'),
    [
        pytest.param(['member', 'other'], ['member'], id='the_filter_keeps_members'),
        pytest.param([], [], id='no_projects'),
    ],
)
async def test_budget_limits_stream_sends_the_readable_projects_consumption(
    deps, requested, readable
):
    uuids = {'member': uuid.uuid4(), 'other': uuid.uuid4()}
    deps.project_service.get_budget_limits_consumption = AsyncMock(
        return_value={str(LID): BAR}
    )
    app = _app(
        deps,
        ProjectRouteConfig(
            filter_project_uuids_fn=lambda _request, ids: [
                u for u in ids if u == uuids['member']
            ]
        ),
    )

    [event] = await first_events(
        app,
        f'{PREFIX}/projects/budget-limits/stream',
        sleep='radicalbit_ai_gateway.routes.project_route.asyncio.sleep',
        interval=10,
        params={'projects': [str(uuids[name]) for name in requested]},
    )

    deps.project_service.get_budget_limits_consumption.assert_awaited_once_with(
        [uuids[name] for name in readable]
    )
    assert event == {str(LID): BAR_JSON}
