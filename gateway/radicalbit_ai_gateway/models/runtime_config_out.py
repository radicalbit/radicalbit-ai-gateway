from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class RuntimeConfigOut(BaseModel):
    enabled_plugins_list: list[str]
    config_generator_enabled: bool

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )
