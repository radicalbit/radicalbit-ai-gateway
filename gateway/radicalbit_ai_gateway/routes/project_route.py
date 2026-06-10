from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Request

from radicalbit_ai_gateway.models.auth_dto import (
    GroupFullOut,
    GroupsRouteOut,
    RouteGroupsIn,
)
from radicalbit_ai_gateway.models.project_dto import (
    GenerateConfigIn,
    GenerateConfigOut,
    ProjectConfigFileIn,
    ProjectFilter,
    ProjectIn,
    ProjectOut,
)
from radicalbit_ai_gateway.route_meta import route_meta
from radicalbit_ai_gateway.services.config_generator_service import (
    ConfigGeneratorService,
)
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()

logger = logging.getLogger(app_config.log_config.logger_name)


@dataclass
class ProjectRouteConfig:
    get_projects_fn: Callable[[Request, ProjectFilter | None], Any] | None = None
    get_project_fn: Callable[[Request, UUID], Any] | None = None
    list_response_model: type = field(default_factory=lambda: list[ProjectOut])
    item_response_model: type = field(default_factory=lambda: ProjectOut)


class ProjectRoute:
    @staticmethod
    def get_project_router(
        project_service: ProjectService,
        group_service: GroupService,
        register_project_routes: Callable[[UUID, str, str], Awaitable[None]]
        | None = None,
        deregister_project_routes: Callable[[UUID], Awaitable[None]] | None = None,
        config: ProjectRouteConfig | None = None,
        config_generator_service: ConfigGeneratorService | None = None,
    ) -> APIRouter:
        config = config or ProjectRouteConfig()
        get_projects_fn = config.get_projects_fn or (
            lambda _, f: project_service.get_all_filtered(f)
        )
        get_project_fn = config.get_project_fn or (
            lambda _, u: project_service.get_by_uuid(u)
        )
        router = APIRouter(tags=['project_api'])

        @router.post('/projects', status_code=201, response_model=ProjectOut)
        @route_meta(entity_type='PROJECT', response_uuid_field='uuid')
        def create_project(project_in: ProjectIn):
            project = project_service.create_project(project_in)
            logger.info('Created project %s', project.uuid)
            return project

        @router.get(
            '/projects', status_code=200, response_model=config.list_response_model
        )
        def get_all(
            request: Request,
            filter: ProjectFilter | None = Query(None),
        ):
            return get_projects_fn(request, filter)

        @router.get(
            '/projects/{project_uuid}',
            status_code=200,
            response_model=config.item_response_model,
        )
        def get_project_by_uuid(project_uuid: UUID, request: Request):
            return get_project_fn(request, project_uuid)

        @router.patch(
            '/projects/{project_uuid}/configs/{config_uuid}',
            status_code=200,
            response_model=ProjectOut,
        )
        @route_meta(entity_type='PROJECT', entity_uuid_param='project_uuid')
        def update_config(
            project_uuid: UUID, config_uuid: UUID, config_in: ProjectConfigFileIn
        ):
            project = project_service.update_config(
                project_uuid, config_uuid, config_in
            )
            logger.info('Updated config %s for project %s', config_uuid, project_uuid)
            return project

        @router.patch(
            '/projects/{project_uuid}/configs/{config_uuid}/approve',
            status_code=200,
            response_model=ProjectOut,
        )
        @route_meta(entity_type='PROJECT', entity_uuid_param='project_uuid')
        def approve_config(project_uuid: UUID, config_uuid: UUID):
            project = project_service.approve_config(project_uuid, config_uuid)
            logger.info('Approved config %s for project %s', config_uuid, project_uuid)
            return project

        @router.patch(
            '/projects/{project_uuid}/configs/{config_uuid}/cancel-approval',
            status_code=200,
            response_model=ProjectOut,
        )
        @route_meta(entity_type='PROJECT', entity_uuid_param='project_uuid')
        def cancel_approval(project_uuid: UUID, config_uuid: UUID):
            project = project_service.cancel_approval(project_uuid, config_uuid)
            logger.info(
                'Cancelled approval for config %s of project %s',
                config_uuid,
                project_uuid,
            )
            return project

        @router.patch(
            '/projects/{project_uuid}/configs/{config_uuid}/serve',
            status_code=200,
            response_model=ProjectOut,
        )
        @route_meta(entity_type='PROJECT', entity_uuid_param='project_uuid')
        async def serve_config(project_uuid: UUID, config_uuid: UUID):
            project = project_service.serve_config(project_uuid, config_uuid)
            # Swap: drop any routes from the previously served config, then
            # register the newly served one.
            if deregister_project_routes:
                await deregister_project_routes(project_uuid)
            served = next(
                (c for c in project.configs if c.uuid == project.served_config_uuid),
                None,
            )
            if register_project_routes and served and served.config_file:
                await register_project_routes(
                    project_uuid, project.name, served.config_file
                )
            logger.info('Served config %s for project %s', config_uuid, project_uuid)
            return project

        @router.post(
            '/projects/{project_uuid}/configs/{config_uuid}/generate-config',
            status_code=200,
            response_model=GenerateConfigOut,
        )
        @route_meta(entity_type='PROJECT', entity_uuid_param='project_uuid')
        async def generate_config(
            project_uuid: UUID, config_uuid: UUID, gen_in: GenerateConfigIn
        ):
            config = project_service.get_config(project_uuid, config_uuid)
            yaml_str = await config_generator_service.generate_config(
                gen_in.description, config.config_file
            )
            logger.info(
                'Generated config %s for project %s', config_uuid, project_uuid
            )
            return GenerateConfigOut(config_file=yaml_str)

        @router.patch(
            '/projects/{project_uuid}/configs/{config_uuid}/unserve',
            status_code=200,
            response_model=ProjectOut,
        )
        @route_meta(entity_type='PROJECT', entity_uuid_param='project_uuid')
        async def unserve_config(project_uuid: UUID, config_uuid: UUID):
            project = project_service.unserve_config(project_uuid, config_uuid)
            if deregister_project_routes:
                await deregister_project_routes(project_uuid)
            logger.info('Unserved config %s for project %s', config_uuid, project_uuid)
            return project

        @router.delete(
            '/projects/{project_uuid}',
            status_code=200,
            response_model=ProjectOut,
        )
        @route_meta(entity_type='PROJECT', entity_uuid_param='project_uuid')
        async def delete_project(project_uuid: UUID):
            project = project_service.delete_project(project_uuid)
            if deregister_project_routes and project.served_config_uuid:
                await deregister_project_routes(project_uuid)
            logger.info('Deleted project %s', project_uuid)
            return project

        @router.patch(
            '/projects/{project_uuid}/routes/{route_name}/groups',
            status_code=200,
            response_model=GroupsRouteOut,
        )
        @route_meta(
            entity_type='PROJECT', entity_uuid_param='project_uuid', action='ASSIGN'
        )
        def add_groups_to_project_route(
            project_uuid: UUID,
            route_name: str,
            route_groups_in: RouteGroupsIn,
            include_groups: bool = Query(False),
        ):
            project = project_service.get_by_uuid(project_uuid)
            return group_service.add_groups_to_project_route(
                project_uuid, project.name, route_name, route_groups_in, include_groups
            )

        @router.get(
            '/projects/{project_uuid}/routes/{route_name}/associable-groups',
            status_code=200,
            response_model=list[GroupFullOut],
        )
        def get_associable_groups_for_project_route(
            project_uuid: UUID,
            route_name: str,
            include_routes: bool = Query(False),
            include_keys: bool = Query(False),
        ):
            project = project_service.get_by_uuid(project_uuid)
            return group_service.get_associable_groups_for_project_route(
                project.name, route_name, include_routes, include_keys
            )

        return router
