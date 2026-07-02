import logging

from fastapi import APIRouter, Query

from radicalbit_ai_gateway.models.project_dto import ConfigListFilter, ProjectOut
from radicalbit_ai_gateway.models.runtime_config_out import RuntimeConfigOut
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()

logger = logging.getLogger(app_config.log_config.logger_name)


class ConfigsRoute:
    @staticmethod
    def get_configs_router(project_service: ProjectService) -> APIRouter:
        router = APIRouter(tags=['runtime_configs_api'])

        @router.get(
            '/configs/runtime', status_code=200, response_model=RuntimeConfigOut
        )
        def get_runtime_configs():
            api_key = app_config.config_generator_config.config_generator_openai_api_key
            return RuntimeConfigOut(
                enabled_plugins_list=app_config.runtime_config.plugins(),
                config_generator_enabled=api_key is not None,
            )

        @router.get(
            '/configs/projects', status_code=200, response_model=list[ProjectOut]
        )
        def get_configs(status: ConfigListFilter | None = Query(None)):
            return project_service.get_configs(status)

        return router
