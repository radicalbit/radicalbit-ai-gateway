"""generator/generate_client.py on tiny specs: what it renders, what it rejects."""

import ast
import copy
import json
from pathlib import Path

import pytest

from generate_client import UnsupportedSpecError, render

MODELS = 'class ThingIn: ...\nclass ThingOut: ...\nclass ErrorOut: ...\n'
ERROR = {
    'content': {
        'application/json': {'schema': {'$ref': '#/components/schemas/ErrorOut'}}
    }
}


def _spec(**operation) -> dict:
    op = {
        'tags': ['things'],
        'operationId': 'things_update',
        'summary': 'Update Thing',
        'description': 'Update a thing.\n\nKeeps the rest.',
        'parameters': [
            {
                'in': 'path',
                'name': 'thing_uuid',
                'required': True,
                'schema': {'type': 'string', 'format': 'uuid'},
            },
            {
                'in': 'query',
                'name': 'dry_run',
                'required': False,
                'schema': {'type': 'boolean', 'default': False},
            },
        ],
        'requestBody': {
            'required': True,
            'content': {
                'application/json': {'schema': {'$ref': '#/components/schemas/ThingIn'}}
            },
        },
        'responses': {
            '200': {
                'content': {
                    'application/json': {
                        'schema': {
                            'type': 'array',
                            'items': {'$ref': '#/components/schemas/ThingOut'},
                        }
                    }
                }
            },
            '404': ERROR,
        },
    }
    op.update(operation)
    return {
        'paths': {'/things/{thing_uuid}': {'patch': op}},
        'components': {
            'schemas': {
                'ThingIn': {
                    'type': 'object',
                    'properties': {
                        'displayName': {'type': 'string'},
                        'note': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
                    },
                    'required': ['displayName'],
                },
                'ThingOut': {'type': 'object', 'properties': {}},
                'ErrorOut': {'type': 'object', 'properties': {}},
            }
        },
    }


def _method(source: str, class_name: str, name: str) -> ast.FunctionDef:
    classes = {n.name: n for n in ast.parse(source).body if isinstance(n, ast.ClassDef)}
    return next(f for f in classes[class_name].body if getattr(f, 'name', '') == name)


def test_renders_an_operation():
    source = render(_spec(), MODELS)
    method = _method(source, 'ThingsResource', 'update')
    args = method.args
    assert [a.arg for a in args.args] == ['self', 'thing_uuid']
    assert ast.unparse(args.args[1].annotation) == 'UUID | str'
    assert [(a.arg, ast.unparse(a.annotation)) for a in args.kwonlyargs] == [
        ('display_name', 'str'),
        ('dry_run', 'bool | NotGiven'),
        ('note', 'str | None | NotGiven'),
    ]
    assert [d and ast.unparse(d) for d in args.kw_defaults] == [
        None,
        'NOT_GIVEN',
        'NOT_GIVEN',
    ]
    assert ast.unparse(method.returns) == 'list[models.ThingOut]'
    assert ast.get_docstring(method) == (
        'Update a thing.\n\nKeeps the rest.\n\n'
        'Args:\n'
        '    thing_uuid: Path parameter.\n'
        '    display_name: Body field ``displayName``.\n'
        '    dry_run: Query parameter. Optional: not sent unless given.\n'
        '    note: Body field. Optional: not sent unless given. None is sent as null.\n\n'
        'Returns:\n'
        '    list[models.ThingOut]\n\n'
        'Raises:\n'
        '    NotFoundError: 404.\n'
        '    APIConnectionError: no answer from the gateway '
        '(APITimeoutError when the time ran out).'
    )
    call = method.body[-1].value
    assert [ast.unparse(a) for a in call.args] == ["'PATCH'", "'/things/{thing_uuid}'"]
    assert {k.arg: ast.unparse(k.value) for k in call.keywords} == {
        'path_params': "{'thing_uuid': thing_uuid}",
        'query': "{'dry_run': dry_run}",
        'json': "{'displayName': display_name, 'note': note}",
        'response': 'list[models.ThingOut]',
    }
    resources = _method(source, 'Resources', '__init__')
    assert ast.unparse(resources.body[0]) == 'self.things = ThingsResource(client)'


