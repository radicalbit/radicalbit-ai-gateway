from uuid import UUID

from sqlalchemy.exc import IntegrityError

from radicalbit_ai_gateway.db.dao.project_config_dao import ProjectConfigDAO
from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO
from radicalbit_ai_gateway.db.tables.project_config_table import ProjectConfig
from radicalbit_ai_gateway.db.tables.project_table import Project
from radicalbit_ai_gateway.models.config_slot import Slot
from radicalbit_ai_gateway.models.config_status import ConfigStatus
from radicalbit_ai_gateway.models.project_dto import (
    ConfigSlotOut,
    ProjectConfigFileIn,
    ProjectFilter,
    ProjectIn,
    ProjectOut,
)
from radicalbit_ai_gateway.utils.exceptions import (
    ProjectAlreadyExistsError,
    ProjectConfigValidationError,
    ProjectInternalError,
    ProjectNotFoundError,
)
from radicalbit_ai_gateway.utils.yaml_utils import (
    get_default_config_template,
    validate_gateway_config,
)


class ProjectService:
    def __init__(self, project_dao: ProjectDAO, project_config_dao: ProjectConfigDAO):
        self.project_dao = project_dao
        self.project_config_dao = project_config_dao

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

    def _build_out(self, project: Project) -> ProjectOut:
        configs = list(self.project_config_dao.list_by_project(project.uuid))
        return ProjectOut.from_project(project, configs)

    def _build_out_or_raise(self, project_uuid: UUID) -> ProjectOut:
        project = self.project_dao.get_by_uuid(project_uuid)
        if not project:
            raise ProjectInternalError(
                f'Failed to fetch updated project {project_uuid}'
            )
        return self._build_out(project)

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

    def update_config(
        self, project_uuid: UUID, config_uuid: UUID, config_in: ProjectConfigFileIn
    ) -> ProjectOut:
        validate_gateway_config(config_in.config_file, check_secrets=True)

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

    def get_by_uuid(self, project_uuid: UUID) -> ProjectOut:
        return self._build_out(self._get_project_or_raise(project_uuid))

    def get_config(self, project_uuid: UUID, config_uuid: UUID) -> ConfigSlotOut:
        return ConfigSlotOut.from_config(
            self._get_config_or_raise(project_uuid, config_uuid)
        )

    def validate_exists(self, project_uuid: UUID) -> None:
        if not self.project_dao.get_by_uuid(project_uuid):
            raise ProjectNotFoundError(f'Project with UUID {project_uuid} not found')

    def get_all(self) -> list[ProjectOut]:
        return [self._build_out(project) for project in self.project_dao.get_all()]

    def get_all_filtered(
        self, project_filter: ProjectFilter | None = None
    ) -> list[ProjectOut]:
        projects = self.project_dao.get_all_filtered(project_filter)
        return [self._build_out(project) for project in projects]

    def get_all_active(self) -> list[ProjectOut]:
        projects = self.project_dao.get_all_with_config()
        return [self._build_out(project) for project in projects]
