from collections.abc import Iterable
import io
import logging
import re
from uuid import UUID
import zipfile

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
import yaml

from radicalbit_ai_gateway.db.dao.project_budget_limit_dao import ProjectBudgetLimitDAO
from radicalbit_ai_gateway.db.dao.project_config_dao import ProjectConfigDAO
from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO
from radicalbit_ai_gateway.db.tables.project_config_table import ProjectConfig
from radicalbit_ai_gateway.db.tables.project_table import Project
from radicalbit_ai_gateway.limiting.limits import shared_limits
from radicalbit_ai_gateway.limiting.windows import project_window
from radicalbit_ai_gateway.models.config_slot import Slot
from radicalbit_ai_gateway.models.config_status import ConfigStatus
from radicalbit_ai_gateway.models.event_dto import WindowProgressBarDTO
from radicalbit_ai_gateway.models.project_budget_limiting import (
    ProjectBudgetLimitConflictsOut,
    ProjectBudgetLimitDraftConflictOut,
    ProjectBudgetLimitOut,
    ProjectBudgetLimitsIn,
    ProjectBudgetLimitUpdatedOut,
    ProjectBudgetLimitValueIn,
)
from radicalbit_ai_gateway.models.project_dto import (
    ConfigListFilter,
    ConfigSlotOut,
    ProjectConfigFileIn,
    ProjectFilter,
    ProjectIn,
    ProjectOut,
)
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.exceptions import (
    ProjectAlreadyExistsError,
    ProjectBudgetLimitAlreadyExistsError,
    ProjectBudgetLimitConflictError,
    ProjectBudgetLimitNotFoundError,
    ProjectConfigStateError,
    ProjectConfigValidationError,
    ProjectInternalError,
    ProjectNotFoundError,
)
from radicalbit_ai_gateway.utils.yaml_utils import (
    find_route_budgets,
    get_default_config_template,
    validate_gateway_config,
)

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


def _sanitize_filename(name: str) -> str:
    sanitized = re.sub(r'[^A-Za-z0-9_-]+', '_', name).strip('_')
    return sanitized or 'config'


def route_budget_conflicts(
    configs: Iterable[ProjectConfig],
) -> ProjectBudgetLimitConflictsOut:
    published: list[str] = []
    draft: list[str] = []
    budget_routing: list[str] = []
    draft_configs: list[ProjectBudgetLimitDraftConflictOut] = []
    for config in configs:
        if not config.config_file:
            continue
        try:
            budgets = find_route_budgets(config.config_file)
        except (ValidationError, TypeError, ValueError, yaml.YAMLError):
            # Not a valid configuration yet (e.g. the seeded template): it
            # can't be published, so it conflicts with nothing
            continue
        if config.config_status == ConfigStatus.SERVED.value:
            published += budgets.budget_limiting
        else:
            draft += budgets.budget_limiting
            if budgets.budget_limiting:
                draft_configs.append(
                    ProjectBudgetLimitDraftConflictOut(
                        config_uuid=config.uuid,
                        slot=config.slot,
                        routes=list(dict.fromkeys(budgets.budget_limiting)),
                    )
                )
        budget_routing += budgets.budget_routing
    return ProjectBudgetLimitConflictsOut(
        published=list(dict.fromkeys(published)),
        draft=list(dict.fromkeys(draft)),
        budget_routing=list(dict.fromkeys(budget_routing)),
        draft_configs=sorted(draft_configs, key=lambda c: c.slot),
    )


