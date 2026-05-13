from uuid import UUID

from sqlalchemy.exc import IntegrityError

from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO
from radicalbit_ai_gateway.db.tables.project_table import Project
from radicalbit_ai_gateway.models.config_status import ConfigStatus
from radicalbit_ai_gateway.models.project_dto import (
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
from radicalbit_ai_gateway.utils.yaml_utils import validate_gateway_config


class ProjectService:
    def __init__(self, project_dao: ProjectDAO):
        self.project_dao = project_dao

    def _get_project_or_raise(self, project_uuid: UUID) -> Project:
        project = self.project_dao.get_by_uuid(project_uuid)
        if not project:
            raise ProjectNotFoundError(f'Project with UUID {project_uuid} not found')
        return project

    def _get_updated_or_raise(self, project_uuid: UUID) -> ProjectOut:
        updated_project = self.project_dao.get_by_uuid(project_uuid)
        if not updated_project:
            raise ProjectInternalError(
                f'Failed to fetch updated project {project_uuid}'
            )
        return ProjectOut.from_project(updated_project)

    def create_project(self, project_in: ProjectIn) -> ProjectOut:
        try:
            project = project_in.to_project()
            inserted = self.project_dao.insert(project)
            return ProjectOut.from_project(inserted)
        except IntegrityError as e:
            if 'uq_project_NAME' in str(e.orig) or 'NAME' in str(e.orig):
                raise ProjectAlreadyExistsError(
                    f'Project with name "{project_in.name}" already exists'
                ) from e
            raise ProjectInternalError(
                f'An error occurred while creating the project: {e}'
            ) from e

    def load_config(
        self, project_uuid: UUID, config_in: ProjectConfigFileIn
    ) -> ProjectOut:
        validate_gateway_config(config_in.config_file, check_secrets=True)

        _ = self._get_project_or_raise(project_uuid)

        rows_updated = self.project_dao.update_draft_config_file(
            project_uuid, config_in.config_file
        )
        if rows_updated == 0:
            raise ProjectNotFoundError(f'Project with UUID {project_uuid} not found')

        updated_project = self.project_dao.get_by_uuid(project_uuid)
        if not updated_project:
            raise ProjectNotFoundError(f'Project with UUID {project_uuid} not found')
        return ProjectOut.from_project(updated_project)

    def approve_config(self, project_uuid: UUID) -> ProjectOut:
        project = self._get_project_or_raise(project_uuid)

        if (
            project.config_status != ConfigStatus.DRAFT.value
            or not project.draft_config_file
        ):
            raise ProjectConfigValidationError(
                f'Project {project_uuid} has no draft configuration to approve'
            )

        validate_gateway_config(project.draft_config_file, check_secrets=True)

        self.project_dao.set_config_status(project_uuid, ConfigStatus.READY_TO_SERVE)

        return self._get_updated_or_raise(project_uuid)

    def serve_config(self, project_uuid: UUID) -> ProjectOut:
        project = self._get_project_or_raise(project_uuid)

        if not project.draft_config_file:
            raise ProjectConfigValidationError(
                f'Project {project_uuid} has no configuration to serve'
            )

        if project.config_status != ConfigStatus.READY_TO_SERVE.value:
            raise ProjectConfigValidationError(
                f'Project {project_uuid} config must be approved before serving'
            )

        rows_updated = self.project_dao.promote_draft_to_config(
            project_uuid, project.draft_config_file
        )
        if rows_updated == 0:
            raise ProjectInternalError(
                f'Failed to promote draft config for project {project_uuid}'
            )

        return self._get_updated_or_raise(project_uuid)

    def unserve_config(self, project_uuid: UUID) -> ProjectOut:
        project = self._get_project_or_raise(project_uuid)

        if not project.config_file:
            raise ProjectConfigValidationError(
                f'Project {project_uuid} has no served configuration to unserve'
            )

        restore_draft = project.draft_config_file is None
        rows_updated = self.project_dao.unserve_config(project_uuid, restore_draft)
        if rows_updated == 0:
            raise ProjectInternalError(
                f'Failed to unserve config for project {project_uuid}'
            )

        return self._get_updated_or_raise(project_uuid)

    def get_by_uuid(self, project_uuid: UUID) -> ProjectOut:
        return ProjectOut.from_project(self._get_project_or_raise(project_uuid))

    def validate_exists(self, project_uuid: UUID) -> None:
        if not self.project_dao.get_by_uuid(project_uuid):
            raise ProjectNotFoundError(f'Project with UUID {project_uuid} not found')

    def get_all(self) -> list[ProjectOut]:
        projects = self.project_dao.get_all()
        return [ProjectOut.from_project(project) for project in projects]

    def get_all_filtered(
        self, project_filter: ProjectFilter | None = None
    ) -> list[ProjectOut]:
        projects = self.project_dao.get_all_filtered(project_filter)
        return [ProjectOut.from_project(project) for project in projects]

    def get_all_active(self) -> list[ProjectOut]:
        projects = self.project_dao.get_all_with_config()
        return [ProjectOut.from_project(project) for project in projects]
