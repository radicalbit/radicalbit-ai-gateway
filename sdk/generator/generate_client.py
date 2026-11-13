"""Generate the SDK's client methods (``_resources.py``) from the OpenAPI spec.

One class per tag, one method per operation: operation ``<tag>_<action>`` is
``gw.<tag>.<action>()``. Path parameters are positional; query parameters and
body fields are keyword-only. The request and response models are the ones
datamodel-codegen writes into ``models.py``, which must be generated first.

Any construct this script does not know how to render stops it with an
``UnsupportedSpecError``: nothing is skipped silently.

    python generator/generate_client.py [--spec openapi.json] [--models ...] [--out ...]
"""

import argparse
import ast
import builtins
from dataclasses import dataclass, field
import json
import keyword
from pathlib import Path
import re
import sys

from jinja2 import Environment, FileSystemLoader, StrictUndefined

SDK = Path(__file__).resolve().parents[1]
PACKAGE = SDK / 'src' / 'radicalbit_gateway'
HTTP_METHODS = {'get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'}
ERROR_SCHEMAS = {'ErrorOut', 'HTTPValidationError'}  # the bodies errors.py reads
FORMATS = {'uuid': 'UUID', 'date': 'datetime.date', 'date-time': 'datetime.datetime'}
TYPES = {'integer': 'int', 'number': 'float', 'boolean': 'bool', 'null': 'None'}
REF = '#/components/schemas/'


class UnsupportedSpecError(Exception):
    """The spec uses a construct the generator does not render."""


def check(condition: object, message: str) -> None:
    if not condition:
        raise UnsupportedSpecError(message)


@dataclass
class Param:
    name: str  # the Python argument
    api_name: str  # the name on the wire
    annotation: str
    required: bool


@dataclass
class Operation:
    name: str
    http_method: str
    path: str
    doc: str
    response: str | None
    path_params: list[Param] = field(default_factory=list)
    query: list[Param] = field(default_factory=list)
    json: list[Param] | None = None  # None: no JSON body
    form: list[Param] | None = None  # None: no multipart body
    files: list[Param] = field(default_factory=list)

    @property
    def keyword_params(self) -> list[Param]:
        params = self.query + (self.json or []) + (self.form or []) + self.files
        return sorted(params, key=lambda p: not p.required)  # stable: required first


@dataclass
class Resource:
    tag: str
    class_name: str
    operations: list[Operation]


def snake_case(name: str, where: str) -> str:
    name = re.sub(r'(?<=[a-z0-9])([A-Z])', r'_\1', name).lower()
    check(
        name.isidentifier() and not keyword.iskeyword(name),
        f'{where}: bad name {name!r}',
    )
    return name


