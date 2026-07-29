import asyncio
from datetime import datetime, timezone
import logging
from time import sleep
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.sse import EventSourceResponse
from starlette.responses import StreamingResponse

from radicalbit_ai_gateway.models.event_dto import (
    CostChartDataDTO,
    CostDataDTO,
    EventsDTO,
    InvocationChartDataDTO,
    LastNEvents,
    ModelCostDTO,
    RequestChartDataDTO,
    RequestGroupedChartDataDTO,
    TokenChartDataDTO,
    WindowStatus,
)
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_route_out import GatewayRouteOut
from radicalbit_ai_gateway.models.guardrails import Guardrail, GuardrailType
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.models.project_entry import ProjectEntry
from radicalbit_ai_gateway.models.prompt_dto import (
    PromptCategory,
    PromptItemOut,
    RoutePromptsOut,
)
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.services.event_service import EventService
from radicalbit_ai_gateway.services.project_service import ProjectService
from radicalbit_ai_gateway.services.request_event_service import RequestEventService
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.chart_utils import determine_granularity
from radicalbit_ai_gateway.utils.exceptions import GatewayNotFoundError
from radicalbit_ai_gateway.utils.sse_params import (
    compute_sse_time_range,
    validate_sse_params,
)
from radicalbit_ai_gateway.utils.token_encoding import count_tokens

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


def _build_chat_prompt_item(model_obj: Model) -> PromptItemOut:
    prompt_text = model_obj.effective_prompt
    tokens = count_tokens(prompt_text or '', model_obj.model)
    return PromptItemOut(
        category=PromptCategory.CHAT_MODEL,
        model_id=model_obj.model_id,
        model_name=model_obj.model,
        prompt=prompt_text,
        tokens=tokens,
    )


def _build_judge_prompt_item(
    gname: str, guardrail: Guardrail, config: GatewayConfig
) -> PromptItemOut:
    judge_params = guardrail.parameters
    judge_model = config.chat_models_by_id.get(judge_params.model_id)
    model_name = judge_model.model if judge_model else judge_params.model_id
    prompt_text = None
    prompt_manager = PromptManager.get_global()
    if prompt_manager:
        try:
            prompt_text = prompt_manager.get_judge_prompt(judge_params.prompt_ref)
        except FileNotFoundError:
            logger.warning('Judge prompt not found: %s', judge_params.prompt_ref)
    tokens = count_tokens(prompt_text or '', model_name)
    return PromptItemOut(
        category=PromptCategory.GUARDRAIL_JUDGE,
        model_id=judge_params.model_id,
        model_name=model_name,
        guardrail_name=gname,
        prompt=prompt_text,
        tokens=tokens,
    )


def _get_route_prompts(route_name: str, config: GatewayConfig) -> RoutePromptsOut:
    route_config = config.routes[route_name]
    chat_items = [
        _build_chat_prompt_item(model)
        for model_id in (route_config.chat_models or [])
        if (model := config.chat_models_by_id.get(model_id)) is not None
    ]
    global_guardrails = {g.name: g for g in (config.guardrails or [])}
    judge_items = [
        _build_judge_prompt_item(gname, global_guardrails[gname], config)
        for gname in (route_config.guardrails or [])
        if gname in global_guardrails
        and global_guardrails[gname].type == GuardrailType.JUDGE
    ]
    return RoutePromptsOut(route_name=route_name, prompts=chat_items + judge_items)


