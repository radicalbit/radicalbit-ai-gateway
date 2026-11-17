import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, File, Query, Request, Response, UploadFile
from fastapi.sse import EventSourceResponse
from starlette.responses import StreamingResponse

from radicalbit_ai_gateway.models.auth_dto import (
    GroupFullOut,
    GroupsRouteOut,
    RouteGroupsIn,
)
from radicalbit_ai_gateway.models.config_status import ConfigStatus
from radicalbit_ai_gateway.models.error_dto import error_responses
from radicalbit_ai_gateway.models.project_budget_limiting import (
    ProjectBudgetLimitConflictsOut,
    ProjectBudgetLimitOut,
    ProjectBudgetLimitsIn,
    ProjectBudgetLimitUpdatedOut,
    ProjectBudgetLimitValueIn,
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
from radicalbit_ai_gateway.utils.exceptions import ProjectConfigValidationError

app_config = get_app_config()

logger = logging.getLogger(app_config.log_config.logger_name)

MAX_IMPORT_BYTES = 2 * 1024 * 1024  # 2 MB
_ALLOWED_IMPORT_SUFFIXES = ('.yaml', '.yml')


@dataclass
class ProjectRouteConfig:
    get_projects_fn: Callable[[Request, ProjectFilter | None, bool], Any] | None = None
    get_project_fn: Callable[[Request, UUID, bool], Any] | None = None
    # The projects among the requested ones the caller may read consumption of
    filter_project_uuids_fn: Callable[[Request, list[UUID]], list[UUID]] | None = None
    list_response_model: type = field(default_factory=lambda: list[ProjectOut])
    item_response_model: type = field(default_factory=lambda: ProjectOut)


class ProjectRoute:
    @staticmethod
    def get_project_router(  # noqa: C901
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
            lambda _, f, include_limits: project_service.get_all_filtered(
                f, include_limits
            )
        )
        get_project_fn = config.get_project_fn or (
            lambda _, u, include_limits: project_service.get_by_uuid(u, include_limits)
        )
        filter_project_uuids_fn = config.filter_project_uuids_fn or (
            lambda _, uuids: uuids
        )
        router = APIRouter()
        projects = ['projects']
        configs = ['configs']

        @router.post(
            '/projects',
            status_code=201,
            response_model=ProjectOut,
            tags=projects,
            operation_id='projects_create',
            responses=error_responses(409),
        )
        @route_meta(entity_type='PROJECT', response_uuid_field='uuid')
        def create_project(project_in: ProjectIn):
            """Create a project, with two draft config slots (A and B)."""
            project = project_service.create_project(project_in)
            logger.info('Created project %s', project.uuid)
            return project

        @router.get(
            '/projects',
            status_code=200,
            response_model=config.list_response_model,
            tags=projects,
            operation_id='projects_list',
        )
        def get_all(
            request: Request,
            filter: ProjectFilter | None = Query(None),
            include_limits: bool = Query(False),
        ):
            """List the projects, optionally filtered."""
            return get_projects_fn(request, filter, include_limits)

        @router.get(
            '/projects/{project_uuid}',
            status_code=200,
            response_model=config.item_response_model,
            tags=projects,
            operation_id='projects_get',
            responses=error_responses(404),
        )
        def get_project_by_uuid(
            project_uuid: UUID,
            request: Request,
            include_limits: bool = Query(False),
        ):
            """Get a project with its two config slots."""
            return get_project_fn(request, project_uuid, include_limits)

        @router.patch(
            '/projects/{project_uuid}/configs/{config_uuid}',
            status_code=200,
            response_model=ProjectOut,
            tags=configs,
            operation_id='configs_save',
            responses=error_responses(400, 404, 409),
        )
        @route_meta(entity_type='PROJECT', entity_uuid_param='project_uuid')
        def update_config(
            project_uuid: UUID, config_uuid: UUID, config_in: ProjectConfigFileIn
        ):
            """Save a YAML configuration into a config slot that is not served."""
            project = project_service.update_config(
                project_uuid, config_uuid, config_in
            )
            logger.info('Updated config %s for project %s', config_uuid, project_uuid)
            return project

        @router.patch(
            '/projects/{project_uuid}/configs/{config_uuid}/approve',
            status_code=200,
            response_model=ProjectOut,
            tags=configs,
            operation_id='configs_approve',
            responses=error_responses(400, 404, 409),
        )
        @route_meta(entity_type='PROJECT', entity_uuid_param='project_uuid')
        def approve_config(project_uuid: UUID, config_uuid: UUID):
            """Request to publish a draft config: it becomes ready to serve."""
            project = project_service.approve_config(project_uuid, config_uuid)
            logger.info('Approved config %s for project %s', config_uuid, project_uuid)
            return project

        @router.patch(
            '/projects/{project_uuid}/configs/{config_uuid}/cancel-approval',
            status_code=200,
            response_model=ProjectOut,
            tags=configs,
            operation_id='configs_cancel_approval',
            responses=error_responses(404, 409),
        )
        @route_meta(entity_type='PROJECT', entity_uuid_param='project_uuid')
        def cancel_approval(project_uuid: UUID, config_uuid: UUID):
            """Cancel a request to publish: the config goes back to draft."""
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
            tags=configs,
            operation_id='configs_serve',
            responses=error_responses(400, 404, 409),
        )
        @route_meta(entity_type='PROJECT', entity_uuid_param='project_uuid')
        async def serve_config(project_uuid: UUID, config_uuid: UUID):
            """Publish an approved config: it replaces the one served, if any."""
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
            # Auto-cleanup on swap: drop group↔route associations whose route_name
            # is no longer present in the newly served config.
            removed = group_service.cleanup_orphaned_associations(
                project_uuid, project.name
            )
            logger.info(
                'Served config %s for project %s (removed %d orphaned associations)',
                config_uuid,
                project_uuid,
                removed,
            )
            return project

        @router.post(
            '/projects/{project_uuid}/configs/{config_uuid}/generate-config',
            status_code=200,
            response_model=GenerateConfigOut,
            tags=configs,
        )
        @route_meta(entity_type='PROJECT', entity_uuid_param='project_uuid')
        async def generate_config(
            project_uuid: UUID, config_uuid: UUID, gen_in: GenerateConfigIn
        ):
            config_slot = project_service.get_config(project_uuid, config_uuid)
            # A served slot is read-only: generating against it is pointless
            # since the result could not be saved back (see update_config).
            if config_slot.config_status == ConfigStatus.SERVED:
                raise ProjectConfigValidationError(
                    f'Config {config_uuid} is served and cannot be used to '
                    'generate a new configuration'
                )
            yaml_str = await config_generator_service.generate_config(
                gen_in.description, config_slot.config_file
            )
            logger.info('Generated config %s for project %s', config_uuid, project_uuid)
            return GenerateConfigOut(config_file=yaml_str)

        @router.get(
            '/projects/{project_uuid}/configs/{config_uuid}/export',
            status_code=200,
            tags=configs,
        )
        def export_config(project_uuid: UUID, config_uuid: UUID):
            content, filename = project_service.export_config(project_uuid, config_uuid)
            logger.info('Exported config %s for project %s', config_uuid, project_uuid)
            return Response(
                content=content,
                media_type='application/zip',
                headers={'Content-Disposition': f'attachment; filename="{filename}"'},
            )

        @router.get(
            '/projects/{project_uuid}/configs/export',
            status_code=200,
            tags=configs,
        )
        def export_all_configs(project_uuid: UUID):
            content, filename = project_service.export_all_configs(project_uuid)
            logger.info('Exported all configs for project %s', project_uuid)
            return Response(
                content=content,
                media_type='application/zip',
                headers={'Content-Disposition': f'attachment; filename="{filename}"'},
            )

        @router.patch(
            '/projects/{project_uuid}/configs/{config_uuid}/import',
            status_code=200,
            response_model=ProjectOut,
            tags=configs,
            operation_id='configs_upload',
            responses=error_responses(400, 404, 409),
        )
        @route_meta(entity_type='PROJECT', entity_uuid_param='project_uuid')
        async def import_config(
            project_uuid: UUID,
            config_uuid: UUID,
            # format: binary, so that generated clients send it as a file
            file: UploadFile = File(..., json_schema_extra={'format': 'binary'}),
        ):
            """Upload a .yaml or .yml file (2 MB at most) into a config slot that is not served."""
            filename = file.filename or ''
            if not filename.lower().endswith(_ALLOWED_IMPORT_SUFFIXES):
                raise ProjectConfigValidationError(
                    'Only .yaml or .yml files can be imported'
                )
            if file.size is not None and file.size > MAX_IMPORT_BYTES:
                raise ProjectConfigValidationError(
                    f'Uploaded file exceeds the {MAX_IMPORT_BYTES // (1024 * 1024)} MB limit'
                )
            content = await file.read()
            project = project_service.import_config(project_uuid, config_uuid, content)
            logger.info('Imported config %s for project %s', config_uuid, project_uuid)
            return project

        @router.patch(
            '/projects/{project_uuid}/configs/{config_uuid}/unserve',
            status_code=200,
            response_model=ProjectOut,
            tags=configs,
            operation_id='configs_unserve',
            responses=error_responses(404, 409),
        )
        @route_meta(entity_type='PROJECT', entity_uuid_param='project_uuid')
        async def unserve_config(project_uuid: UUID, config_uuid: UUID):
            """Stop serving the served config: the project serves no routes."""
            project = project_service.unserve_config(project_uuid, config_uuid)
            if deregister_project_routes:
                await deregister_project_routes(project_uuid)
            logger.info('Unserved config %s for project %s', config_uuid, project_uuid)
            return project

        @router.delete(
            '/projects/{project_uuid}',
            status_code=200,
            response_model=ProjectOut,
            tags=projects,
        )
        @route_meta(entity_type='PROJECT', entity_uuid_param='project_uuid')
        async def delete_project(project_uuid: UUID):
            project = await project_service.delete_project(project_uuid)
            if deregister_project_routes and project.served_config_uuid:
                await deregister_project_routes(project_uuid)
            logger.info('Deleted project %s', project_uuid)
            return project

        @router.patch(
            '/projects/{project_uuid}/routes/{route_name}/groups',
            status_code=200,
            response_model=GroupsRouteOut,
            tags=projects,
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
            tags=projects,
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

        @router.get(
            '/projects/budget-limits/stream',
            status_code=200,
            response_class=EventSourceResponse,
            tags=projects,
        )
        async def stream_budget_limits_consumption(
            request: Request,
            projects: Annotated[list[UUID] | None, Query()] = None,
        ) -> StreamingResponse:
            while True:
                visible = filter_project_uuids_fn(request, projects or [])
                consumption = await project_service.get_budget_limits_consumption(
                    visible
                )
                yield {
                    limit_uuid: bar.model_dump(by_alias=True)
                    for limit_uuid, bar in consumption.items()
                }
                await asyncio.sleep(10)

        @router.post(
            '/projects/{project_uuid}/budget-limits',
            status_code=201,
            response_model=list[ProjectBudgetLimitOut],
            tags=projects,
        )
        @route_meta(
            entity_type='PROJECT',
            entity_uuid_param='project_uuid',
            action='ADD_BUDGET_LIMIT',
        )
        def add_budget_limits_to_project(
            project_uuid: UUID, limits_in: ProjectBudgetLimitsIn
        ):
            limits = project_service.add_budget_limits_to_project(
                project_uuid, limits_in
            )
            logger.info(
                'Added %s budget limit(s) to project %s',
                len(limits_in.limits),
                project_uuid,
            )
            return limits

        @router.get(
            '/projects/{project_uuid}/budget-limits',
            status_code=200,
            response_model=list[ProjectBudgetLimitOut],
            tags=projects,
        )
        def get_budget_limits_for_project(project_uuid: UUID):
            return project_service.get_budget_limits_for_project(project_uuid)

        @router.get(
            '/projects/{project_uuid}/budget-limits/conflicts',
            status_code=200,
            response_model=ProjectBudgetLimitConflictsOut,
            tags=projects,
        )
        def get_budget_limit_conflicts(project_uuid: UUID):
            return project_service.get_budget_limit_conflicts(project_uuid)

        @router.patch(
            '/projects/{project_uuid}/budget-limits/{limit_uuid}',
            status_code=200,
            response_model=ProjectBudgetLimitUpdatedOut,
            tags=projects,
        )
        @route_meta(entity_type='PROJECT', entity_uuid_param='project_uuid')
        def update_budget_limit_value(
            project_uuid: UUID, limit_uuid: UUID, value_in: ProjectBudgetLimitValueIn
        ):
            return project_service.update_budget_limit_value(
                project_uuid, limit_uuid, value_in
            )

        @router.delete(
            '/projects/{project_uuid}/budget-limits/{limit_uuid}',
            status_code=200,
            response_model=ProjectBudgetLimitOut,
            tags=projects,
        )
        @route_meta(entity_type='PROJECT', entity_uuid_param='project_uuid')
        async def delete_budget_limit_from_project(
            project_uuid: UUID, limit_uuid: UUID
        ):
            limit = await project_service.delete_budget_limit_from_project(
                project_uuid, limit_uuid
            )
            logger.info(
                'Deleted budget limit %s from project %s', limit_uuid, project_uuid
            )
            return limit

        return router
