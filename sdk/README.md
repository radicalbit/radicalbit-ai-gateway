# radicalbit-ai-gateway-sdk

Python SDK for the management API (`/public/api/v1`) of the Radicalbit AI Gateway:
projects, credentials, groups and configs. Each method calls exactly one API
operation and returns the API's own model, on a sync (`Gateway`) or an async
(`AsyncGateway`) client. Python 3.11+, runtime dependencies `httpx2`, `pydantic`
and `typing-extensions` only.

```python
from radicalbit_gateway import Gateway, errors, models

with Gateway('http://localhost:9000') as gw:
    project = gw.projects.create(name='support-bot')
    # credential.api_key: the value, returned only here
    credential = gw.credentials.create(name='support-bot-prod')
    group = gw.groups.create(name='support')
    gw.groups.add_credentials(group.uuid, keys=[credential.uuid])

    gw.configs.validate(config_file=open('config.yaml').read())  # dry run
    slot_a = next(c for c in project.configs if c.slot == 'A')
    with open('config.yaml', 'rb') as file:
        gw.configs.upload(project.uuid, slot_a.uuid, file=file)
    gw.configs.approve(project.uuid, slot_a.uuid)  # Ready to serve
    gw.configs.serve(project.uuid, slot_a.uuid)  # published
    gw.groups.add_routes(group.uuid, project.uuid, routes=['support-route'])
```

## API

Operation `<tag>_<action>` of the API is the method `gw.<tag>.<action>()`
(`credentials_create` is `gw.credentials.create`, `configs_cancel_approval` is
`gw.configs.cancel_approval`). For every method:

- **path parameters** are positional, named as in the API (`project_uuid`,
  `config_uuid`, `key_uuid`, `group_uuid`, `route_name`);
- **JSON body fields and query parameters** are keyword-only, in snake_case
  (`configFile` is `config_file`). Required ones have no default;
- **optional ones default to `NOT_GIVEN`**: an argument you do not pass is not
  sent, so the API applies its own default. `None` is sent as JSON `null`
  (e.g. `credentials.rotate(key_uuid, grace_period=None)`: no grace period);
- a **file** of a multipart body (`configs.upload(..., file=...)`) takes an
  open binary file or `(filename, content[, content type])`, not the content
  alone: the gateway accepts only a `.yaml` or `.yml` filename. For YAML text
  already in memory, `configs.save(..., config_file=text)` needs no file;
- an **id** takes a `UUID` or its string (`gw.credentials.get('3f1c9a2e-...')`);
- a **closed set of values** is a plain string, checked by the type checker and
  completed by the editor (`gw.projects.list(filter='prod')`;
  `project.project_status == 'PROD'`): `models.ProjectFilter` and the like are
  `Literal` type aliases, not enums;
