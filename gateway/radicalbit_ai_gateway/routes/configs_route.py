from collections.abc import Callable
from dataclasses import dataclass, field
import logging
from typing import Any

from fastapi import APIRouter, Query, Request

from radicalbit_ai_gateway.models.error_dto import error_responses
from radicalbit_ai_gateway.models.project_dto import (
    ConfigListFilter,
    ConfigValidationOut,
    ProjectConfigFileIn,
    ProjectOut,
)
from radicalbit_ai_gateway.models.runtime_config_out import RuntimeConfigOut
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.yaml_utils import validate_gateway_config

app_config = get_app_config()

logger = logging.getLogger(app_config.log_config.logger_name)


@dataclass
class ConfigsRouteConfig:
    get_configs_fn: Callable[[Request, ConfigListFilter | None], Any] | None = None
    list_response_model: type = field(default_factory=lambda: list[ProjectOut])


class ConfigsRoute:
    @staticmethod
    def get_configs_router(
        project_service: ProjectService,
        config: ConfigsRouteConfig | None = None,
    ) -> APIRouter:
        config = config or ConfigsRouteConfig()
        get_configs_fn = config.get_configs_fn or (
            lambda _, f: project_service.get_configs(f)
        )
        router = APIRouter()
        runtime_configs = ['runtime_configs_api']

        @router.get(
            '/configs/runtime',
            status_code=200,
            response_model=RuntimeConfigOut,
            tags=runtime_configs,
        )
        def get_runtime_configs():
            api_key = app_config.config_generator_config.config_generator_openai_api_key
            return RuntimeConfigOut(
                enabled_plugins_list=app_config.runtime_config.plugins(),
                config_generator_enabled=api_key is not None,
            )

        @router.get(
            '/configs/projects',
            status_code=200,
            response_model=config.list_response_model,
            tags=runtime_configs,
        )
        def get_configs(
            request: Request, status: ConfigListFilter | None = Query(None)
        ):
            return get_configs_fn(request, status)

        @router.post(
            '/configs/validate',
            status_code=200,
            response_model=ConfigValidationOut,
            tags=['configs'],
            operation_id='configs_validate',
            responses=error_responses(400),
        )
        def validate_config(config_in: ProjectConfigFileIn):
            """Validate a YAML configuration against the config schema, saving nothing.

            Secrets are not checked: saving a valid config can still fail on them.
            """
            validate_gateway_config(config_in.config_file, check_secrets=False)
            return ConfigValidationOut(valid=True)

        return router
