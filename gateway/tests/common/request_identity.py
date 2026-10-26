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
