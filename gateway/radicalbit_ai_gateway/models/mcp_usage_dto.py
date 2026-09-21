from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class McpKeyUsageDTO(BaseModel):
    """One API key that made MCP invocations, as the event recorded it.

    Names and identifiers are read back from the event, not resolved from
    Postgres, so a renamed key reads under its old name and a deleted key
    still shows up. ``last_call`` is epoch seconds, the convention the trace
    payloads use.
    """

    key_name: str
    key_uuid: UUID
    group_name: str
    group_uuid: UUID
    counter: int
    last_call: int

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )
