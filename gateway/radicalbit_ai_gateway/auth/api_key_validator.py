from radicalbit_ai_gateway.models.auth_dto import KeyDetails
from radicalbit_ai_gateway.models.credential_expiry import (
    CredentialState,
    get_credential_state,
)
from radicalbit_ai_gateway.models.credential_rotation import (
    previous_value_authenticates,
)
from radicalbit_ai_gateway.services.commons.keyed_hash_algorithm import hash_key
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.utils.exceptions import (
    ExpiredApiKey,
    InvalidApiKey,
    KeyNotFoundError,
)


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

        # Found by its previous value: valid only during the grace period, and
        # afterwards indistinguishable from a wrong value, even once the credential
        # has expired (ADR 0008). A grace period never outlasts the expiry.
        if hashed != key_record.hashed_key and not previous_value_authenticates(
            key_record.expires_on, key_record.grace_ends_at
        ):
            raise InvalidApiKey(
                'Incorrect API key provided.',
                log_message=f'Previous value of API key {key_record.uuid} used after its grace period',
            )

        if get_credential_state(key_record.expires_on) == CredentialState.EXPIRED:
            raise ExpiredApiKey(
                'API key has expired.',
                log_message=f'API key {key_record.uuid} expired on {key_record.expires_on}',
            )

        group = key_record.group
        if group is None:
            raise InvalidApiKey('API Key does not have a group associated')

        return KeyDetails(
            api_key_uuid=str(key_record.uuid),
            api_key_name=key_record.name,
            hashed_api_key=hashed,
            group_uuid=str(group.uuid),
            group_name=group.name,
            limits=key_record.limits or [],
        )
