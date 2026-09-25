from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ProjectRef(BaseModel):
    """A project identified by uuid and name, for display only."""

    uuid: UUID
    name: str

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class SecretOut(BaseModel):
    """A secret key held by the secrets backend. Never carries a value."""

    key: str = Field(description='The secret key as the secrets backend spells it')
    used_in: list[ProjectRef] = Field(
        default_factory=list,
        description='Projects referencing this key in their published configuration',
    )

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )
