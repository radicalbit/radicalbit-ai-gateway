from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class SecretOut(BaseModel):
    """A secret key held by the secrets backend. Never carries a value."""

    key: str = Field(description='The secret key as the secrets backend spells it')

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )
