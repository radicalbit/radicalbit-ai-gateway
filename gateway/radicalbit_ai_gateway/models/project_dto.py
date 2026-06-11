import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from radicalbit_ai_gateway.db.tables.project_config_table import ProjectConfig
from radicalbit_ai_gateway.db.tables.project_table import Project
from radicalbit_ai_gateway.models.config_status import ConfigStatus
from radicalbit_ai_gateway.models.project_status import ProjectStatus


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


class ConfigSlotOut(BaseModel):
    uuid: UUID
    slot: str
    config_file: str | None
    config_status: ConfigStatus
    updated_at: str

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    @staticmethod
    def from_config(config: ProjectConfig) -> 'ConfigSlotOut':
        return ConfigSlotOut(
            uuid=config.uuid,
            slot=config.slot,
            config_file=config.config_file,
            config_status=ConfigStatus(config.config_status),
            updated_at=str(config.updated_at),
        )


class ProjectOut(BaseModel):
    uuid: UUID
    name: str
    description: str | None
    project_status: ProjectStatus
    served_config_uuid: UUID | None
    configs: list[ConfigSlotOut]
    created_at: str
    updated_at: str

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )

    @staticmethod
    def from_project(project: Project, configs: list[ProjectConfig]) -> 'ProjectOut':
        ordered = sorted(configs, key=lambda c: c.slot)
        served = next(
            (c for c in ordered if c.config_status == ConfigStatus.SERVED.value),
            None,
        )
        return ProjectOut(
            uuid=project.uuid,
            name=project.name,
            description=project.description,
            project_status=ProjectStatus.PROD if served else ProjectStatus.DEV,
            served_config_uuid=served.uuid if served else None,
            configs=[ConfigSlotOut.from_config(c) for c in ordered],
            created_at=str(project.created_at),
            updated_at=str(project.updated_at),
        )
