import io
import re
from uuid import UUID
import zipfile

from sqlalchemy.exc import IntegrityError

from radicalbit_ai_gateway.db.dao.project_config_dao import ProjectConfigDAO
from radicalbit_ai_gateway.db.dao.project_dao import ProjectDAO
from radicalbit_ai_gateway.db.tables.project_config_table import ProjectConfig
from radicalbit_ai_gateway.db.tables.project_table import Project
from radicalbit_ai_gateway.models.config_slot import Slot
from radicalbit_ai_gateway.models.config_status import ConfigStatus
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
    ProjectConfigValidationError,
    ProjectInternalError,
    ProjectNotFoundError,
)
from radicalbit_ai_gateway.utils.yaml_utils import (
    get_default_config_template,
    validate_gateway_config,
)


def _sanitize_filename(name: str) -> str:
    sanitized = re.sub(r'[^A-Za-z0-9_-]+', '_', name).strip('_')
    return sanitized or 'config'


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

        validate_gateway_config(config.config_file, check_secrets=True)

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

        rows_updated = self.project_config_dao.update_config_file(
            config_uuid, config_file
        )
        if rows_updated == 0:
            raise ProjectNotFoundError(f'Config {config_uuid} not found')
        return self._build_out_or_raise(project_uuid)

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
