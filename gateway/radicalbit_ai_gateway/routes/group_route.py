import logging
from uuid import UUID

from fastapi import APIRouter, Query

from radicalbit_ai_gateway.models.auth_dto import (
    GroupFullOut,
    GroupIn,
    GroupRouteOut,
    GroupRoutesIn,
    KeyFullOut,
    KeysUuidIn,
)
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()

logger = logging.getLogger(app_config.log_config.logger_name)


class GroupRoute:
    @staticmethod
    def get_group_router(
        group_service: GroupService,
        project_service: ProjectService,
    ) -> APIRouter:
        router = APIRouter(tags=['group_api'])

        @router.post('/groups', status_code=201, response_model=GroupFullOut)
        def create_group(
            group_in: GroupIn,
        ):
            group = group_service.create_group(group_in)
            logger.info('Created group %s', group.uuid)
            return group

        @router.get('/groups', status_code=200, response_model=list[GroupFullOut])
        def get_all(
            include_routes: bool = Query(False), include_keys: bool = Query(False)
        ):
            return group_service.get_all(include_routes, include_keys)

        @router.get(
            '/groups/{group_uuid}', status_code=200, response_model=GroupFullOut
        )
        def get_group_by_uuid(
            group_uuid: UUID,
            include_routes: bool = Query(False),
            include_keys: bool = Query(False),
        ):
            return group_service.get_group_by_uuid(
                group_uuid, include_routes, include_keys
            )

        @router.patch(
            '/groups/{group_uuid}', status_code=200, response_model=GroupFullOut
        )
        def update_group(group_uuid: UUID, group_in: GroupIn):
            return group_service.update_group_name(group_uuid, group_in)

        @router.delete(
            '/groups/{group_uuid}', status_code=200, response_model=GroupFullOut
        )
        def delete_group(
            group_uuid: UUID,
            include_routes: bool = Query(False),
            include_keys: bool = Query(False),
        ):
            return group_service.delete_group(group_uuid, include_routes, include_keys)

        @router.patch(
            '/groups/{group_uuid}/projects/{project_uuid}/routes',
            status_code=201,
            response_model=GroupFullOut,
        )
        def add_project_route(
            group_uuid: UUID,
            project_uuid: UUID,
            group_route_in: GroupRoutesIn,
            include_routes: bool = Query(False),
            include_keys: bool = Query(False),
        ):
            project = project_service.get_by_uuid(project_uuid)
            return group_service.add_project_routes(
                group_uuid,
                project_uuid,
                project.name,
                group_route_in,
                include_routes,
                include_keys,
            )

        @router.delete(
            '/groups/{group_uuid}/projects/{project_uuid}/routes/{route_name}',
            status_code=200,
            response_model=GroupFullOut,
        )
        def remove_project_route(group_uuid: UUID, project_uuid: UUID, route_name: str):
            project = project_service.get_by_uuid(project_uuid)
            return group_service.remove_project_route(
                group_uuid, project_uuid, project.name, route_name
            )

        @router.patch(
            '/groups/{group_uuid}/keys', status_code=201, response_model=GroupFullOut
        )
        def add_key(
            group_uuid: UUID,
            key: KeysUuidIn,
            include_routes: bool = Query(False),
            include_keys: bool = Query(False),
        ):
            return group_service.add_keys(group_uuid, key, include_routes, include_keys)

        @router.delete(
            '/groups/{group_uuid}/keys/{key_uuid}',
            status_code=200,
            response_model=GroupFullOut,
        )
        def remove_key(group_uuid: UUID, key_uuid: UUID):
            return group_service.remove_key(group_uuid, key_uuid)

        @router.get(
            '/groups/{group_uuid}/associable-keys',
            status_code=200,
            response_model=list[KeyFullOut],
        )
        def get_associable_keys(group_uuid: UUID):
            return group_service.get_associable_keys(group_uuid)

        @router.get(
            '/groups/{group_uuid}/projects/{project_uuid}/associable-routes',
            status_code=200,
            response_model=list[GroupRouteOut],
        )
        def get_associable_routes(group_uuid: UUID, project_uuid: UUID):
            project = project_service.get_by_uuid(project_uuid)
            return group_service.get_associable_routes(group_uuid, project.name)

        return router