- the return value is the API's response model, from `radicalbit_gateway.models`
  (snake_case attributes, e.g. `project.served_config_uuid`;
  `model_dump(by_alias=True)` gives the API's camelCase).

The signatures and docstrings are the reference (`help(gw.configs)`): they are
generated from the API's spec, and each docstring lists the method's
arguments, return value and errors. A project has two config slots, `A` and
`B`, in `project.configs`. The API's paths and fields still call credentials
`keys` (`/keys`, `key_uuid`, `groups.add_credentials(..., keys=[...])`); the
methods call them credentials (`gw.credentials`).

## Errors

Every non-2xx status raises a `radicalbit_gateway.errors.GatewayError`
subclass with `status`, `code`, `message` and the decoded `body`:

| Status | Class |
|---|---|
| 400 (invalid config, `code='project_config_validation_error'`), 422 | `ValidationError` (`.details`: `[{loc, msg, type}]`) |
| 401 / 403 | `AuthenticationError` / `AuthorizationError` |
| 404 | `NotFoundError` |
| 409 | `ConflictError` (e.g. `code='config_not_approved'`, `code='group_already_exists'`) |
| other | `GatewayError` |
| no answer | `APIConnectionError` (`APITimeoutError` when the time ran out), `status` None |

So `except errors.GatewayError` catches every failure of a call.

## Retries

A failed call is sent again, up to `max_retries` times (default 2), only when
sending it twice cannot do the work twice:

- **any method**, when the request never reached the gateway (connection
  refused, connect timeout) or the gateway refused it unprocessed (429, 503);
- **reads** (GET) also after a lost answer or a failure midway (other
  timeouts, a broken connection, 408, 500, 502, 504). A create, a state change
  or a delete (POST, PATCH, DELETE) is not sent again then: it may have
  happened, and repeating it would answer 409 or 404 on work already done.

The wait doubles from 0.5 s up to 8 s, with jitter, or follows `Retry-After` /
`retry-after-ms` (up to 60 s). An upload of an open file is not retried (it
could not be read again); pass `('config.yaml', content_bytes)` for a retried
upload.

## Newer gateways

A response carrying what this SDK version does not know does not fail: an
unknown value of a closed set comes through as sent (`key.state == 'suspended'`),
an unknown field is kept in `model_extra` under its API name. Anything else that
does not match the model (a wrong type, a missing field) still raises.

## Client options

`Gateway(base_url=None, *, auth=None, timeout=30.0, max_retries=2, transport=None, headers=None)`:

- `base_url` defaults to the `RADICALBIT_GATEWAY_BASE_URL` environment variable;
- `timeout` in seconds, or an `httpx2.Timeout`;
- `auth` is any `httpx2.Auth` (e.g. one that sets a cookie or a header),
  `transport` any httpx2 transport (`httpx2.MockTransport` in tests), `headers`
  are sent with every request. Every request also sends
  `User-Agent: radicalbit-ai-gateway-sdk-python/<version>`.

Use it as a context manager, or call `close()`. For some calls only,
`with_options` gives a copy that shares the connections:

```python
gw.with_options(timeout=120).configs.validate(config_file=big_config)
gw.with_options(max_retries=0, headers={'X-Run': run_id}).credentials.list()
```

`AsyncGateway` takes the same options; its methods are awaited, and it is used
with `async with` (or `await gw.close()`):

```python
async with AsyncGateway() as gw:
    projects = await gw.projects.list(filter='prod')
```

## How the SDK is generated

`scripts/generate.sh` is the only step; it is deterministic (running it twice
yields no diff):

1. exports `openapi.json` from the gateway app (`gateway/scripts/export_sdk_spec.py`);
2. **datamodel-codegen** writes the models into `src/radicalbit_gateway/models.py`
   (options in `pyproject.toml`, `[tool.datamodel-codegen]`);
3. **`generator/generate_client.py`** (our script, with the Jinja2 template
   `generator/resources.py.jinja`) writes the methods into
   `src/radicalbit_gateway/_resources.py`;
4. ruff drops unused imports from both files and formats them.

Both start with `# Code generated by the Radicalbit AI Gateway SDK generator.
DO NOT EDIT.`, the convention editors and review tools read, and the root
`.gitattributes` marks them (and `openapi.json`) as generated, so GitHub
collapses their diffs. Never edit them by hand. The handwritten code knows no
endpoint: `_client.py` (the two clients: sending, retrying, options),
`_models.py` (the models' base class: tolerance of what newer gateways add),
`errors.py` (status and error body to exception), `_types.py` (`NOT_GIVEN`,
the file type).
The tool versions are pinned in `pyproject.toml` / `uv.lock`.

### When an endpoint changes

Run `scripts/generate.sh` and commit `openapi.json`, `models.py` and
`_resources.py`. CI (`.github/workflows/sdk-workflow.yaml`) fails when they are
stale.

### When the generator rejects the spec

`generate_client.py` stops with `unsupported spec construct: <operation>: <what>`
on anything it does not render, instead of skipping it: e.g. an operationId
without its `<tag>_` prefix, a header or cookie parameter, a request content
type other than JSON or multipart, a `oneOf` body, more than one 2xx response,
an error response that is not `ErrorOut`/`HTTPValidationError`. Either change
the endpoint to follow the conventions every other endpoint follows (the usual
fix), or teach the generator the construct, with a test in
`tests/test_generator.py`.

## Development

- `uv run pytest`: the generator tests (`tests/test_generator.py`) and the unit
  tests on a mocked transport: the operations (`tests/test_gateway.py`) and the
  client's own behaviour, retries, options, async, tolerance
  (`tests/test_client_options.py`).
- `gateway/tests/sdk/`: every SDK method against the gateway's real routes and
  error handlers, in-process, with the services mocked
  (`cd ../gateway && uv run pytest tests/sdk --no-cov`). It runs in the
  gateway's tests and in the SDK workflow.
- Python 3.11+, for the SDK and its dev environment.
- `uv run ty check src`: type-checks the SDK, generated code included.