def test_renders_a_multipart_file():
    spec = _spec()
    spec['components']['schemas']['ThingIn'] = {
        'type': 'object',
        'properties': {'file': {'type': 'string', 'format': 'binary'}},
        'required': ['file'],
    }
    spec['paths']['/things/{thing_uuid}']['patch']['requestBody']['content'] = {
        'multipart/form-data': spec['paths']['/things/{thing_uuid}']['patch'][
            'requestBody'
        ]['content']['application/json']
    }
    method = _method(render(spec, MODELS), 'ThingsResource', 'update')
    assert ast.unparse(method.args.kwonlyargs[0].annotation) == 'FileTypes'
    keywords = {k.arg: ast.unparse(k.value) for k in method.body[-1].value.keywords}
    assert keywords['files'] == "{'file': file}"
    assert keywords['data'] == '{}'


def test_a_method_named_like_a_builtin_qualifies_it():
    method = _method(
        render(_spec(operationId='things_list'), MODELS), 'ThingsResource', 'list'
    )
    assert ast.unparse(method.returns) == 'builtins.list[models.ThingOut]'


def _break(spec: dict, change) -> dict:
    spec = copy.deepcopy(spec)
    change(spec['paths']['/things/{thing_uuid}']['patch'], spec)
    return spec


def _return_a_model_not_in_models_py(op: dict, spec: dict) -> None:
    spec['components']['schemas']['Other'] = {'type': 'object'}
    op['responses']['200']['content']['application/json']['schema'] = {
        '$ref': '#/components/schemas/Other'
    }


UNSUPPORTED = {
    'operationId without the tag prefix': lambda op, s: op.update(operationId='update'),
    'two tags': lambda op, s: op.update(tags=['things', 'more']),
    'header parameter': lambda op, s: op['parameters'].append(
        {'in': 'header', 'name': 'X-Id', 'schema': {'type': 'string'}}
    ),
    'cookie parameter': lambda op, s: op['parameters'].append(
        {'in': 'cookie', 'name': 'sid', 'schema': {'type': 'string'}}
    ),
    'unknown content type': lambda op, s: op['requestBody'].update(
        content={'text/plain': {'schema': {'type': 'string'}}}
    ),
    'oneOf body': lambda op, s: op['requestBody']['content']['application/json'].update(
        schema={'oneOf': [{'$ref': '#/components/schemas/ThingIn'}]}
    ),
    'oneOf field': lambda op, s: s['components']['schemas']['ThingIn'][
        'properties'
    ].update(note={'oneOf': [{'type': 'string'}, {'type': 'integer'}]}),
    'optional body': lambda op, s: op['requestBody'].update(required=False),
    'two 2xx responses': lambda op, s: op['responses'].update({'201': {}}),
    'unknown error schema': lambda op, s: op['responses'].update(
        {
            '400': {
                'content': {
                    'application/json': {
                        'schema': {'$ref': '#/components/schemas/ThingOut'}
                    }
                }
            }
        }
    ),
    'model missing in models.py': _return_a_model_not_in_models_py,
    'no description': lambda op, s: op.update(summary='', description=''),
}


@pytest.mark.parametrize('change', UNSUPPORTED.values(), ids=UNSUPPORTED.keys())
def test_fails_loudly_on_an_unsupported_construct(change):
    with pytest.raises(UnsupportedSpecError):
        render(_break(_spec(), change), MODELS)


def test_output_is_deterministic():
    spec = json.loads((Path(__file__).parents[1] / 'openapi.json').read_text())
    models = (
        Path(__file__).parents[1] / 'src/radicalbit_gateway/models.py'
    ).read_text()
    reordered = copy.deepcopy(spec)
    reordered['paths'] = dict(reversed(list(spec['paths'].items())))
    assert render(spec, models) == render(spec, models) == render(reordered, models)


