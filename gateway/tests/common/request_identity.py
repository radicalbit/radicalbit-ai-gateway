from dataclasses import fields, replace

from tests.common.db_mock import API_KEY_UUID, GROUP_UUID, REQUEST_UUID

from radicalbit_ai_gateway.models.request_identity import RequestIdentity

# The request a limiter is counting for, in tests that don't look at its events.
IDENTITY = RequestIdentity(
    request_uuid=str(REQUEST_UUID),
    route_name='test-route',
    api_key_uuid=str(API_KEY_UUID),
    api_key_name='test-key',
    group_uuid=str(GROUP_UUID),
    group_name='test-group',
)

_IDENTITY_FIELDS = {field.name for field in fields(RequestIdentity)}


def with_identity(**kwargs) -> dict:
    """Return the arguments of a call that takes an ``identity``: the loose
    identity fields among ``kwargs`` (``request_uuid``, ``route_name``…)
    gathered into one ``RequestIdentity``, the others as they are. A field
    not given is ``IDENTITY``'s.
    """
    loose = {k: kwargs.pop(k) for k in list(kwargs) if k in _IDENTITY_FIELDS}
    return {'identity': replace(IDENTITY, **loose), **kwargs}
