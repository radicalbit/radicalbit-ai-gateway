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

## Working on the SDK

The SDK is **generated from the gateway's routes**. Most of it is never edited
by hand: change the route, then regenerate.

```text
gateway routes ──export──> sdk/openapi.json ──datamodel-codegen──> models.py
                                           └──generate_client.py──> _resources.py
```

| File | Written by | Edit by hand? |
|---|---|---|
| `openapi.json` | `gateway/scripts/export_sdk_spec.py` | No |
| `src/radicalbit_gateway/models.py` | datamodel-codegen | No |
| `src/radicalbit_gateway/_resources.py` | `generator/generate_client.py` + `generator/resources.py.jinja` | No |
| `src/radicalbit_gateway/_client.py`, `_models.py`, `errors.py`, `_types.py` | people | Yes: sending, retries, options, errors; no endpoint |
| `gateway/radicalbit_ai_gateway/sdk_spec.py` | people | Yes: the list of operations in the SDK |

The generated files start with `# Code generated by the Radicalbit AI Gateway
SDK generator. DO NOT EDIT.` and are collapsed in GitHub diffs
(`.gitattributes`).

### Setup

```bash
cd sdk
uv sync
```

Python 3.11+. The gateway's own environment (`cd gateway && uv sync`) is
needed too: the first step of the generation runs in it.

### Regenerate

```bash
sdk/scripts/generate.sh
```

It exports the spec, writes the models and the methods, and formats them. Run
it from anywhere; it is deterministic, so running it twice gives no diff.

### I changed a management route the SDK uses

Any change to the path, parameters, body, response model, declared errors or
docstring of one of the operations in `SDK_OPERATION_IDS`.

1. Change the route in `gateway/`.
2. Run `sdk/scripts/generate.sh`.
3. Read the diff of `openapi.json`, `models.py` and `_resources.py`: it is
   the change SDK users will see. A renamed or removed argument, field or
   method breaks their code.
4. Run the tests (see [Tests](#tests)).
5. Commit the route and the three generated files together.

A route outside the SDK can change without regenerating (the export only
keeps the SDK's operations), unless it changes a model an SDK operation uses
too. When in doubt, run `generate.sh`: no diff means nothing to commit.

### I want a new operation in the SDK

1. Give the route what the generator needs:

   ```python
   @router.patch(
       '/projects/{project_uuid}/configs/{config_uuid}/serve',
       response_model=ProjectOut,  # the method's return type
       tags=['configs'],  # gw.configs
       operation_id='configs_serve',  # <tag>_<action>: gw.configs.serve()
       responses=error_responses(400, 404, 409),  # the errors it can answer
   )
   async def serve_config(project_uuid: UUID, config_uuid: UUID):
       """Publish an approved config: it replaces the one served, if any."""
   ```

   The docstring becomes the method's docstring, and every error the route
   can raise must be in `error_responses(...)`: the method's docstring lists
   them, and a test fails when either is missing.
2. Add the operation id to `SDK_OPERATION_IDS` in
   `gateway/radicalbit_ai_gateway/sdk_spec.py`.
3. Run `sdk/scripts/generate.sh`.
4. Add a case for it to `OPERATIONS` in
   `gateway/tests/sdk/test_sdk_against_routes.py`: the service method it
   calls, a result, and the SDK call. `test_every_sdk_operation_has_a_case`
   fails until it is there.
5. Run the tests, and commit the route, `sdk_spec.py`, the test and the three
   generated files.

### The generator stops with "unsupported spec construct"

`generate_client.py` refuses what it cannot render instead of skipping it:
an operation id without its `<tag>_` prefix, a header or cookie parameter, a
body that is not JSON or multipart, a `oneOf` body, more than one 2xx
response, an error response that is not `ErrorOut` / `HTTPValidationError`.
The message names the operation and the construct. Change the route to
follow the conventions above (the usual fix), or teach the generator the
construct, with a test in `tests/test_generator.py`.

### I changed the generator or the handwritten client

- Generator (`generator/`): run `sdk/scripts/generate.sh` and check the diff
  of the generated files is the one you meant. Add a test to
  `tests/test_generator.py`.
- Client (`_client.py`, `_models.py`, `errors.py`, `_types.py`): add a test
  to `tests/test_client_options.py` or `tests/test_gateway.py`.

### Tests

```bash
cd sdk
uv run pytest                     # generator, operations, client behaviour (mocked transport)
uv run ruff check --exclude src/radicalbit_gateway/models.py --exclude src/radicalbit_gateway/_resources.py
uv run ty check src               # types, generated code included

cd ../gateway
uv run pytest tests/sdk --no-cov  # every SDK method against the real routes, in-process
```

### What CI checks

`.github/workflows/sdk-workflow.yaml` runs on every pull request that touches
`gateway/`, `sdk/` or the workflow:

| Job | Fails when |
|---|---|
| `lint, types, tests, wheel` | ruff, `ty`, the SDK tests or the wheel build fail |
| `generated SDK is up to date` | `generate.sh` changes a file: a route changed and the SDK was not regenerated. Run it and commit. It also runs `gateway/tests/sdk` |
| `lint the SDK spec` | `openapi.json` breaks a Redocly rule |

The tool versions are pinned (`pyproject.toml`, `uv.lock`), so CI and your
machine generate the same code.

### Releasing

Nothing to do by hand. Publishing a GitHub release with a `vX.Y.Z` tag runs
`publish-sdk-pypi` in `.github/workflows/release.yaml`: it tests, builds and
uploads `radicalbit-ai-gateway-sdk` X.Y.Z to PyPI, the same version as the
gateway (both read the tag). Merging to `main` publishes nothing.

The Enterprise SDK (`radicalbit-ai-gateway-enterprise-sdk`, in the Enterprise
repo) builds on this package: a change here reaches it when its dependency is
re-pinned (see its README).