class DashboardRoute:
    @staticmethod
    def get_dashboard_router(  # noqa: C901
        event_service: EventService,
        request_event_service: RequestEventService,
        project_service: ProjectService,
    ) -> APIRouter:
        router = APIRouter(tags=['dashboard_api'])

        @router.get(
            '/projects/{project_uuid}/metrics',
            status_code=200,
            response_model=EventsDTO,
            response_model_exclude_none=True,
        )
        def get_route_total_metrics(
            project_uuid: UUID,
            request: Request,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
        ):
            project = project_service.get_by_uuid(project_uuid)
            project_entry = request.app.state.project_configs.get(project.name)
            if not project_entry:
                return EventsDTO(request_error_percentage=0.0)
            return event_service.get_total_counter(
                project_uuid=project_uuid,
                config=project_entry.config,
                _from=datetime.fromtimestamp(_from) if _from else None,
                _to=datetime.fromtimestamp(_to) if _to else None,
            )

        @router.get(
            '/projects/{project_uuid}/routes',
            status_code=200,
            response_model=list[GatewayRouteOut],
            response_model_exclude_none=True,
        )
        def get_all_routes_config_with_metrics(
            project_uuid: UUID,
            request: Request,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            include_groups: bool = False,
        ):
            project = project_service.get_by_uuid(project_uuid)
            project_entry = request.app.state.project_configs.get(project.name)
            if not project_entry:
                return []
            return event_service.get_total_counter_per_route(
                project_uuid=project_uuid,
                project_name=project.name,
                config=project_entry.config,
                include_groups=include_groups,
                _from=datetime.fromtimestamp(_from) if _from else None,
                _to=datetime.fromtimestamp(_to) if _to else None,
            )

        @router.get(
            '/projects/{project_uuid}/routes/{route_name}',
            status_code=200,
            response_model=GatewayRouteOut,
            response_model_exclude_none=True,
        )
        def get_route_config_with_metrics_by_name(
            project_uuid: UUID,
            route_name: str,
            request: Request,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            include_groups: bool = False,
        ):
            project = project_service.get_by_uuid(project_uuid)
            project_entry = request.app.state.project_configs.get(project.name)
            if not project_entry:
                raise GatewayNotFoundError(
                    f'No active configuration for project {project.name}'
                )
            if route_name not in project_entry.config.routes:
                raise GatewayNotFoundError(
                    f'Route {route_name} not found in project {project.name}'
                )
            return event_service.get_counter_per_route(
                project_uuid=project_uuid,
                project_name=project.name,
                config=project_entry.config,
                route_name=route_name,
                include_groups=include_groups,
                _from=datetime.fromtimestamp(_from) if _from else None,
                _to=datetime.fromtimestamp(_to) if _to else None,
            )

        @router.get(
            '/projects/{project_uuid}/routes/{route_name}/events',
            status_code=200,
            response_model=LastNEvents,
            response_model_exclude_none=True,
        )
        def get_n_last_events(
            project_uuid: UUID,
            route_name: str,
            request: Request,
            n: int = Query(10),
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
        ):
            project = project_service.get_by_uuid(project_uuid)
            project_entry = request.app.state.project_configs.get(project.name)
            if not project_entry:
                raise GatewayNotFoundError(
                    f'No active configuration for project {project.name}'
                )
            if route_name not in project_entry.config.routes:
                raise GatewayNotFoundError(
                    f'Route {route_name} not found in project {project.name}'
                )
            return event_service.get_latest_n_per_event_type(
                project_uuid=project_uuid,
                config=project_entry.config,
                route_name=route_name,
                n=n,
                _from=datetime.fromtimestamp(_from) if _from else None,
                _to=datetime.fromtimestamp(_to) if _to else None,
            )

        @router.get(
            '/projects/{project_uuid}/routes/{route_name}/costs/chart',
            status_code=200,
            response_model=CostChartDataDTO,
            response_model_exclude_none=True,
        )
        def get_costs_chart_data(
            project_uuid: UUID,
            route_name: str,
            request: Request,
            _from: Annotated[datetime | None, Query()] = None,
            _to: Annotated[datetime | None, Query()] = None,
            group_by: Literal['keys', 'groups', 'models'] = Query(),
        ):
            project = project_service.get_by_uuid(project_uuid)
            project_entry = request.app.state.project_configs.get(project.name)
            if not project_entry:
                raise GatewayNotFoundError(
                    f'No active configuration for project {project.name}'
                )
            if route_name not in project_entry.config.routes:
                raise GatewayNotFoundError(
                    f'Route {route_name} not found in project {project.name}'
                )
            return event_service.get_costs_chart_data(
                project_uuid=project_uuid,
                route_names=[route_name],
                _from=_from,
                _to=_to,
                group_by=group_by,
            )

        @router.get(
            '/projects/{project_uuid}/routes/{route_name}/costs/summary',
            status_code=200,
            response_model=CostDataDTO,
            response_model_exclude_none=True,
        )
        def get_chart_data_with_cache(
            project_uuid: UUID,
            route_name: str,
            request: Request,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            _with_saved_tokens: bool = Query(False),
        ):
            project = project_service.get_by_uuid(project_uuid)
            project_entry: ProjectEntry = request.app.state.project_configs.get(
                project.name
            )
            if not project_entry:
                raise GatewayNotFoundError(
                    f'No active configuration for project {project.name}'
                )
            if route_name not in project_entry.config.routes:
                raise GatewayNotFoundError(
                    f'Route {route_name} not found in project {project.name}'
                )
            return event_service.get_summary_costs(
                project_uuid=project_uuid,
                config=project_entry.config,
                route_names=[route_name],
                _from=datetime.fromtimestamp(_from, timezone.utc) if _from else None,
                _to=datetime.fromtimestamp(_to, timezone.utc) if _to else None,
                _with_saved_tokens=_with_saved_tokens,
            )

        @router.get(
            '/projects/{project_uuid}/routes/{route_name}/tokens/chart',
            status_code=200,
            response_model=TokenChartDataDTO,
            response_model_exclude_none=True,
        )
        def get_token_chart_data(
            project_uuid: UUID,
            route_name: str,
            request: Request,
            _from: Annotated[datetime | None, Query()] = None,
            _to: Annotated[datetime | None, Query()] = None,
        ):
            project = project_service.get_by_uuid(project_uuid)
            project_entry = request.app.state.project_configs.get(project.name)
            if not project_entry:
                raise GatewayNotFoundError(
                    f'No active configuration for project {project.name}'
                )
            if route_name not in project_entry.config.routes:
                raise GatewayNotFoundError(
                    f'Route {route_name} not found in project {project.name}'
                )
            granularity = determine_granularity(_from, _to)
            return event_service.get_token_chart_data(
                project_uuid=project_uuid,
                route_names=[route_name],
                _from=_from,
                _to=_to,
                granularity=granularity,
            )

        @router.get(
            '/projects/{project_uuid}/routes/tokens/stream',
            status_code=200,
            response_class=EventSourceResponse,
        )
        def stream_tokens(
            project_uuid: UUID,
            routes: Annotated[list[str] | None, Query()] = None,
            _gte: Annotated[
                int | None,
                Query(
                    description='Seconds to look back from now (mutually exclusive with _from/_to)'
                ),
            ] = None,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            _: None = Depends(validate_sse_params),
        ) -> StreamingResponse:
            project_service.validate_exists(project_uuid)
            while True:
                from_datetime, to_datetime = compute_sse_time_range(_gte, _from, _to)
                granularity = determine_granularity(from_datetime, to_datetime)
                result = event_service.get_token_chart_data(
                    project_uuid=project_uuid,
                    route_names=routes,
                    _from=from_datetime,
                    _to=to_datetime,
                    granularity=granularity,
                )
                yield result.model_dump(by_alias=True)
                sleep(10)

        @router.get(
            '/projects/{project_uuid}/routes/{route_name}/requests/chart',
            status_code=200,
            response_model=RequestChartDataDTO | RequestGroupedChartDataDTO,
            response_model_exclude_none=True,
        )
        def get_request_chart_data(
            project_uuid: UUID,
            route_name: str,
            request: Request,
            _from: Annotated[datetime | None, Query()] = None,
            _to: Annotated[datetime | None, Query()] = None,
            show_errors: Annotated[bool, Query()] = False,
        ):
            project = project_service.get_by_uuid(project_uuid)
            project_entry = request.app.state.project_configs.get(project.name)
            if not project_entry:
                raise GatewayNotFoundError(
                    f'No active configuration for project {project.name}'
                )
            if route_name not in project_entry.config.routes:
                raise GatewayNotFoundError(
                    f'Route {route_name} not found in project {project.name}'
                )
            granularity = determine_granularity(_from, _to)
            if show_errors:
                return request_event_service.get_request_grouped_chart_data(
                    project_uuid=project_uuid,
                    route_name=route_name,
                    _from=_from,
                    _to=_to,
                    granularity=granularity,
                )
            return request_event_service.get_request_chart_data(
                project_uuid=project_uuid,
                route_name=route_name,
                _from=_from,
                _to=_to,
                granularity=granularity,
            )

        @router.get(
            '/projects/{project_uuid}/routes/{route_name}/invocations/chart',
            status_code=200,
            response_model=InvocationChartDataDTO,
            response_model_exclude_none=True,
        )
        def get_invocation_chart_data(
            project_uuid: UUID,
            route_name: str,
            request: Request,
            _from: Annotated[datetime | None, Query()] = None,
            _to: Annotated[datetime | None, Query()] = None,
            include_models: Annotated[bool, Query()] = False,
        ):
            project = project_service.get_by_uuid(project_uuid)
            project_entry = request.app.state.project_configs.get(project.name)
            if not project_entry:
                raise GatewayNotFoundError(
                    f'No active configuration for project {project.name}'
                )
            if route_name not in project_entry.config.routes:
                raise GatewayNotFoundError(
                    f'Route {route_name} not found in project {project.name}'
                )
            granularity = determine_granularity(_from, _to)
            return event_service.get_invocation_chart_data(
                project_uuid=project_uuid,
                route_names=[route_name],
                _from=_from,
                _to=_to,
                granularity=granularity,
                include_models=include_models,
            )

        @router.get(
            '/projects/{project_uuid}/routes/{route_name}/prompts',
            status_code=200,
            response_model=RoutePromptsOut,
            response_model_exclude_none=True,
        )
        def get_route_prompts(
            project_uuid: UUID,
            route_name: str,
            request: Request,
        ):
            project = project_service.get_by_uuid(project_uuid)
            project_entry = request.app.state.project_configs.get(project.name)
            if not project_entry:
                raise GatewayNotFoundError(
                    f'No active configuration for project {project.name}'
                )
            if route_name not in project_entry.config.routes:
                raise GatewayNotFoundError(
                    f'Route {route_name} not found in project {project.name}'
                )
            return _get_route_prompts(route_name, project_entry.config)

        @router.get(
            '/projects/{project_uuid}/routes/limits/stream',
            status_code=200,
            response_class=EventSourceResponse,
        )
        async def stream_limits_progress(
            project_uuid: UUID,
            request: Request,
            routes: Annotated[list[str] | None, Query()] = None,
            window_statuses: Annotated[list[WindowStatus] | None, Query()] = None,
        ) -> StreamingResponse:
            project = project_service.get_by_uuid(project_uuid)
            project_gateway_routes = {
                k: v
                for k, v in request.app.state.routes.items()
                if k.startswith(f'{project.name}/')
            }
            while True:
                results = await event_service.get_route_limits_progress(
                    project_gateway_routes, project.name, routes, window_statuses
                )
                yield [r.model_dump(exclude_none=True, by_alias=True) for r in results]
                await asyncio.sleep(10)

        @router.get(
            '/projects/{project_uuid}/routes/invocations/stream',
            status_code=200,
            response_class=EventSourceResponse,
        )
        def stream_invocations(
            project_uuid: UUID,
            routes: Annotated[list[str] | None, Query()] = None,
            _gte: Annotated[
                int | None,
                Query(
                    description='Seconds to look back from now (mutually exclusive with _from/_to)'
                ),
            ] = None,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            include_models: Annotated[bool, Query()] = False,
            _: None = Depends(validate_sse_params),
        ) -> StreamingResponse:
            project_service.validate_exists(project_uuid)
            while True:
                from_datetime, to_datetime = compute_sse_time_range(_gte, _from, _to)
                granularity = determine_granularity(from_datetime, to_datetime)
                result = event_service.get_invocation_chart_data(
                    project_uuid=project_uuid,
                    route_names=routes,
                    _from=from_datetime,
                    _to=to_datetime,
                    granularity=granularity,
                    include_models=include_models,
                )
                yield result.model_dump(by_alias=True)
                sleep(10)

        @router.get(
            '/projects/{project_uuid}/routes/most-requested/stream',
            status_code=200,
            response_class=EventSourceResponse,
        )
        def stream_most_requested_route(
            project_uuid: UUID,
            request: Request,
            _gte: Annotated[
                int | None,
                Query(
                    description='Seconds to look back from now (mutually exclusive with _from/_to)'
                ),
            ] = None,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            _: None = Depends(validate_sse_params),
        ) -> StreamingResponse:
            project = project_service.get_by_uuid(project_uuid)
            project_entry = request.app.state.project_configs.get(project.name)
            if not project_entry:
                raise GatewayNotFoundError(
                    f'No active configuration for project {project.name}'
                )
            while True:
                from_datetime, to_datetime = compute_sse_time_range(_gte, _from, _to)
                result = request_event_service.get_most_requested_route(
                    project_uuid=project_uuid,
                    config=project_entry.config,
                    _from=from_datetime,
                    _to=to_datetime,
                )
                yield result if result is not None else {}
                sleep(10)

        @router.get(
            '/projects/{project_uuid}/routes/most-requested-error/stream',
            status_code=200,
            response_class=EventSourceResponse,
        )
        def stream_most_requested_error_route(
            project_uuid: UUID,
            request: Request,
            _gte: Annotated[
                int | None,
                Query(
                    description='Seconds to look back from now (mutually exclusive with _from/_to)'
                ),
            ] = None,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            _: None = Depends(validate_sse_params),
        ) -> StreamingResponse:
            project = project_service.get_by_uuid(project_uuid)
            project_entry = request.app.state.project_configs.get(project.name)
            if not project_entry:
                raise GatewayNotFoundError(
                    f'No active configuration for project {project.name}'
                )
            while True:
                from_datetime, to_datetime = compute_sse_time_range(_gte, _from, _to)
                result = request_event_service.get_most_requested_error_route(
                    project_uuid=project_uuid,
                    config=project_entry.config,
                    _from=from_datetime,
                    _to=to_datetime,
                )
                yield result if result is not None else {}
                sleep(10)

        @router.get(
            '/projects/{project_uuid}/routes/costs/stream',
            status_code=200,
            response_class=EventSourceResponse,
        )
        def stream_costs_chart(
            project_uuid: UUID,
            routes: Annotated[list[str] | None, Query()] = None,
            _gte: Annotated[
                int | None,
                Query(
                    description='Seconds to look back from now (mutually exclusive with _from/_to)'
                ),
            ] = None,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            group_by: Literal['keys', 'groups', 'models'] = Query(),
            _: None = Depends(validate_sse_params),
        ) -> StreamingResponse:
            project_service.validate_exists(project_uuid)
            while True:
                from_datetime, to_datetime = compute_sse_time_range(_gte, _from, _to)
                result = event_service.get_costs_chart_data(
                    project_uuid=project_uuid,
                    route_names=routes,
                    _from=from_datetime,
                    _to=to_datetime,
                    group_by=group_by,
                )
                yield result.model_dump(by_alias=True)
                sleep(10)

        @router.get(
            '/projects/{project_uuid}/routes/costs/key/{key_uuid}/stream',
            status_code=200,
            response_class=EventSourceResponse,
        )
        def stream_costs_chart_by_key(
            project_uuid: UUID,
            key_uuid: UUID,
            routes: Annotated[list[str] | None, Query()] = None,
            _gte: Annotated[
                int | None,
                Query(
                    description='Seconds to look back from now (mutually exclusive with _from/_to)'
                ),
            ] = None,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            _: None = Depends(validate_sse_params),
        ) -> StreamingResponse:
            project_service.validate_exists(project_uuid)
            while True:
                from_datetime, to_datetime = compute_sse_time_range(_gte, _from, _to)
                result = event_service.get_costs_chart_data_by_route(
                    project_uuid=project_uuid,
                    entity_column='API_KEY_UUID',
                    entity_value=str(key_uuid),
                    route_names=routes,
                    _from=from_datetime,
                    _to=to_datetime,
                )
                yield result.model_dump(by_alias=True)
                sleep(10)

        @router.get(
            '/projects/{project_uuid}/routes/costs/group/{group_uuid}/stream',
            status_code=200,
            response_class=EventSourceResponse,
        )
        def stream_costs_chart_by_group(
            project_uuid: UUID,
            group_uuid: UUID,
            routes: Annotated[list[str] | None, Query()] = None,
            _gte: Annotated[
                int | None,
                Query(
                    description='Seconds to look back from now (mutually exclusive with _from/_to)'
                ),
            ] = None,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            _: None = Depends(validate_sse_params),
        ) -> StreamingResponse:
            project_service.validate_exists(project_uuid)
            while True:
                from_datetime, to_datetime = compute_sse_time_range(_gte, _from, _to)
                result = event_service.get_costs_chart_data_by_route(
                    project_uuid=project_uuid,
                    entity_column='GROUP_UUID',
                    entity_value=str(group_uuid),
                    route_names=routes,
                    _from=from_datetime,
                    _to=to_datetime,
                )
                yield result.model_dump(by_alias=True)
                sleep(10)

        @router.get(
            '/projects/{project_uuid}/routes/costs/model/{model_id}/stream',
            status_code=200,
            response_class=EventSourceResponse,
        )
        def stream_costs_chart_by_model(
            project_uuid: UUID,
            model_id: str,
            routes: Annotated[list[str] | None, Query()] = None,
            _gte: Annotated[
                int | None,
                Query(
                    description='Seconds to look back from now (mutually exclusive with _from/_to)'
                ),
            ] = None,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            _: None = Depends(validate_sse_params),
        ) -> StreamingResponse:
            project_service.validate_exists(project_uuid)
            while True:
                from_datetime, to_datetime = compute_sse_time_range(_gte, _from, _to)
                result = event_service.get_costs_chart_data_by_route(
                    project_uuid=project_uuid,
                    entity_column='MODEL_ID',
                    entity_value=model_id,
                    route_names=routes,
                    _from=from_datetime,
                    _to=to_datetime,
                )
                yield result.model_dump(by_alias=True)
                sleep(10)

        @router.get(
            '/projects/{project_uuid}/routes/costs/model/{model_id}/breakdown',
            status_code=200,
            response_model=list[ModelCostDTO],
        )
        def get_cost_breakdown_by_model(
            project_uuid: UUID,
            model_id: str,
            timestamp: int,
            granularity: Literal['hours', 'days', 'weeks', 'months'],
            routes: Annotated[list[str] | None, Query()] = None,
        ) -> list[ModelCostDTO]:
            project_service.validate_exists(project_uuid)
            return event_service.get_cost_breakdown(
                project_uuid=project_uuid,
                entity_column='MODEL_ID',
                entity_value=model_id,
                timestamp=timestamp,
                granularity=granularity,
                routes=routes,
            )

        @router.get(
            '/projects/{project_uuid}/routes/costs/key/{key_uuid}/breakdown',
            status_code=200,
            response_model=list[ModelCostDTO],
        )
        def get_cost_breakdown_by_key(
            project_uuid: UUID,
            key_uuid: UUID,
            timestamp: int,
            granularity: Literal['hours', 'days', 'weeks', 'months'],
            routes: Annotated[list[str] | None, Query()] = None,
        ) -> list[ModelCostDTO]:
            project_service.validate_exists(project_uuid)
            return event_service.get_cost_breakdown(
                project_uuid=project_uuid,
                entity_column='API_KEY_UUID',
                entity_value=str(key_uuid),
                timestamp=timestamp,
                granularity=granularity,
                routes=routes,
            )

        @router.get(
            '/projects/{project_uuid}/routes/costs/group/{group_uuid}/breakdown',
            status_code=200,
            response_model=list[ModelCostDTO],
        )
        def get_cost_breakdown_by_group(
            project_uuid: UUID,
            group_uuid: UUID,
            timestamp: int,
            granularity: Literal['hours', 'days', 'weeks', 'months'],
            routes: Annotated[list[str] | None, Query()] = None,
        ) -> list[ModelCostDTO]:
            project_service.validate_exists(project_uuid)
            return event_service.get_cost_breakdown(
                project_uuid=project_uuid,
                entity_column='GROUP_UUID',
                entity_value=str(group_uuid),
                timestamp=timestamp,
                granularity=granularity,
                routes=routes,
            )

        @router.get(
            '/projects/{project_uuid}/routes/costs/summary/stream',
            status_code=200,
            response_class=EventSourceResponse,
        )
        def stream_costs_summary(
            project_uuid: UUID,
            request: Request,
            routes: Annotated[list[str] | None, Query()] = None,
            _gte: Annotated[
                int | None,
                Query(
                    description='Seconds to look back from now (mutually exclusive with _from/_to)'
                ),
            ] = None,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            _with_saved_tokens: bool = Query(False),
            _: None = Depends(validate_sse_params),
        ) -> StreamingResponse:
            project = project_service.get_by_uuid(project_uuid)
            project_entry = request.app.state.project_configs.get(project.name)
            if not project_entry:
                raise GatewayNotFoundError(
                    f'No active configuration for project {project.name}'
                )
            while True:
                from_datetime, to_datetime = compute_sse_time_range(_gte, _from, _to)
                result = event_service.get_summary_costs(
                    project_uuid=project_uuid,
                    config=project_entry.config,
                    route_names=routes,
                    _from=from_datetime,
                    _to=to_datetime,
                    _with_saved_tokens=_with_saved_tokens,
                )
                yield result.model_dump(exclude_none=True, by_alias=True)
                sleep(10)

        @router.get(
            '/projects/{project_uuid}/routes/most-expensive/stream',
            status_code=200,
            response_class=EventSourceResponse,
        )
        def stream_most_expensive_route(
            project_uuid: UUID,
            request: Request,
            _gte: Annotated[
                int | None,
                Query(
                    description='Seconds to look back from now (mutually exclusive with _from/_to)'
                ),
            ] = None,
            _from: Annotated[int | None, Query()] = None,
            _to: Annotated[int | None, Query()] = None,
            _: None = Depends(validate_sse_params),
        ) -> StreamingResponse:
            project = project_service.get_by_uuid(project_uuid)
            project_entry = request.app.state.project_configs.get(project.name)
            if not project_entry:
                raise GatewayNotFoundError(
                    f'No active configuration for project {project.name}'
                )
            while True:
                from_datetime, to_datetime = compute_sse_time_range(_gte, _from, _to)
                result = event_service.get_most_expensive_route(
                    project_uuid=project_uuid,
                    config=project_entry.config,
                    _from=from_datetime,
                    _to=to_datetime,
                )
                yield result if result is not None else {}
                sleep(10)

        return router
