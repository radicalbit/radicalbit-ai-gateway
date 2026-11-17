from unittest.mock import AsyncMock, MagicMock
import uuid

from fastapi import Request
import pytest

from radicalbit_ai_gateway.auth.request_auth import authenticate_bearer_request
from radicalbit_ai_gateway.middleware.request_event_context import RequestEventContext
from radicalbit_ai_gateway.models.auth_dto import KeyDetails
from radicalbit_ai_gateway.utils.exceptions import MissingApiKey

KEY_DETAILS = KeyDetails(
    api_key_uuid=str(uuid.uuid4()),
    api_key_name='my-key',
    group_uuid=str(uuid.uuid4()),
    group_name='team-a',
    hashed_api_key='hashed',
)


def _make_request(headers: dict[str, str]) -> Request:
    scope = {
        'type': 'http',
        'method': 'POST',
        'path': '/v1/chat/completions',
        'headers': [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        'app': MagicMock(),
    }
    request = Request(scope)
    request.app.state.token_validator.validate_token = AsyncMock(
        return_value=KEY_DETAILS
    )
    return request


async def test_happy_path_populates_state_and_context():
    request = _make_request({'Authorization': 'Bearer sk-rb-abc'})

    key_details = await authenticate_bearer_request(request, 'proj-uuid', 'proj-name')

    assert key_details is KEY_DETAILS
    request.app.state.token_validator.validate_token.assert_awaited_once_with(
        'sk-rb-abc'
    )
    assert request.state.api_key_uuid == KEY_DETAILS.api_key_uuid
    assert request.state.group_name == 'team-a'
    ctx = RequestEventContext.get(request)
    assert ctx.api_key_uuid == KEY_DETAILS.api_key_uuid
    assert ctx.group_uuid == KEY_DETAILS.group_uuid


@pytest.mark.parametrize(
    'headers', [{}, {'Authorization': 'Basic abc'}, {'Authorization': 'sk-rb-abc'}]
)
async def test_missing_or_malformed_bearer_raises(headers):
    request = _make_request(headers)
    with pytest.raises(MissingApiKey, match='Missing API key'):
        await authenticate_bearer_request(request, 'proj-uuid', 'proj-name')
