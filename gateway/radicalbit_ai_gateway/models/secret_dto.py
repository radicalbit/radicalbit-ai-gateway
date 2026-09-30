from enum import Enum
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


class SecretStatus(str, Enum):
    UNAVAILABLE = 'unavailable'


class SecretOut(BaseModel):
    """A secret key the Secrets page lists. Never carries a value.

    The key either comes from the secrets backend or only from a published
    configuration that references it, in which case it is unavailable.
    """

    key: str = Field(description='The secret key as the secrets backend spells it')
    used_in: list[ProjectRef] = Field(
        default_factory=list,
        description='Projects referencing this key in their published configuration',
    )
    status: SecretStatus | None = Field(
        default=None,
        description='Unavailable when a published configuration references the '
        'key but the secrets backend no longer holds it, otherwise null',
    )

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )
