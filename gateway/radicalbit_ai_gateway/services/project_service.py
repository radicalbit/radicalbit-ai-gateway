import io
import re
from uuid import UUID
import zipfile

from sqlalchemy.exc import IntegrityError

from radicalbit_ai_gateway.db.dao.project_budget_limit_dao import ProjectBudgetLimitDAO
from radicalbit_ai_gateway.db.dao.project_config_dao import ProjectConfigDAO
from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO
from radicalbit_ai_gateway.db.tables.project_config_table import ProjectConfig
from radicalbit_ai_gateway.db.tables.project_table import Project
from radicalbit_ai_gateway.models.config_slot import Slot
from radicalbit_ai_gateway.models.config_status import ConfigStatus
from radicalbit_ai_gateway.models.project_budget_limiting import (
    ProjectBudgetLimitOut,
    ProjectBudgetLimitsIn,
)
from radicalbit_ai_gateway.models.project_dto import (
    ConfigListFilter,
    ConfigSlotOut,
    ProjectConfigFileIn,
    ProjectFilter,
    ProjectIn,
    ProjectOut,
)
from radicalbit_ai_gateway.utils.exceptions import (
    ProjectAlreadyExistsError,
    ProjectBudgetLimitAlreadyExistsError,
    ProjectBudgetLimitConflictError,
    ProjectConfigValidationError,
    ProjectInternalError,
    ProjectNotFoundError,
)
from radicalbit_ai_gateway.utils.yaml_utils import (
    config_has_route_budget_limiting,
    get_default_config_template,
    validate_gateway_config,
)


def _sanitize_filename(name: str) -> str:
    sanitized = re.sub(r'[^A-Za-z0-9_-]+', '_', name).strip('_')
    return sanitized or 'config'


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

    def _get_project_or_raise(self, project_uuid: UUID) -> Project:
        project = self.project_dao.get_by_uuid(project_uuid)
        if not project:
            raise ProjectNotFoundError(f'Project with UUID {project_uuid} not found')
        return project

    def _get_config_or_raise(
        self, project_uuid: UUID, config_uuid: UUID
    ) -> ProjectConfig:
        config = self.project_config_dao.get_by_uuid(config_uuid)
        if not config or config.project_uuid != project_uuid:
            raise ProjectNotFoundError(
                f'Config {config_uuid} not found for project {project_uuid}'
            )
        return config

    def _build_out(self, project: Project, include_limits: bool = False) -> ProjectOut:
        configs = list(self.project_config_dao.list_by_project(project.uuid))
        limit = None
        if include_limits:
            found = self.project_budget_limit_dao.get_by_project_uuid(project.uuid)
            if found:
                limit = ProjectBudgetLimitOut.from_project_budget_limit(found[0])
        return ProjectOut.from_project(project, configs, limits=limit)

    def _build_out_or_raise(
        self, project_uuid: UUID, include_limits: bool = False
    ) -> ProjectOut:
        project = self.project_dao.get_by_uuid(project_uuid)
        if not project:
            raise ProjectInternalError(
                f'Failed to fetch updated project {project_uuid}'
            )
        return self._build_out(project, include_limits)

    def create_project(self, project_in: ProjectIn) -> ProjectOut:
        template = get_default_config_template()
        try:
            project = project_in.to_project()
            # Seed both slots atomically with the project so the response
            # always carries exactly 2 configs (never a partial project).
            inserted = self.project_dao.insert_with_configs(
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

        return self._build_out_or_raise(inserted.uuid)

    def _reject_route_budget_limiting_conflict(
        self, project_uuid: UUID, yaml_str: str
    ) -> None:
        if not config_has_route_budget_limiting(yaml_str):
            return
        if self.project_budget_limit_dao.get_by_project_uuid(project_uuid):
            raise ProjectConfigValidationError(
                f'Project {project_uuid} already has a budget limit assigned; '
                'routes cannot configure budget_limiting'
            )

    def update_config(
        self, project_uuid: UUID, config_uuid: UUID, config_in: ProjectConfigFileIn
    ) -> ProjectOut:
        validate_gateway_config(config_in.config_file, check_secrets=True)
        self._reject_route_budget_limiting_conflict(project_uuid, config_in.config_file)

        config = self._get_config_or_raise(project_uuid, config_uuid)
        if config.config_status == ConfigStatus.SERVED.value:
            raise ProjectConfigValidationError(
                f'Config {config_uuid} is served and cannot be edited'
            )

        rows_updated = self.project_config_dao.update_config_file(
            config_uuid, config_in.config_file
        )
        if rows_updated == 0:
            raise ProjectNotFoundError(f'Config {config_uuid} not found')

        return self._build_out_or_raise(project_uuid)

    def approve_config(self, project_uuid: UUID, config_uuid: UUID) -> ProjectOut:
        config = self._get_config_or_raise(project_uuid, config_uuid)

        if config.config_status != ConfigStatus.DRAFT.value or not config.config_file:
            raise ProjectConfigValidationError(
                f'Config {config_uuid} has no draft configuration to approve'
            )

        validate_gateway_config(config.config_file, check_secrets=True)
        self._reject_route_budget_limiting_conflict(project_uuid, config.config_file)

        self.project_config_dao.set_status(config_uuid, ConfigStatus.READY_TO_SERVE)
        return self._build_out_or_raise(project_uuid)

    def cancel_approval(self, project_uuid: UUID, config_uuid: UUID) -> ProjectOut:
        config = self._get_config_or_raise(project_uuid, config_uuid)

        if config.config_status != ConfigStatus.READY_TO_SERVE.value:
            raise ProjectConfigValidationError(
                f'Config {config_uuid} is not in READY_TO_SERVE state'
            )

        self.project_config_dao.set_status(config_uuid, ConfigStatus.DRAFT)
        return self._build_out_or_raise(project_uuid)

    def serve_config(self, project_uuid: UUID, config_uuid: UUID) -> ProjectOut:
        config = self._get_config_or_raise(project_uuid, config_uuid)

        if not config.config_file:
            raise ProjectConfigValidationError(
                f'Config {config_uuid} has no configuration to serve'
            )
        if config.config_status != ConfigStatus.READY_TO_SERVE.value:
            raise ProjectConfigValidationError(
                f'Config {config_uuid} must be approved before serving'
            )

        validate_gateway_config(config.config_file, check_secrets=True)
        self._reject_route_budget_limiting_conflict(project_uuid, config.config_file)

        served = self.project_config_dao.serve(config_uuid)
        if served is None:
            raise ProjectInternalError(
                f'Failed to serve config {config_uuid} for project {project_uuid}'
            )
        return self._build_out_or_raise(project_uuid)

    def unserve_config(self, project_uuid: UUID, config_uuid: UUID) -> ProjectOut:
        config = self._get_config_or_raise(project_uuid, config_uuid)

        if config.config_status != ConfigStatus.SERVED.value:
            raise ProjectConfigValidationError(f'Config {config_uuid} is not served')

        rows_updated = self.project_config_dao.unserve(config_uuid)
        if rows_updated == 0:
            raise ProjectInternalError(f'Failed to unserve config {config_uuid}')
        return self._build_out_or_raise(project_uuid)

    def delete_project(self, project_uuid: UUID) -> ProjectOut:
        project = self._get_project_or_raise(project_uuid)

        # Build the response before deletion so the caller can still see the
        # served config (e.g. to deregister its routes).
        out = self._build_out(project)

        served = self.project_config_dao.get_served_by_project(project_uuid)
        if served is not None:
            self.project_config_dao.unserve(served.uuid)

        self.project_config_dao.soft_delete_by_project(project_uuid)
        self.project_dao.soft_delete(project_uuid)
        return out

    def get_by_uuid(
        self, project_uuid: UUID, include_limits: bool = False
    ) -> ProjectOut:
        return self._build_out(self._get_project_or_raise(project_uuid), include_limits)

    def get_config(self, project_uuid: UUID, config_uuid: UUID) -> ConfigSlotOut:
        return ConfigSlotOut.from_config(
            self._get_config_or_raise(project_uuid, config_uuid)
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

    def export_config(self, project_uuid: UUID, config_uuid: UUID) -> tuple[bytes, str]:
        project = self._get_project_or_raise(project_uuid)
        config = self._get_config_or_raise(project_uuid, config_uuid)
        if not config.config_file:
            raise ProjectConfigValidationError(
                f'Config {config_uuid} has no configuration to export'
            )
        return self._build_configs_zip(project.name, [config])

    def export_all_configs(self, project_uuid: UUID) -> tuple[bytes, str]:
        project = self._get_project_or_raise(project_uuid)
        configs = [
            config
            for config in self.project_config_dao.list_by_project(project_uuid)
            if config.config_file
        ]
        if not configs:
            raise ProjectConfigValidationError(
                f'Project {project_uuid} has no configuration to export'
            )
        return self._build_configs_zip(project.name, configs)

    def import_config(
        self, project_uuid: UUID, config_uuid: UUID, content: bytes
    ) -> ProjectOut:
        self._get_project_or_raise(project_uuid)
        config = self._get_config_or_raise(project_uuid, config_uuid)
        if config.config_status == ConfigStatus.SERVED.value:
            raise ProjectConfigValidationError(
                f'Config {config_uuid} is served and cannot be overwritten by import'
            )
        try:
            config_file = content.decode('utf-8')
        except UnicodeDecodeError as e:
            raise ProjectConfigValidationError(
                'Uploaded file is not valid UTF-8 text'
            ) from e

        validate_gateway_config(config_file, check_secrets=True)
        self._reject_route_budget_limiting_conflict(project_uuid, config_file)

        rows_updated = self.project_config_dao.update_config_file(
            config_uuid, config_file
        )
        if rows_updated == 0:
            raise ProjectNotFoundError(f'Config {config_uuid} not found')
        return self._build_out_or_raise(project_uuid)

    def add_budget_limits_to_project(
        self, project_uuid: UUID, limits_in: ProjectBudgetLimitsIn
    ) -> list[ProjectBudgetLimitOut]:
        project = self._get_project_or_raise(project_uuid)

        served = self.project_config_dao.get_served_by_project(project_uuid)
        if (
            served
            and served.config_file
            and config_has_route_budget_limiting(served.config_file)
        ):
            raise ProjectBudgetLimitConflictError(
                f'Project "{project.name}" has a published route with '
                'budget_limiting configured; remove it before assigning a '
                'project-level budget limit'
            )

        try:
            inserted = self.project_budget_limit_dao.insert_many(
                limits_in.to_project_budget_limits(project_uuid)
            )
        except IntegrityError as e:
            if 'uq_project_budget_limit_PROJECT_UUID_WINDOW_SIZE' in str(e.orig):
                raise ProjectBudgetLimitAlreadyExistsError(
                    f'Project "{project.name}" already has a budget limit for '
                    'one of the requested time windows'
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

    def get_budget_limits_for_project(
        self, project_uuid: UUID
    ) -> list[ProjectBudgetLimitOut]:
        self._get_project_or_raise(project_uuid)
        return [
            ProjectBudgetLimitOut.from_project_budget_limit(limit)
            for limit in self.project_budget_limit_dao.get_by_project_uuid(project_uuid)
        ]

    def validate_exists(self, project_uuid: UUID) -> None:
        if not self.project_dao.get_by_uuid(project_uuid):
            raise ProjectNotFoundError(f'Project with UUID {project_uuid} not found')

    def get_all(self) -> list[ProjectOut]:
        return [self._build_out(project) for project in self.project_dao.get_all()]

    def get_all_filtered(
        self,
        project_filter: ProjectFilter | None = None,
        include_limits: bool = False,
    ) -> list[ProjectOut]:
        projects = self.project_dao.get_all_filtered(project_filter)
        return [self._build_out(project, include_limits) for project in projects]

    def get_configs(
        self, config_filter: ConfigListFilter | None = None
    ) -> list[ProjectOut]:
        status = config_filter.to_config_status() if config_filter else None
        # "Draft" must exclude EMPTY slots (freshly seeded template with a NULL
        # updated_at), otherwise it would match every project since a DRAFT slot
        # always exists.
        exclude_empty = config_filter == ConfigListFilter.DRAFT
        projects = self.project_dao.get_all_by_config_status(
            status, exclude_empty=exclude_empty
        )
        return [self._build_out(project) for project in projects]

    def get_all_active(self) -> list[ProjectOut]:
        projects = self.project_dao.get_all_with_config()
        return [self._build_out(project) for project in projects]
