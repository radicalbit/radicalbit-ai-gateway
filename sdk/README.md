# radicalbit-gateway

Python SDK for the management API (`/public/api/v1`) of the Radicalbit AI Gateway:
projects, credentials, groups and configs. Each method calls exactly one API
operation and returns the API's own model. Python 3.11+, runtime dependencies
`httpx2` and `pydantic` only.

```python
from radicalbit_gateway import Gateway, errors, models

with Gateway('http://localhost:9000') as gw:
    project = gw.projects.create(name='support-bot')
    key = gw.keys.create(name='support-bot-prod')  # key.api_key: the only copy
    group = gw.groups.create(name='support')
    gw.groups.add_keys(group.uuid, keys=[key.uuid])

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
(`keys_create` is `gw.keys.create`, `configs_cancel_approval` is
`gw.configs.cancel_approval`). For every method:

- **path parameters** are positional, named as in the API (`project_uuid`,
  `config_uuid`, `key_uuid`, `group_uuid`, `route_name`);
- **JSON body fields and query parameters** are keyword-only, in snake_case
  (`configFile` is `config_file`). Required ones have no default;
- **optional ones default to `NOT_GIVEN`**: an argument you do not pass is not
  sent, so the API applies its own default. `None` is sent as JSON `null`
  (e.g. `keys.rotate(key_uuid, grace_period=None)`: no grace period);
- a **file** of a multipart body (`configs.upload(..., file=...)`) takes what
  httpx2 takes: an open binary file, `bytes`, or `(filename, content[, content type])`;
- the return value is the API's response model, from `radicalbit_gateway.models`
  (snake_case attributes, e.g. `project.served_config_uuid`;
  `model_dump(by_alias=True)` gives the API's camelCase).

The signatures and docstrings are the reference (`help(gw.configs)`): they are
generated from the API's spec. Credentials are the API's `keys`. A project has
two config slots, `A` and `B`, in `project.configs`.

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

## Client options

`Gateway(base_url, *, auth=None, timeout=30.0, transport=None, headers=None)`:
`auth` is any `httpx2.Auth` (e.g. one that sets a cookie or a header),
`transport` any httpx2 transport (`httpx2.MockTransport` in tests), `headers` are
sent with every request. Use it as a context manager, or call `close()`.

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

Never edit `models.py` or `_resources.py` by hand. The handwritten code knows
no endpoint: `_client.py` (the `Gateway` and its one `_request`), `errors.py`
(status and error body to exception), `_types.py` (`NOT_GIVEN`, the file type).
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
  tests on a mocked transport (`tests/test_gateway.py`).
- Python 3.11+, for the SDK and its dev environment.
- `uv run ty check src`: type-checks the SDK, generated code included.
