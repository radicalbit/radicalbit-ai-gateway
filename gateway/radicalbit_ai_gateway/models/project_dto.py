import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from radicalbit_ai_gateway.db.tables.project_table import Project
from radicalbit_ai_gateway.models.config_status import ConfigStatus
from radicalbit_ai_gateway.models.project_status import ProjectStatus
from radicalbit_ai_gateway.utils.yaml_utils import get_default_config_template


class ProjectFilter(str, Enum):
    ACTIVE = 'active'
    WITH_USAGE = 'with_usage'
    DEV = 'dev'
    PROD = 'prod'

    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            for member in cls:
                if member.value == value.lower():
                    return member
        return None


class ProjectIn(BaseModel, validate_assignment=True):
    name: str
    description: str | None = None

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    def to_project(self) -> Project:
        UTC = getattr(datetime, 'UTC', datetime.timezone.utc)
        now = datetime.datetime.now(tz=UTC)

        return Project(
            name=self.name,
            description=self.description,
            config_status=ConfigStatus.DRAFT.value,
            draft_config_file=get_default_config_template(),
            created_at=now,
            updated_at=now,
        )


class ProjectConfigFileIn(BaseModel):
    config_file: str

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class GenerateConfigIn(BaseModel):
    description: str

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class GenerateConfigOut(BaseModel):
    config_file: str

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class ProjectOut(BaseModel):
    uuid: UUID
    name: str
    description: str | None
    config_file: str | None
    draft_config_file: str | None
    config_status: ConfigStatus
    project_status: ProjectStatus
    created_at: str
    updated_at: str

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    @staticmethod
    def from_project(project: Project) -> 'ProjectOut':
        return ProjectOut(
            uuid=project.uuid,
            name=project.name,
            description=project.description,
            config_file=project.config_file,
            draft_config_file=project.draft_config_file,
            config_status=ConfigStatus(project.config_status),
            project_status=ProjectStatus.PROD
            if project.config_file is not None
            else ProjectStatus.DEV,
            created_at=str(project.created_at),
            updated_at=str(project.updated_at),
        )
