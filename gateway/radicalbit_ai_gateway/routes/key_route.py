import logging
from uuid import UUID

from fastapi import APIRouter, Query

from radicalbit_ai_gateway.models.auth_dto import (
    GroupFullOut,
    KeyFullOut,
    KeyGroupIn,
    KeyIn,
)
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
            key_in: KeyIn,
        ):
            key = key_service.create_key(key_in)
            logger.info('Created key %s', key.uuid)
            return key

        @router.get('/keys', status_code=200, response_model=list[KeyFullOut])
        def get_all(include_groups: bool = False, only_unassigned: bool = Query(False)):
            return key_service.get_all(include_groups, only_unassigned)

        @router.get('/keys/{key_uuid}', status_code=200, response_model=KeyFullOut)
        def get_key_by_uuid(key_uuid: UUID, include_groups: bool = False):
            return key_service.get_key_by_uuid(key_uuid, include_groups)

        @router.patch('/keys/{key_uuid}', status_code=200, response_model=KeyFullOut)
        @route_meta(entity_type='KEY', entity_uuid_param='key_uuid')
        def update_key(key_uuid: UUID, key_in: KeyIn):
            return key_service.update_key_name(key_uuid, key_in)

        @router.delete('/keys/{key_uuid}', status_code=200, response_model=KeyFullOut)
        @route_meta(entity_type='KEY', entity_uuid_param='key_uuid')
        def delete_key(key_uuid: UUID, include_groups: bool = Query(False)):
            return key_service.delete_key(key_uuid, include_groups)

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

        return router
