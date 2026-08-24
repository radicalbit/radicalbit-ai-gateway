from uuid import UUID

from fastapi import APIRouter

from radicalbit_ai_gateway.models.tag_dto import TagKeysDTO
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.services.request_event_service import RequestEventService


class TagRoute:
    @staticmethod
    def get_tag_router(
        request_event_service: RequestEventService,
        project_service: ProjectService,
    ) -> APIRouter:
        router = APIRouter(tags=['tags_api'])

        @router.get(
            '/projects/{project_uuid}/tags/keys',
            status_code=200,
            response_model=TagKeysDTO,
        )
        def get_tag_keys(project_uuid: UUID):
            project_service.get_by_uuid(project_uuid)
            return request_event_service.get_tag_keys(project_uuid)

        return router
