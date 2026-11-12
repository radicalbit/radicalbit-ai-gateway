from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi_pagination import Page, Params

from radicalbit_ai_gateway.models.request_dto import RequestDetailDTO, RequestDTO
from radicalbit_ai_gateway.models.request_event_type import RequestType
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.services.requests_service import RequestsService
from radicalbit_ai_gateway.utils.request_tags import parse_tags_query


class RequestsRoute:
    @staticmethod
    def get_requests_router(
        requests_service: RequestsService,
        project_service: ProjectService,
    ) -> APIRouter:
        router = APIRouter(tags=['requests_api'])

        @router.get(
            '/projects/{project_uuid}/requests',
            status_code=200,
            response_model=Page[RequestDTO],
        )
        def get_requests(
            project_uuid: UUID,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            routes: Annotated[list[str] | None, Query()] = None,
            groups: Annotated[list[UUID] | None, Query()] = None,
            keys: Annotated[list[UUID] | None, Query()] = None,
            request_types: Annotated[
                list[RequestType] | None, Query(alias='requestType')
            ] = None,
            _page: Annotated[int, Query(ge=1)] = 1,
            _limit: Annotated[int, Query(ge=1, le=100)] = 50,
            tags: Annotated[list[str] | None, Depends(parse_tags_query)] = None,
        ):
            project_service.validate_exists(project_uuid)
            from_dt = datetime.fromtimestamp(_from, timezone.utc) if _from else None
            to_dt = datetime.fromtimestamp(_to, timezone.utc) if _to else None
            return requests_service.get_requests(
                project_uuid=project_uuid,
                route_names=routes,
                group_uuids=groups,
                key_uuids=keys,
                _from=from_dt,
                _to=to_dt,
                params=Params(page=_page, size=_limit),
                tags=tags,
                request_types=request_types,
            )

        # Same rule: a request with no trace answers `traceId: null`.
        @router.get(
            '/projects/{project_uuid}/requests/{request_uuid}',
            status_code=200,
            response_model=RequestDetailDTO,
        )
        def get_request(project_uuid: UUID, request_uuid: UUID):
            project_service.validate_exists(project_uuid)
            return requests_service.get_request(
                project_uuid=project_uuid, request_uuid=request_uuid
            )

        return router