class ProjectService:
    def __init__(
        self,
        project_dao: ProjectDAO,
        project_config_dao: ProjectConfigDAO,
        project_budget_limit_dao: ProjectBudgetLimitDAO,
    ):
        self.project_dao = project_dao
        self.project_config_dao = project_config_dao
        self.project_budget_limit_dao = project_budget_limit_dao

    async def _get_project_or_raise(self, project_uuid: UUID) -> Project:
        project = await self.project_dao.get_by_uuid(project_uuid)
        if not project:
            raise ProjectNotFoundError(f'Project with UUID {project_uuid} not found')
        return project

    async def _get_config_or_raise(
        self, project_uuid: UUID, config_uuid: UUID
    ) -> ProjectConfig:
        config = await self.project_config_dao.get_by_uuid(config_uuid)
        if not config or config.project_uuid != project_uuid:
            raise ProjectNotFoundError(
                f'Config {config_uuid} not found for project {project_uuid}'
            )
        return config

    async def _build_out(self, project: Project) -> ProjectOut:
        configs = list(await self.project_config_dao.list_by_project(project.uuid))
        return ProjectOut.from_project(project, configs)

    async def _build_out_with_limits(self, project: Project) -> ProjectOut:
        configs = list(await self.project_config_dao.list_by_project(project.uuid))
        limits = [
            ProjectBudgetLimitOut.from_project_budget_limit(limit)
            for limit in await self.project_budget_limit_dao.get_by_project_uuid(
                project.uuid
            )
        ]
        return ProjectOut.from_project(
            project,
            configs,
            limits=limits,
            route_budgets=route_budget_conflicts(configs),
        )

    async def _build_out_or_raise(self, project_uuid: UUID) -> ProjectOut:
        project = await self.project_dao.get_by_uuid(project_uuid)
        if not project:
            raise ProjectInternalError(
                f'Failed to fetch updated project {project_uuid}'
            )
        return await self._build_out(project)

    async def create_project(self, project_in: ProjectIn) -> ProjectOut:
        template = get_default_config_template()
        try:
            project = project_in.to_project()
            # Seed both slots atomically with the project so the response
            # always carries exactly 2 configs (never a partial project).
            inserted = await self.project_dao.insert_with_configs(
                project,
                [
                    (Slot.A, template, ConfigStatus.DRAFT),
                    (Slot.B, template, ConfigStatus.DRAFT),
                ],
            )
        except IntegrityError as e:
            if 'uq_project_NAME' in str(e.orig) or 'NAME' in str(e.orig):
                raise ProjectAlreadyExistsError(
                    f'Project with name "{project_in.name}" already exists'
                ) from e
            raise ProjectInternalError(
                f'An error occurred while creating the project: {e}'
            ) from e

        return await self._build_out_or_raise(inserted.uuid)

    async def _reject_route_budget_limiting_conflict(
        self, project_uuid: UUID, yaml_str: str
    ) -> None:
        routes = find_route_budgets(yaml_str).budget_limiting
        if not routes:
            return
        if await self.project_budget_limit_dao.get_by_project_uuid(project_uuid):
            raise ProjectConfigValidationError(
                'The project has a budget: routes cannot configure '
                f'budget_limiting: {", ".join(routes)}',
                routes=routes,
            )

    async def update_config(
        self, project_uuid: UUID, config_uuid: UUID, config_in: ProjectConfigFileIn
    ) -> ProjectOut:
        validate_gateway_config(config_in.config_file, check_secrets=True)
        await self._reject_route_budget_limiting_conflict(
            project_uuid, config_in.config_file
        )

        config = await self._get_config_or_raise(project_uuid, config_uuid)
        if config.config_status == ConfigStatus.SERVED.value:
            raise ProjectConfigStateError(
                f'Config {config_uuid} is served and cannot be edited',
                'config_served_not_editable',
            )

        rows_updated = await self.project_config_dao.update_config_file(
            config_uuid, config_in.config_file
        )
        if rows_updated == 0:
            raise ProjectNotFoundError(f'Config {config_uuid} not found')

        return await self._build_out_or_raise(project_uuid)

    async def approve_config(self, project_uuid: UUID, config_uuid: UUID) -> ProjectOut:
        config = await self._get_config_or_raise(project_uuid, config_uuid)

        if config.config_status != ConfigStatus.DRAFT.value or not config.config_file:
            raise ProjectConfigStateError(
                f'Config {config_uuid} has no draft configuration to approve',
                'config_no_draft_to_approve',
            )

        validate_gateway_config(config.config_file, check_secrets=True)
        await self._reject_route_budget_limiting_conflict(
            project_uuid, config.config_file
        )

        await self.project_config_dao.set_status(
            config_uuid, ConfigStatus.READY_TO_SERVE
        )
        return await self._build_out_or_raise(project_uuid)

    async def cancel_approval(
        self, project_uuid: UUID, config_uuid: UUID
    ) -> ProjectOut:
        config = await self._get_config_or_raise(project_uuid, config_uuid)

        if config.config_status != ConfigStatus.READY_TO_SERVE.value:
            raise ProjectConfigStateError(
                f'Config {config_uuid} is not in READY_TO_SERVE state',
                'config_not_ready_to_serve',
            )

        await self.project_config_dao.set_status(config_uuid, ConfigStatus.DRAFT)
        return await self._build_out_or_raise(project_uuid)

    async def serve_config(self, project_uuid: UUID, config_uuid: UUID) -> ProjectOut:
        config = await self._get_config_or_raise(project_uuid, config_uuid)

        if not config.config_file:
            raise ProjectConfigValidationError(
                f'Config {config_uuid} has no configuration to serve'
            )
        if config.config_status != ConfigStatus.READY_TO_SERVE.value:
            raise ProjectConfigStateError(
                f'Config {config_uuid} must be approved before serving',
                'config_not_approved',
            )

        validate_gateway_config(config.config_file, check_secrets=True)
        await self._reject_route_budget_limiting_conflict(
            project_uuid, config.config_file
        )

        served = await self.project_config_dao.serve(config_uuid)
        if served is None:
            raise ProjectInternalError(
                f'Failed to serve config {config_uuid} for project {project_uuid}'
            )
        return await self._build_out_or_raise(project_uuid)

    async def unserve_config(self, project_uuid: UUID, config_uuid: UUID) -> ProjectOut:
        config = await self._get_config_or_raise(project_uuid, config_uuid)

        if config.config_status != ConfigStatus.SERVED.value:
            raise ProjectConfigStateError(
                f'Config {config_uuid} is not served', 'config_not_served'
            )

        rows_updated = await self.project_config_dao.unserve(config_uuid)
        if rows_updated == 0:
            raise ProjectInternalError(f'Failed to unserve config {config_uuid}')
        return await self._build_out_or_raise(project_uuid)

    async def delete_project(self, project_uuid: UUID) -> ProjectOut:
        project = await self._get_project_or_raise(project_uuid)

        # Build the response before deletion so the caller can still see the
        # served config (e.g. to deregister its routes).
        out = await self._build_out(project)

        served = await self.project_config_dao.get_served_by_project(project_uuid)
        if served is not None:
            await self.project_config_dao.unserve(served.uuid)

        await self.project_config_dao.soft_delete_by_project(project_uuid)
        await self.project_dao.soft_delete(project_uuid)

        # The project row is soft-deleted, so the table's ON DELETE CASCADE
        # FK never fires — budget limits must be cleaned up explicitly.
        limits = await self.project_budget_limit_dao.get_by_project_uuid(project_uuid)
        if limits:
            await self.project_budget_limit_dao.delete_by_project_uuid(project_uuid)
            await self._clear_budget_limit_counters(project_uuid, limits)

        return out

    async def get_by_uuid(self, project_uuid: UUID) -> ProjectOut:
        return await self._build_out(await self._get_project_or_raise(project_uuid))

    async def get_by_uuid_with_limits(self, project_uuid: UUID) -> ProjectOut:
        """Return the project with its budget limits and its route budgets."""
        return await self._build_out_with_limits(
            await self._get_project_or_raise(project_uuid)
        )

    async def get_config(self, project_uuid: UUID, config_uuid: UUID) -> ConfigSlotOut:
        return ConfigSlotOut.from_config(
            await self._get_config_or_raise(project_uuid, config_uuid)
        )

    @staticmethod
    def _config_entry_name(project_name: str, config: ProjectConfig) -> str:
        status_label = (
            'served' if config.config_status == ConfigStatus.SERVED.value else 'draft'
        )
        return _sanitize_filename(
            f'{project_name}_config_{Slot(config.slot).value}_{status_label}'
        )

    @staticmethod
    def _build_configs_zip(
        project_name: str, configs: list[ProjectConfig]
    ) -> tuple[bytes, str]:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for config in configs:
                entry = ProjectService._config_entry_name(project_name, config)
                archive.writestr(f'{entry}.yaml', config.config_file)
        zip_name = _sanitize_filename(f'{project_name}_config')
        return buffer.getvalue(), f'{zip_name}.zip'

    async def export_config(
        self, project_uuid: UUID, config_uuid: UUID
    ) -> tuple[bytes, str]:
        project = await self._get_project_or_raise(project_uuid)
        config = await self._get_config_or_raise(project_uuid, config_uuid)
        if not config.config_file:
            raise ProjectConfigValidationError(
                f'Config {config_uuid} has no configuration to export'
            )
        return self._build_configs_zip(project.name, [config])

    async def export_all_configs(self, project_uuid: UUID) -> tuple[bytes, str]:
        project = await self._get_project_or_raise(project_uuid)
        configs = [
            config
            for config in await self.project_config_dao.list_by_project(project_uuid)
            if config.config_file
        ]
        if not configs:
            raise ProjectConfigValidationError(
                f'Project {project_uuid} has no configuration to export'
            )
        return self._build_configs_zip(project.name, configs)

    async def import_config(
        self, project_uuid: UUID, config_uuid: UUID, content: bytes
    ) -> ProjectOut:
        await self._get_project_or_raise(project_uuid)
        config = await self._get_config_or_raise(project_uuid, config_uuid)
        if config.config_status == ConfigStatus.SERVED.value:
            raise ProjectConfigStateError(
                f'Config {config_uuid} is served and cannot be overwritten by import',
                'config_served_not_importable',
            )
        try:
            config_file = content.decode('utf-8')
        except UnicodeDecodeError as e:
            raise ProjectConfigValidationError(
                'Uploaded file is not valid UTF-8 text'
            ) from e

        validate_gateway_config(config_file, check_secrets=True)
        await self._reject_route_budget_limiting_conflict(project_uuid, config_file)

        rows_updated = await self.project_config_dao.update_config_file(
            config_uuid, config_file
        )
        if rows_updated == 0:
            raise ProjectNotFoundError(f'Config {config_uuid} not found')
        return await self._build_out_or_raise(project_uuid)

    async def add_budget_limits_to_project(
        self, project_uuid: UUID, limits_in: ProjectBudgetLimitsIn
    ) -> list[ProjectBudgetLimitOut]:
        project = await self._get_project_or_raise(project_uuid)

        served = await self.project_config_dao.get_served_by_project(project_uuid)
        routes = (
            find_route_budgets(served.config_file).budget_limiting
            if served and served.config_file
            else []
        )
        if routes:
            raise ProjectBudgetLimitConflictError(
                f'Project "{project.name}" has published routes with '
                f'budget_limiting configured ({", ".join(routes)}); remove them '
                'before assigning a project-level budget limit',
                routes=routes,
            )

        try:
            inserted = await self.project_budget_limit_dao.insert_many(
                limits_in.to_project_budget_limits(project_uuid)
            )
        except IntegrityError as e:
            if 'uq_project_budget_limit_PROJECT_UUID_ALGORITHM_WINDOW_SIZE' in str(
                e.orig
            ):
                raise ProjectBudgetLimitAlreadyExistsError(
                    f'Project "{project.name}" already has a budget limit with '
                    'the same algorithm and window as one of the requested ones'
                ) from e
            raise ProjectInternalError(
                f'An error occurred while adding the budget limits: {e}'
            ) from e
        except Exception as e:
            raise ProjectInternalError(
                f'An error occurred while adding the budget limits: {e}'
            ) from e
        return [
            ProjectBudgetLimitOut.from_project_budget_limit(limit) for limit in inserted
        ]

    async def get_budget_limit_conflicts(
        self, project_uuid: UUID
    ) -> ProjectBudgetLimitConflictsOut:
        await self._get_project_or_raise(project_uuid)
        return route_budget_conflicts(
            await self.project_config_dao.list_by_project(project_uuid)
        )

    async def get_budget_limits_for_project(
        self, project_uuid: UUID
    ) -> list[ProjectBudgetLimitOut]:
        await self._get_project_or_raise(project_uuid)
        return [
            ProjectBudgetLimitOut.from_project_budget_limit(limit)
            for limit in await self.project_budget_limit_dao.get_by_project_uuid(
                project_uuid
            )
        ]

    async def get_budget_limits_consumption(
        self, project_uuids: list[UUID]
    ) -> dict[str, WindowProgressBarDTO]:
        """Consumption of every budget of *project_uuids*, keyed by limit uuid:
        the counters requests write, read without consuming them.
        """
        windows = {}
        for row in await self.project_budget_limit_dao.get_all_by_project_uuids(
            project_uuids
        ):
            limit = ProjectBudgetLimitOut.from_project_budget_limit(row)
            windows[str(limit.uuid)] = project_window(
                str(row.project_uuid), limit.algorithm, limit.window_size, limit.value
            )
        return await shared_limits.consumption(windows)

    async def update_budget_limit_value(
        self,
        project_uuid: UUID,
        limit_uuid: UUID,
        value_in: ProjectBudgetLimitValueIn,
    ) -> ProjectBudgetLimitUpdatedOut:
        await self._get_project_or_raise(project_uuid)
        limit = await self.project_budget_limit_dao.get_by_uuid(limit_uuid)
        if not limit or limit.project_uuid != project_uuid:
            raise ProjectBudgetLimitNotFoundError(
                f'Budget limit {limit_uuid} not found for project {project_uuid}'
            )
        previous_value = float(limit.max_value)
        await self.project_budget_limit_dao.update_max_value(limit_uuid, value_in.value)
        logger.info(
            'Budget limit %s of project %s: max %s -> %s',
            limit_uuid,
            project_uuid,
            previous_value,
            value_in.value,
        )
        updated = await self.project_budget_limit_dao.get_by_uuid(limit_uuid)
        return ProjectBudgetLimitUpdatedOut(
            **ProjectBudgetLimitOut.from_project_budget_limit(updated).model_dump(),
            previous_value=previous_value,
        )

    async def delete_budget_limit_from_project(
        self, project_uuid: UUID, limit_uuid: UUID
    ) -> ProjectBudgetLimitOut:
        await self._get_project_or_raise(project_uuid)
        limit = await self.project_budget_limit_dao.get_by_uuid(limit_uuid)
        if not limit or limit.project_uuid != project_uuid:
            raise ProjectBudgetLimitNotFoundError(
                f'Budget limit {limit_uuid} not found for project {project_uuid}'
            )
        # Build the response before deletion so the caller can still see it.
        out = ProjectBudgetLimitOut.from_project_budget_limit(limit)
        await self.project_budget_limit_dao.delete_by_uuid(limit_uuid)
        await self._clear_budget_limit_counters(project_uuid, [limit])
        return out

    @staticmethod
    async def _clear_budget_limit_counters(project_uuid: UUID, limits) -> None:
        """Best-effort: the DB rows are already gone, that's what matters."""
        for limit in limits:
            try:
                await shared_limits.clear(
                    project_window(
                        str(project_uuid), limit.algorithm, limit.window_size
                    )
                )
            except Exception:
                logger.exception(
                    'Failed to clear the budget limit counter for limit %s on '
                    'project %s',
                    limit.uuid,
                    project_uuid,
                )

    async def validate_exists(self, project_uuid: UUID) -> None:
        if not await self.project_dao.get_by_uuid(project_uuid):
            raise ProjectNotFoundError(f'Project with UUID {project_uuid} not found')

    async def get_all(self) -> list[ProjectOut]:
        return [
            await self._build_out(project)
            for project in await self.project_dao.get_all()
        ]

    async def get_all_filtered(
        self,
        project_filter: ProjectFilter | None = None,
        include_limits: bool = False,
    ) -> list[ProjectOut]:
        projects = await self.project_dao.get_all_filtered(project_filter)
        if not include_limits:
            return [await self._build_out(project) for project in projects]
        return [await self._build_out_with_limits(project) for project in projects]

    async def get_configs(
        self, config_filter: ConfigListFilter | None = None
    ) -> list[ProjectOut]:
        status = config_filter.to_config_status() if config_filter else None
        # "Draft" must exclude EMPTY slots (freshly seeded template with a NULL
        # updated_at), otherwise it would match every project since a DRAFT slot
        # always exists.
        exclude_empty = config_filter == ConfigListFilter.DRAFT
        projects = await self.project_dao.get_all_by_config_status(
            status, exclude_empty=exclude_empty
        )
        return [await self._build_out(project) for project in projects]

    async def get_all_active(self) -> list[ProjectOut]:
        projects = await self.project_dao.get_all_with_config()
        return [await self._build_out(project) for project in projects]
