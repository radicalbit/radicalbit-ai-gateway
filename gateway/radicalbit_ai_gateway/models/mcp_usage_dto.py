from typing import Literal
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


class McpServerChartDataSeriesDTO(BaseModel):
    """One line on the MCP invocations chart.

    ``uuid`` is what a caller navigates by when drilling into the series. It
    is null when the grouping is ``services``, where the alias in ``name`` is
    the identifier. Counts are integers, not the floats the cost chart uses.
    """

    name: str
    uuid: UUID | None = None
    data: list[int]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class McpServerChartDataDTO(BaseModel):
    """MCP invocations over time, one series per entity in the grouping.

    Every series is zero-filled across ``timestamp``, so a gap reads as a gap.
    Not named after the cost chart's model: ``CostChartDataDTO`` is taken.
    """

    granularity: Literal['hours', 'days', 'weeks', 'months']
    timestamp: list[int]
    data: list[McpServerChartDataSeriesDTO]
    total: int

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )
