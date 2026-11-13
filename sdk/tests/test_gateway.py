"""The client against a mocked transport: requests sent, errors typed."""

import datetime
import json
from uuid import uuid4

import httpx2
import pytest

from radicalbit_gateway import NOT_GIVEN, Gateway, errors, models

URL = 'http://gateway.test'


def _project() -> dict:
    return {
        'uuid': str(uuid4()),
        'name': 'p',
        'description': None,
        'projectStatus': 'DEV',
        'servedConfigUuid': None,
        'createdAt': 'now',
        'updatedAt': 'now',
        'configs': [
            {
                'uuid': str(uuid4()),
                'slot': slot,
                'configFile': '',
                'configStatus': 'DRAFT',
                'createdAt': 'now',
                'updatedAt': None,
            }
            for slot in ('A', 'B')
        ],
    }


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


def _gateway(status: int, body, seen: list | None = None, **kwargs) -> Gateway:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if seen is not None:
            seen.append(request)
        if isinstance(body, bytes):
            return httpx2.Response(status, content=body)
        return httpx2.Response(status, json=body)

    return Gateway(URL, transport=httpx2.MockTransport(handler), **kwargs)


def test_save_sends_the_path_and_the_json_body():
    project = _project()
    project_uuid, config_uuid = project['uuid'], project['configs'][1]['uuid']
    seen: list[httpx2.Request] = []
    out = _gateway(200, project, seen).configs.save(
        project_uuid, config_uuid, config_file='routes: {}'
    )
    assert isinstance(out, models.ProjectOut)
    assert out.configs[1].config_status == 'DRAFT'
    assert seen[0].method == 'PATCH'
    assert seen[0].url.path == (
        f'/public/api/v1/projects/{project_uuid}/configs/{config_uuid}'
    )
    assert json.loads(seen[0].content) == {'configFile': 'routes: {}'}


def test_unset_optional_fields_are_not_sent():
    seen: list[httpx2.Request] = []
    gw = _gateway(201, _project(), seen)
    gw.projects.create(name='p')
    gw.projects.create(name='p', description=NOT_GIVEN)
    assert [json.loads(r.content) for r in seen] == [{'name': 'p'}, {'name': 'p'}]


def test_none_is_sent_as_null_when_given():
    seen: list[httpx2.Request] = []
    gw = _gateway(201, _project(), seen)
    gw.projects.create(name='p', description=None)
    assert json.loads(seen[0].content) == {'name': 'p', 'description': None}


def test_body_values_are_serialized_as_json():
    seen: list[httpx2.Request] = []
    _gateway(201, KEY, seen).keys.create(name='k', expires_on=datetime.date(2030, 1, 2))
    assert json.loads(seen[0].content) == {'name': 'k', 'expiresOn': '2030-01-02'}


def test_rotate_sends_a_required_null():
    seen: list[httpx2.Request] = []
    out = _gateway(200, KEY, seen).keys.rotate(KEY['uuid'], grace_period=None)
    assert isinstance(out, models.KeyFullOut)
    assert seen[0].url.path == f'/public/api/v1/keys/{KEY["uuid"]}/rotation'
    assert json.loads(seen[0].content) == {'gracePeriod': None}


def test_add_keys_sends_the_key_uuids():
    group_uuid, key_uuid = uuid4(), uuid4()
    group = {
        'uuid': str(group_uuid),
        'name': 'g',
        'keys': None,
        'routes': None,
        'metadata': None,
        'owner': 'o',
        'createdAt': 'now',
        'updatedAt': 'now',
    }
    seen: list[httpx2.Request] = []
    _gateway(201, group, seen).groups.add_keys(group_uuid, keys=[key_uuid])
    assert seen[0].url.path == f'/public/api/v1/groups/{group_uuid}/keys'
    assert json.loads(seen[0].content) == {'keys': [str(key_uuid)]}


def test_path_segments_are_escaped():
    seen: list[httpx2.Request] = []
    group_uuid, project_uuid = uuid4(), uuid4()
    with pytest.raises(errors.NotFoundError):
        _gateway(
            404, {'error': {'message': 'm', 'type': 't'}}, seen
        ).groups.remove_route(group_uuid, project_uuid, 'a/b c')
    assert seen[0].url.raw_path.decode().endswith('/routes/a%2Fb%20c')


