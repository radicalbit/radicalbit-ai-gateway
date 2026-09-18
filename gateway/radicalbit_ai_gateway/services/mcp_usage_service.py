from datetime import datetime
from uuid import UUID

from fastapi_pagination import Page, Params

from radicalbit_ai_gateway.db.dao.event_dao import EventDAO
from radicalbit_ai_gateway.models.mcp_usage_dto import McpKeyUsageDTO


class McpUsageService:
    """MCP usage views on the Usage page, read from MCP invocation events."""

    def __init__(self, event_dao: EventDAO):
        self.event_dao = event_dao

    def get_mcp_key_usage(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        params: Params,
        tags: list[str] | None = None,
    ) -> Page[McpKeyUsageDTO]:
        page = self.event_dao.get_mcp_key_usage_paginated(
            project_uuid=project_uuid,
            route_names=route_names,
            _from=_from,
            _to=_to,
            params=params,
            tags=tags,
        )
        items = [
            McpKeyUsageDTO(
                key_name=row.key_name,
                key_uuid=row.key_uuid,
                group_name=row.group_name,
                group_uuid=row.group_uuid,
                counter=row.counter,
                last_call=int(row.last_call.timestamp()),
            )
            for row in page.items
        ]
        return Page.create(items, params, total=page.total)
