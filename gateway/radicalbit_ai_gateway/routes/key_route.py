import logging
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.exceptions import RequestValidationError

from radicalbit_ai_gateway.models.auth_dto import (
    GroupFullOut,
    KeyCreateIn,
    KeyFullOut,
    KeyGroupIn,
    KeyRotationIn,
    KeyUpdateIn,
)
from radicalbit_ai_gateway.models.credential_limiting import (
    CredentialLimitOut,
    CredentialLimitsIn,
    CredentialLimitUpdatedOut,
    CredentialLimitValueIn,
)
from radicalbit_ai_gateway.models.credential_rotation import GracePeriodOutOfBoundsError
from radicalbit_ai_gateway.route_meta import route_meta
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()

logger = logging.getLogger(app_config.log_config.logger_name)


class KeyRoute:
    @staticmethod
    def get_key_router(key_service: KeyService) -> APIRouter:
        router = APIRouter(tags=['key_api'])

        @router.post('/keys', status_code=201, response_model=KeyFullOut)
        @route_meta(entity_type='KEY', response_uuid_field='uuid')
        def create_key(
            key_in: KeyCreateIn,
        ):
            key = key_service.create_key(key_in)
            logger.info('Created key %s', key.uuid)
            return key

        @router.get('/keys', status_code=200, response_model=list[KeyFullOut])
        def get_all(
            include_groups: bool = False,
            only_unassigned: bool = Query(False),
            include_limits: bool = Query(False),
        ):
            return key_service.get_all(include_groups, only_unassigned, include_limits)

        @router.get('/keys/{key_uuid}', status_code=200, response_model=KeyFullOut)
        def get_key_by_uuid(
            key_uuid: UUID,
            include_groups: bool = False,
            include_limits: bool = Query(False),
        ):
            return key_service.get_key_by_uuid(key_uuid, include_groups, include_limits)

        @router.patch('/keys/{key_uuid}', status_code=200, response_model=KeyFullOut)
        @route_meta(entity_type='KEY', entity_uuid_param='key_uuid')
        def update_key(key_uuid: UUID, key_in: KeyUpdateIn):
            return key_service.update_key_name(key_uuid, key_in)

        @router.delete('/keys/{key_uuid}', status_code=200, response_model=KeyFullOut)
        @route_meta(entity_type='KEY', entity_uuid_param='key_uuid')
        def delete_key(key_uuid: UUID, include_groups: bool = Query(False)):
            return key_service.delete_key(key_uuid, include_groups)

        @router.post(
            '/keys/{key_uuid}/rotation', status_code=200, response_model=KeyFullOut
        )
        @route_meta(entity_type='KEY', entity_uuid_param='key_uuid')
        def rotate_key(key_uuid: UUID, rotation_in: KeyRotationIn):
            try:
                key = key_service.rotate_key(key_uuid, rotation_in)
            except GracePeriodOutOfBoundsError as e:
                # Bounds that depend on the credential's expiry: same shape as the
                # body's own validation errors
                raise RequestValidationError(
                    [
                        {
                            'type': 'value_error',
                            'loc': ('body', 'gracePeriod'),
                            'msg': str(e),
                            'input': rotation_in.grace_period,
                        }
                    ]
                ) from e
            logger.info(
                'Rotated key %s, grace period ends at %s', key_uuid, key.grace_ends_at
            )
            return key

        @router.delete(
            '/keys/{key_uuid}/rotation', status_code=200, response_model=KeyFullOut
        )
        # Ends the grace period: an update of the credential, not its deletion
        @route_meta(entity_type='KEY', entity_uuid_param='key_uuid', action='UPDATE')
        def end_grace_period(key_uuid: UUID):
            key = key_service.end_grace_period(key_uuid)
            logger.info('Ended the grace period of key %s', key_uuid)
            return key

        @router.patch(
            '/keys/{key_uuid}/group', status_code=200, response_model=KeyFullOut
        )
        @route_meta(entity_type='KEY', entity_uuid_param='key_uuid', action='ASSIGN')
        def add_groups_to_key(
            key_uuid: UUID,
            key_group_in: KeyGroupIn,
            include_groups: bool = Query(False),
        ):
            return key_service.add_group_to_key(key_uuid, key_group_in, include_groups)

        @router.get(
            '/keys/{key_uuid}/associable-groups',
            status_code=200,
            response_model=list[GroupFullOut],
        )
        def get_associable_groups(
            key_uuid: UUID,
            include_routes: bool = Query(False),
            include_keys: bool = Query(False),
        ):
            return key_service.get_associable_groups(
                key_uuid, include_routes, include_keys
            )

        @router.post(
            '/keys/{key_uuid}/limits', status_code=201, response_model=KeyFullOut
        )
        @route_meta(entity_type='KEY', entity_uuid_param='key_uuid', action='ADD_LIMIT')
        def add_limits_to_key(
            key_uuid: UUID,
            limits_in: CredentialLimitsIn,
            include_groups: bool = Query(False),
        ):
            key = key_service.add_limits_to_key(key_uuid, limits_in, include_groups)
            logger.info('Added %s limit(s) to key %s', len(limits_in.limits), key_uuid)
            return key

        @router.get(
            '/keys/{key_uuid}/limits',
            status_code=200,
            response_model=list[CredentialLimitOut],
        )
        def get_limits_for_key(key_uuid: UUID):
            return key_service.get_limits_for_key(key_uuid)

        @router.patch(
            '/keys/{key_uuid}/limits/{limit_uuid}',
            status_code=200,
            response_model=CredentialLimitUpdatedOut,
        )
        @route_meta(entity_type='KEY', entity_uuid_param='key_uuid')
        def update_limit_value(
            key_uuid: UUID, limit_uuid: UUID, value_in: CredentialLimitValueIn
        ):
            return key_service.update_limit_value(key_uuid, limit_uuid, value_in)

        @router.delete(
            '/keys/{key_uuid}/limits/{limit_uuid}',
            status_code=200,
            response_model=CredentialLimitOut,
        )
        @route_meta(entity_type='KEY', entity_uuid_param='key_uuid')
        async def delete_limit_from_key(key_uuid: UUID, limit_uuid: UUID):
            limit = await key_service.delete_limit_from_key(key_uuid, limit_uuid)
            logger.info('Deleted limit %s from key %s', limit_uuid, key_uuid)
            return limit

        return router