class Spec:
    def __init__(self, spec: dict, model_names: set[str]):
        self.schemas = spec.get('components', {}).get('schemas', {})
        self.paths = spec.get('paths', {})
        self.model_names = model_names

    def ref(self, schema: dict, where: str) -> tuple[str, dict]:
        """The name and the schema a ``$ref`` points to."""
        name = schema.get('$ref', '').removeprefix(REF)
        check(
            name in self.schemas,
            f'{where}: not a $ref to a schema: {json.dumps(schema)}',
        )
        return name, self.schemas[name]

    def annotation(self, schema: dict, where: str) -> str:
        """The Python type of a JSON schema, as source text."""
        if '$ref' in schema:
            name = self.ref(schema, where)[0]
            check(name in self.model_names, f'{where}: no model {name!r} in models.py')
            return f'models.{name}'
        for key in ('oneOf', 'allOf', 'not', 'enum', 'const'):
            check(key not in schema, f'{where}: inline {key!r} schema')
        if 'anyOf' in schema or isinstance(schema.get('type'), list):
            options = schema.get('anyOf') or [
                {**schema, 'type': t} for t in schema['type']
            ]
            types = [self.annotation(s, where) for s in options]
            unique = list(dict.fromkeys(t for t in types if t != 'None'))
            return ' | '.join(unique + ['None'] * ('None' in types))  # None last
        kind, values = schema.get('type'), schema.get('additionalProperties', True)
        check(
            schema.get('format') != 'binary',
            f'{where}: binary outside a multipart body',
        )
        if kind == 'string':
            return FORMATS.get(schema.get('format'), 'str')
        if kind in TYPES:
            return TYPES[kind]
        if kind == 'array' and 'items' in schema:
            return f'list[{self.annotation(schema["items"], where)}]'
        if kind == 'object' and 'properties' not in schema:
            any_value = values is True or values == {}
            return (
                f'dict[str, {"Any" if any_value else self.annotation(values, where)}]'
            )
        raise UnsupportedSpecError(f'{where}: unsupported schema {json.dumps(schema)}')

    def body_fields(
        self, schema: dict, where: str, multipart: bool
    ) -> tuple[list, list]:
        """The (fields, files) of a request body: one keyword argument per property."""
        name, schema = self.ref(schema, where)
        where = f'{where} body {name}'
        check(
            schema.get('type') == 'object' and 'properties' in schema,
            f'{where}: not an object',
        )
        check(
            schema.get('additionalProperties') in (None, False),
            f'{where}: additionalProperties',
        )
        fields, files = [], []
        for api_name, prop in sorted(schema['properties'].items()):
            param = Param(
                snake_case(api_name, where),
                api_name,
                'FileTypes',
                api_name in schema.get('required', []),
            )
            if (
                multipart
                and prop.get('type') == 'string'
                and prop.get('format') == 'binary'
            ):
                files.append(param)
            else:
                param.annotation = self.annotation(prop, f'{where}.{api_name}')
                fields.append(param)
        return fields, files

    def operation(self, path: str, http_method: str, op: dict) -> tuple[str, Operation]:
        tags, op_id = op.get('tags', []), op.get('operationId', '')
        where = f'{http_method.upper()} {path} ({op_id or "no operationId"})'
        check(len(tags) == 1, f'{where}: needs exactly one tag, has {tags}')
        check(
            op_id.startswith(f'{tags[0]}_'),
            f'{where}: operationId lacks the {tags[0]}_ prefix',
        )
        doc = (op.get('description') or op.get('summary') or '').strip()
        check(doc, f'{where}: no description or summary')
        result = Operation(
            name=snake_case(op_id.removeprefix(f'{tags[0]}_'), where),
            http_method=http_method.upper(),
            path=path,
            doc=doc,
            response=self.response(op.get('responses', {}), where),
        )
        for param in op.get('parameters', []):
            location = param.get('in')
            check(
                location in ('path', 'query'),
                f'{where}: unsupported parameter {json.dumps(param)}',
            )
            default_style = 'form' if location == 'query' else 'simple'
            custom = (
                'content' in param or param.get('style', default_style) != default_style
            )
            check(
                not custom,
                f'{where}: parameter {param["name"]!r} has a custom serialization',
            )
            annotation = self.annotation(
                param.get('schema', {}), f'{where}.{param["name"]}'
            )
            name = snake_case(param['name'], where)
            target = result.path_params if location == 'path' else result.query
            target.append(
                Param(name, param['name'], annotation, param.get('required', False))
            )
        template_names = sorted(re.findall(r'{(\w+)}', path))
        check(
            sorted(p.name for p in result.path_params) == template_names,
            f'{where}: path parameters',
        )
        check(
            all(p.name == p.api_name for p in result.path_params),
            f'{where}: path parameters',
        )
        if 'requestBody' in op:
            body, content = op['requestBody'], op['requestBody'].get('content', {})
            check(
                body.get('required') and len(content) == 1,
                f'{where}: optional body or many types',
            )
            content_type, media = next(iter(content.items()))
            schema = media.get('schema', {})
            if content_type == 'application/json':
                result.json, _ = self.body_fields(schema, where, multipart=False)
            elif content_type == 'multipart/form-data':
                result.form, result.files = self.body_fields(
                    schema, where, multipart=True
                )
            else:
                raise UnsupportedSpecError(
                    f'{where}: request content type {content_type!r}'
                )
        names = [p.name for p in result.path_params + result.keyword_params]
        check(
            len(names) == len(set(names)),
            f'{where}: two arguments share a name: {names}',
        )
        return tags[0], result

    def response(self, responses: dict, where: str) -> str | None:
        success = [s for s in responses if s.startswith('2')]
        check(
            len(success) == 1 and success[0].isdigit(),
            f'{where}: needs one 2xx response, has {success}',
        )
        for status, response in responses.items():
            schema = (
                response.get('content', {})
                .get('application/json', {})
                .get('schema', {})
            )
            is_error = (
                status.isdigit()
                and schema.get('$ref', '').removeprefix(REF) in ERROR_SCHEMAS
            )
            check(
                status in success or is_error,
                f'{where}: response {status} is not {ERROR_SCHEMAS}',
            )
        content = responses[success[0]].get('content')
        if not content:
            return None
        check(
            list(content) == ['application/json'],
            f'{where}: response content {list(content)}',
        )
        return self.annotation(
            content['application/json'].get('schema', {}), f'{where} response'
        )

    def resources(self) -> list[Resource]:
        by_tag: dict[str, list[Operation]] = {}
        for path, item in self.paths.items():
            check(
                set(item) <= HTTP_METHODS,
                f'{path}: path-level keys {sorted(set(item) - HTTP_METHODS)}',
            )
            for http_method, op in item.items():
                tag, operation = self.operation(path, http_method, op)
                by_tag.setdefault(tag, []).append(operation)
        resources = []
        for tag in sorted(by_tag):
            operations = sorted(by_tag[tag], key=lambda o: o.name)
            check(
                len({o.name for o in operations}) == len(operations),
                f'tag {tag}: duplicate methods',
            )
            qualify_shadowed_builtins(operations)
            class_name = (
                ''.join(p.title() for p in snake_case(tag, tag).split('_')) + 'Resource'
            )
            resources.append(Resource(tag, class_name, operations))
        return resources


