from uuid import UUID

from fastapi import Request

from radicalbit_ai_gateway.middleware.request_event_context import RequestEventContext
from radicalbit_ai_gateway.models.auth_dto import KeyDetails
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.utils.exceptions import InvalidApiKey, MissingApiKey
from radicalbit_ai_gateway.utils.trace_attributes import set_trace_attributes


async def authenticate_bearer_request(
    request: Request, project_uuid: str, project_name: str
) -> KeyDetails:
    """Authenticate a request via its ``Authorization: Bearer`` gateway API key.

    Populates ``request.state``, the request event context, and trace
    attributes with the resolved key identity. Same behavior as the
    ``/v1/chat/completions`` auth step.
    """
    auth = request.headers.get('authorization')
    if not auth or not auth.startswith('Bearer '):
        raise MissingApiKey('Missing API key')
    token = auth.split(' ')[1]

    key_details = await request.app.state.token_validator.validate_token(
        token,
    )
    request.state.api_key_uuid = key_details.api_key_uuid
    request.state.api_key_name = key_details.api_key_name
    request.state.group_uuid = key_details.group_uuid
    request.state.group_name = key_details.group_name
    ctx = RequestEventContext.get_or_create(request)
    ctx.api_key_uuid = key_details.api_key_uuid
    ctx.api_key_name = key_details.api_key_name
    ctx.group_uuid = key_details.group_uuid
    ctx.group_name = key_details.group_name
    set_trace_attributes(
        api_key_uuid=key_details.api_key_uuid,
        api_key_name=key_details.api_key_name,
        group_uuid=key_details.group_uuid,
        group_name=key_details.group_name,
        project_uuid=project_uuid,
        project_name=project_name,
    )
    return key_details


def ensure_key_bound_to_route(
    group_service: GroupService,
    project_name: str,
    route_name: str,
    key_details: KeyDetails,
) -> None:
    """Raise ``InvalidApiKey`` unless the key's group is bound to the route."""
    if not group_service.check_key_uuid_for_route(
        f'{project_name}/{route_name}', UUID(key_details.api_key_uuid)
    ):
        raise InvalidApiKey(f'API Key not associated with route {route_name}')