def test_query_params_keep_the_api_names_and_omit_unset_ones():
    seen: list[httpx2.Request] = []
    gw = _gateway(200, [], seen)
    assert gw.groups.list(include_keys=True) == []
    gw.projects.list(filter='active')
    assert dict(seen[0].url.params) == {'include_keys': 'true'}
    assert dict(seen[1].url.params) == {'filter': 'active'}


def test_list_responses_are_parsed():
    out = _gateway(200, [_project()]).projects.list()
    assert [type(p) for p in out] == [models.ProjectOut]


def test_upload_sends_a_multipart_file():
    seen: list[httpx2.Request] = []
    _gateway(200, _project(), seen).configs.upload(
        uuid4(), uuid4(), file=('config.yaml', b'routes: {}', 'application/yaml')
    )
    request = seen[0]
    assert request.headers['Content-Type'].startswith('multipart/form-data')
    content = request.read()
    assert b'filename="config.yaml"' in content
    assert b'routes: {}' in content


def test_config_validation_error_has_details():
    body = {
        'error': {
            'message': 'Invalid gateway configuration - 1 error(s): ...',
            'type': 'auth_registry_error',
            'param': None,
            'code': 'project_config_validation_error',
            'details': [
                {'loc': ['routes'], 'msg': 'Field required', 'type': 'missing'}
            ],
        }
    }
    with pytest.raises(errors.ValidationError) as exc:
        _gateway(400, body).configs.validate(config_file='x')
    assert exc.value.status == 400
    assert exc.value.code == 'project_config_validation_error'
    assert exc.value.message.startswith('Invalid gateway configuration')
    assert exc.value.details == [
        {'loc': ['routes'], 'msg': 'Field required', 'type': 'missing'}
    ]


def test_request_validation_error_has_details():
    body = {
        'detail': [
            {'loc': ['body', 'name'], 'msg': 'Field required', 'type': 'missing'}
        ]
    }
    with pytest.raises(errors.ValidationError) as exc:
        _gateway(422, body).projects.create(name='p')
    assert exc.value.code is None
    assert exc.value.message == 'Field required'
    assert exc.value.details[0]['loc'] == ['body', 'name']


@pytest.mark.parametrize(
    ('status', 'cls'),
    [
        (401, errors.AuthenticationError),
        (403, errors.AuthorizationError),
        (404, errors.NotFoundError),
        (409, errors.ConflictError),
        (400, errors.GatewayError),
        (405, errors.GatewayError),
        (500, errors.GatewayError),
    ],
)
def test_status_mapping(status, cls):
    body = {'error': {'message': 'nope', 'type': 't', 'param': None, 'code': 'c'}}
    with pytest.raises(cls) as exc:
        _gateway(status, body).configs.serve(uuid4(), uuid4())
    assert type(exc.value) is cls
    assert (exc.value.status, exc.value.code, exc.value.message) == (
        status,
        'c',
        'nope',
    )
    assert exc.value.body == body


def test_non_json_body_on_an_undeclared_status():
    # e.g. a proxy in front of the gateway: kept as it came
    with pytest.raises(errors.GatewayError) as exc:
        _gateway(502, b'<html>bad gateway</html>').configs.approve(uuid4(), uuid4())
    assert type(exc.value) is errors.GatewayError
    assert exc.value.status == 502
    assert exc.value.body == '<html>bad gateway</html>'


def test_auth_and_headers_are_applied():
    class CookieAuth(httpx2.Auth):
        def auth_flow(self, request):
            request.headers['Cookie'] = 'access_token=t'
            yield request

    seen: list[httpx2.Request] = []
    gw = _gateway(200, [], seen, auth=CookieAuth(), headers={'X-Team': 'ml'})
    gw.projects.list()
    assert seen[0].headers['Cookie'] == 'access_token=t'
    assert seen[0].headers['X-Team'] == 'ml'


def test_context_manager_closes_the_http_client():
    with _gateway(200, []) as gw:
        gw.keys.list()
    with pytest.raises(RuntimeError):
        gw.keys.list()
