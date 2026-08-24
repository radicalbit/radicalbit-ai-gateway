from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class TagKeysDTO(BaseModel):
    tag_keys: list[str] = Field(description='Distinct tag keys used in the project')

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )
