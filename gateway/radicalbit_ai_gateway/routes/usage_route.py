from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi_pagination import Page, Params

from radicalbit_ai_gateway.models.event_dto import UsageCostsDTO
from radicalbit_ai_gateway.models.mcp_usage_dto import McpKeyUsageDTO
from radicalbit_ai_gateway.services.event_service import EventService
from radicalbit_ai_gateway.services.mcp_usage_service import McpUsageService
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.utils.request_tags import parse_tags_query


class UsageRoute:
    @staticmethod
    def get_usage_router(
        event_service: EventService,
        project_service: ProjectService,
        mcp_usage_service: McpUsageService,
    ) -> APIRouter:
        router = APIRouter(tags=['usage_api'])

        @router.get(
            '/projects/{project_uuid}/usage/costs',
            status_code=200,
            response_model=UsageCostsDTO,
            response_model_exclude_none=True,
        )
        def get_usage_costs(
            project_uuid: UUID,
            request: Request,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            _with_saved_tokens: bool = Query(False),
            tags: Annotated[list[str] | None, Depends(parse_tags_query)] = None,
        ):
            project = project_service.get_by_uuid(project_uuid)
            project_entry = request.app.state.project_configs.get(project.name)
            if not project_entry:
                return UsageCostsDTO(total=0.0, routes=[])
            return event_service.get_all_routes_costs(
                project_uuid=project_uuid,
                config=project_entry.config,
                _from=datetime.fromtimestamp(_from, timezone.utc) if _from else None,
                _to=datetime.fromtimestamp(_to, timezone.utc) if _to else None,
                _with_saved_tokens=_with_saved_tokens,
                tags=tags,
            )

        @router.get(
            '/projects/{project_uuid}/usage/mcp/keys',
            status_code=200,
            response_model=Page[McpKeyUsageDTO],
            response_model_exclude_none=True,
        )
        def get_mcp_key_usage(
            project_uuid: UUID,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            routes: Annotated[list[str] | None, Query()] = None,
            _page: Annotated[int, Query(ge=1)] = 1,
            _limit: Annotated[int, Query(ge=1, le=100)] = 50,
            tags: Annotated[list[str] | None, Depends(parse_tags_query)] = None,
        ):
            project_service.validate_exists(project_uuid)
            return mcp_usage_service.get_mcp_key_usage(
                project_uuid=project_uuid,
                route_names=routes,
                _from=datetime.fromtimestamp(_from, timezone.utc) if _from else None,
                _to=datetime.fromtimestamp(_to, timezone.utc) if _to else None,
                params=Params(page=_page, size=_limit),
                tags=tags,
            )

        return router