def qualify_shadowed_builtins(operations: list[Operation]) -> None:
    """``builtins.list[...]`` in a class with a method named ``list``, which shadows it."""
    shadowed = {o.name for o in operations} & set(dir(builtins))
    if shadowed:
        pattern = re.compile(rf'(?<![.\w])({"|".join(sorted(shadowed))})\b')
        for op in operations:
            for p in op.path_params + op.keyword_params:
                p.annotation = pattern.sub(r'builtins.\1', p.annotation)
            op.response = op.response and pattern.sub(r'builtins.\1', op.response)


def docstring(text: str) -> str:
    """The body of a triple-quoted docstring, indented for a method."""
    text = text.replace('\\', '\\\\').replace('"""', '\\"\\"\\"')
    lines = [f'        {line}' if line else '' for line in text.splitlines()]
    # A multi-line docstring closes on a line of its own
    return '\n'.join(lines).strip() + ('\n        ' if len(lines) > 1 else '')


def render(spec: dict, models_source: str) -> str:
    """The source of ``_resources.py``; ``ruff`` drops the unused imports and formats it."""
    model_names = {
        n.name for n in ast.parse(models_source).body if isinstance(n, ast.ClassDef)
    }
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        extensions=['jinja2.ext.do'],
    )
    env.filters.update(docstring=docstring, repr=repr)
    resources = Spec(spec, model_names).resources()
    return env.get_template('resources.py.jinja').render(resources=resources)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--spec', type=Path, default=SDK / 'openapi.json')
    parser.add_argument('--models', type=Path, default=PACKAGE / 'models.py')
    parser.add_argument('--out', type=Path, default=PACKAGE / '_resources.py')
    args = parser.parse_args()
    try:
        source = render(json.loads(args.spec.read_text()), args.models.read_text())
    except UnsupportedSpecError as e:
        print(f'generate_client: unsupported spec construct: {e}', file=sys.stderr)
        return 1
    args.out.write_text(source)
    return 0


if __name__ == '__main__':
    sys.exit(main())
