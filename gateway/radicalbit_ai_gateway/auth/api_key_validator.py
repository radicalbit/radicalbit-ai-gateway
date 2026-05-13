from radicalbit_ai_gateway.models.auth_dto import KeyDetails
from radicalbit_ai_gateway.services.commons.keyed_hash_algorithm import hash_key
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.utils.exceptions import InvalidApiKey, KeyNotFoundError


class ApiKeyValidator:
    """Default token validator for sk-rb-* API keys. Always registered on app.state
    before plugins are loaded; auth plugins may wrap or replace it.
    """

    def __init__(self, key_service: KeyService):
        self._key_service = key_service

    async def validate_token(self, token: str) -> KeyDetails:
        hashed = hash_key(token)
        try:
            key_record = self._key_service.get_key_by_hashed_key(hashed)
        except KeyNotFoundError as e:
            raise InvalidApiKey('Incorrect API key provided.') from e

        group = key_record.group
        if group is None:
            raise InvalidApiKey('API Key does not have a group associated')

        return KeyDetails(
            api_key_uuid=str(key_record.uuid),
            api_key_name=key_record.name,
            hashed_api_key=hashed,
            group_uuid=str(group.uuid),
            group_name=group.name,
        )