def test_the_error_classes_match_the_ones_the_client_raises():
    from generate_client import ERROR_CLASSES
    from radicalbit_gateway import errors

    for status, name in ERROR_CLASSES.items():
        if status == 400:  # a ValidationError only for an invalid config
            continue
        assert errors._BY_STATUS[status].__name__ == name


def test_a_type_alias_of_models_py_is_a_valid_type():
    spec = _spec()
    spec['paths']['/things/{thing_uuid}']['patch']['parameters'][1]['schema'] = {
        '$ref': '#/components/schemas/Mode'
    }
    spec['components']['schemas']['Mode'] = {'type': 'string', 'enum': ['a', 'b']}
    models = MODELS + "Mode = TypeAliasType('Mode', Literal['a', 'b'])\n"
    method = _method(render(spec, models), 'ThingsResource', 'update')
    assert ast.unparse(method.args.kwonlyargs[1].annotation) == (
        'models.Mode | NotGiven'
    )


def test_renders_the_async_twin_of_each_resource():
    source = render(_spec(), MODELS)
    method = _method(source, 'AsyncThingsResource', 'update')
    assert isinstance(method, ast.AsyncFunctionDef)
    assert isinstance(method.body[-1].value, ast.Await)
    resources = _method(source, 'AsyncResources', '__init__')
    assert ast.unparse(resources.body[0]) == 'self.things = AsyncThingsResource(client)'


def test_the_output_says_it_is_generated():
    first = render(_spec(), MODELS).splitlines()[0]
    assert first == (
        '# Code generated by the Radicalbit AI Gateway SDK generator. DO NOT EDIT.'
    )


def test_renders_for_the_package_given():
    source = render(_spec(), MODELS, package='my_sdk')
    imports = [
        ast.unparse(n)
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.ImportFrom)
    ]
    assert 'from my_sdk import models' in imports
    assert 'from my_sdk._client import AsyncGateway, Gateway' in imports
    # NOT_GIVEN, the file type: still this SDK's
    assert 'from radicalbit_gateway._types import NOT_GIVEN, FileTypes, NotGiven' in (
        imports
    )


def test_refuses_a_package_that_is_not_a_dotted_name():
    with pytest.raises(UnsupportedSpecError):
        render(_spec(), MODELS, package='my-sdk')


def test_an_api_name_that_is_a_keyword_or_starts_with_an_underscore():
    spec = _spec()
    spec['paths']['/things/{thing_uuid}']['patch']['parameters'] += [
        {'in': 'query', 'name': 'from', 'schema': {'type': 'string'}},
        {'in': 'query', 'name': '_page', 'schema': {'type': 'integer'}},
    ]
    method = _method(render(spec, MODELS), 'ThingsResource', 'update')
    assert 'from_' in [a.arg for a in method.args.kwonlyargs]
    assert 'page' in [a.arg for a in method.args.kwonlyargs]
    keywords = {k.arg: ast.unparse(k.value) for k in method.body[-1].value.keywords}
    # The API names are the ones sent
    assert "'from': from_" in keywords['query']
    assert "'_page': page" in keywords['query']
    assert 'from_: Query parameter ``from``.' in ast.get_docstring(method)


def test_an_inline_set_of_strings_is_a_literal():
    spec = _spec()
    spec['components']['schemas']['ThingIn']['properties']['mode'] = {
        'type': 'string',
        'enum': ['b', 'a'],
    }
    method = _method(render(spec, MODELS), 'ThingsResource', 'update')
    annotations = {a.arg: ast.unparse(a.annotation) for a in method.args.kwonlyargs}
    assert annotations['mode'] == "Literal['a', 'b'] | NotGiven"


def test_an_inline_set_of_numbers_is_refused():
    spec = _spec()
    spec['components']['schemas']['ThingIn']['properties']['level'] = {
        'type': 'integer',
        'enum': [1, 2],
    }
    with pytest.raises(UnsupportedSpecError):
        render(spec, MODELS)
