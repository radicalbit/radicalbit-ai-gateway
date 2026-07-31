import asyncio
import contextlib
from datetime import datetime, timezone
import logging
from typing import Literal
from uuid import UUID

from radicalbit_ai_gateway.db.dao.event_dao import EventDAO
from radicalbit_ai_gateway.db.dao.request_event_dao import RequestEventDAO
from radicalbit_ai_gateway.db.models.event import (
    CostData,
    DetailedCostBreakdown,
    EventDetails,
    LastEventFallback,
    LastEventGuardrail,
    TokensCounter,
)
from radicalbit_ai_gateway.models.event_dto import (
    CacheHitEventDetailDTO,
    ChartDataSeriesDTO,
    CostChartDataDTO,
    CostChartDataSeriesDTO,
    CostDataDTO,
    EventsDTO,
    FallbackEventDetailDTO,
    GuardrailEventDetailDTO,
    InvocationChartDataDTO,
    LastNEvents,
    ModelCostDTO,
    MostExpensiveRouteChartDataDTO,
    MostExpensiveRouteDTO,
    RateLimitEventDetailDTO,
    RouteCostDTO,
    RouteProgressBarDTO,
    RouteProgressBarsDTO,
    TokenChartDataDTO,
    TokenChartDataSeriesDTO,
    TokenInputLimitEventDetailDTO,
    TokenOutputLimitEventDetailDTO,
    TokensCounterDTO,
    UsageCostsDTO,
    WindowProgressBarDTO,
    WindowStatus,
)
from radicalbit_ai_gateway.models.event_type import EventType
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.gateway_config_out import GatewayRouteConfigOut
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.gateway_route_out import GatewayRouteOut
from radicalbit_ai_gateway.services.group_service import GroupService
from radicalbit_ai_gateway.services.key_service import KeyService
from radicalbit_ai_gateway.utils import BUDGET_MULTIPLIER
from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.chart_utils import (
    calculate_increment_percentage,
    determine_granularity,
    generate_chart_timestamps,
    get_bucket_end_timestamp,
    prepare_chart_time_range,
)

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


class EventService:
    def __init__(
        self,
        event_dao: EventDAO,
        key_service: KeyService,
        group_service: GroupService,
        request_event_dao: RequestEventDAO,
    ):
        self.event_dao = event_dao
        self.key_service = key_service
        self.group_service = group_service
        self.request_event_dao = request_event_dao

    @staticmethod
    def clean_model_empty_strings(e: EventDetails) -> EventDetails:
        optional_fields = [
            'target',
            'fallback',
            'name',
            'type',
            'where',
            'parameters',
            'behavior',
        ]
        for field_name, current_value in e:
            if current_value == '' and field_name in optional_fields:
                setattr(e, field_name, None)
        return e

    @staticmethod
    def _total_counter_per_metric(tokens_counter: list[TokensCounter]) -> int:
        return sum(i.value for i in tokens_counter)

    def _resolve_last_event_key_names(
        self,
        last_events: list[LastEventGuardrail | LastEventFallback],
    ) -> None:
        if not last_events:
            return
        uuids_to_resolve = list({e.api_key_uuid for e in last_events})
        names_map = self.key_service.get_names_by_uuids(uuids_to_resolve)
        for e in last_events:
            e.api_key_name = names_map.get(
                e.api_key_uuid,
                f'Deleted Key ({str(e.api_key_uuid)[:8]})',
            )

    def _calculate_token_metrics(
        self, tokens_counter: list[TokensCounter], route_name: str | None = None
    ) -> TokensCounterDTO:
        tokens_counter_dto = TokensCounterDTO()

        def _filter_by_type(event_type: str) -> list[TokensCounter]:
            if route_name:
                return [
                    i
                    for i in tokens_counter
                    if i.event_type == event_type and i.route_name == route_name
                ]
            return [i for i in tokens_counter if i.event_type == event_type]

        if tokens_counter:
            input_tokens_processed = _filter_by_type('INPUT_TOKEN_PROCESSED')
            output_tokens_processed = _filter_by_type('OUTPUT_TOKEN_PROCESSED')
            cache_saved_tokens_input = _filter_by_type('CACHE_INPUT_TOKENS')
            cache_saved_tokens_output = _filter_by_type('CACHE_OUTPUT_TOKENS')

            tokens_counter_dto.total_input_token_processed = (
                self._total_counter_per_metric(input_tokens_processed)
            )
            tokens_counter_dto.total_output_token_processed = (
                self._total_counter_per_metric(output_tokens_processed)
            )
            tokens_counter_dto.cache_saved_tokens_input = (
                self._total_counter_per_metric(cache_saved_tokens_input)
            )
            tokens_counter_dto.cache_saved_tokens_output = (
                self._total_counter_per_metric(cache_saved_tokens_output)
            )
        return tokens_counter_dto

    def _get_metrics_per_route(
        self,
        project_uuid: UUID,
        config: GatewayConfig,
        route_name: str,
        _from: datetime | None,
        _to: datetime | None,
    ):
        counters = self.event_dao.get_all_counters_by_route(
            project_uuid, route_name, _from=_from, _to=_to
        )
        tokens_counter = self.event_dao.get_tokens_by_model_per_route(
            project_uuid, route_name, _from=_from, _to=_to
        )
        last_event_guardrail = self.event_dao.get_last_event_route(
            project_uuid, EventType.GUARDRAIL, route_name, _from=_from, _to=_to
        )
        last_event_fallback = self.event_dao.get_last_event_route(
            project_uuid, EventType.FALLBACK, route_name, _from=_from, _to=_to
        )
        routing_model_counters = self.event_dao.get_routing_model_counters(
            project_uuid, _from=_from, _to=_to, route_name=route_name
        )
        request_stats = self.request_event_dao.get_request_stats_by_route(
            project_uuid, route_name, _from=_from, _to=_to
        )
        error_details = self.request_event_dao.get_error_breakdown(
            project_uuid, route_name, _from=_from, _to=_to
        )

        tokens_counter_dto = self._calculate_token_metrics(
            tokens_counter=tokens_counter, route_name=route_name
        )

        if last_event_guardrail:
            assert isinstance(last_event_guardrail, LastEventGuardrail)
        if last_event_fallback:
            assert isinstance(last_event_fallback, LastEventFallback)

        self._resolve_last_event_key_names(
            [e for e in [last_event_guardrail, last_event_fallback] if e]
        )

        return EventsDTO.from_dao_per_route(
            config=config,
            route_name=route_name,
            counters=counters,
            tokens_counter_dto=tokens_counter_dto,
            last_event_guardrail=last_event_guardrail,
            last_event_fallback=last_event_fallback,
            routing_model_counters=routing_model_counters,
            request_stats=request_stats,
            error_details=error_details,
        )

    def get_total_counter(
        self,
        project_uuid: UUID,
        config: GatewayConfig,
        _from: datetime | None,
        _to: datetime | None,
    ) -> EventsDTO:
        tokens_counter = self.event_dao.get_tokens_by_model(
            project_uuid, _from=_from, _to=_to
        )
        counters = self.event_dao.get_all_counters(project_uuid, _from=_from, _to=_to)
        last_event_guardrail = self.event_dao.get_last_event(
            project_uuid, EventType.GUARDRAIL, _from=_from, _to=_to
        )
        last_event_fallback = self.event_dao.get_last_event(
            project_uuid, EventType.FALLBACK, _from=_from, _to=_to
        )
        routing_model_counters = self.event_dao.get_routing_model_counters(
            project_uuid, _from=_from, _to=_to
        )
        request_stats = self.request_event_dao.get_request_stats_global(
            project_uuid, _from=_from, _to=_to
        )
        error_details = self.request_event_dao.get_error_breakdown(
            project_uuid, None, _from=_from, _to=_to
        )

        tokens_counter_dto = self._calculate_token_metrics(
            tokens_counter=tokens_counter,
            route_name=None,
        )

        if last_event_guardrail:
            assert isinstance(last_event_guardrail, LastEventGuardrail)
        if last_event_fallback:
            assert isinstance(last_event_fallback, LastEventFallback)

        # TODO: Implement soft delete for keys in Postgres (deleted_at column)
        # so that deleted keys still have resolvable names, removing the need for this fallback.
        self._resolve_last_event_key_names(
            [e for e in [last_event_guardrail, last_event_fallback] if e]
        )

        return EventsDTO.from_dao_global(
            config=config,
            counters=counters,
            tokens_counter_dto=tokens_counter_dto,
            last_event_guardrail=last_event_guardrail,
            last_event_fallback=last_event_fallback,
            routing_model_counters=routing_model_counters,
            request_stats=request_stats,
            error_details=error_details,
        )

    def get_total_counter_per_route(
        self,
        project_uuid: UUID,
        project_name: str,
        config: GatewayConfig,
        include_groups: bool,
        _from: datetime | None,
        _to: datetime | None,
    ) -> list[GatewayRouteOut]:
        routes_out = []
        for route_name, route_config in config.routes.items():
            configuration = self._build_route_config_out(route_config, config)
            groups = None
            if include_groups:
                groups = self.group_service.get_all_groups_by_route(
                    project_name, route_name
                )
            routes_out.append(
                GatewayRouteOut(
                    route_name=route_name,
                    configuration=configuration,
                    metrics=self._get_metrics_per_route(
                        project_uuid=project_uuid,
                        config=config,
                        route_name=route_name,
                        _from=_from,
                        _to=_to,
                    ),
                    groups=groups,
                )
            )
        return routes_out

    def get_counter_per_route(
        self,
        project_uuid: UUID,
        project_name: str,
        config: GatewayConfig,
        route_name: str,
        include_groups: bool,
        _from: datetime | None,
        _to: datetime | None,
    ) -> GatewayRouteOut:
        route_config = config.routes[route_name]
        configuration = self._build_route_config_out(route_config, config)
        groups = None
        if include_groups:
            groups = self.group_service.get_all_groups_by_route(
                project_name, route_name
            )
        return GatewayRouteOut(
            route_name=route_name,
            configuration=configuration,
            metrics=self._get_metrics_per_route(
                project_uuid=project_uuid,
                config=config,
                route_name=route_name,
                _from=_from,
                _to=_to,
            ),
            groups=groups,
        )

    def get_latest_n_per_event_type(
        self,
        project_uuid: UUID,
        config: GatewayConfig,
        route_name: str,
        n: int,
        _from: datetime | None,
        _to: datetime | None,
    ) -> LastNEvents:
        fallbacks: list[FallbackEventDetailDTO] = []
        guardrails: list[GuardrailEventDetailDTO] = []
        rate_limit: list[RateLimitEventDetailDTO] = []
        token_input_limit: list[TokenInputLimitEventDetailDTO] = []
        token_output_limit: list[TokenOutputLimitEventDetailDTO] = []
        cache_triggered: list[CacheHitEventDetailDTO] = []

        route_config = config.routes[route_name]
        events = self.event_dao.get_latest_n_per_event_type(
            project_uuid, route_name, n, _from=_from, _to=_to
        )
        if events is None:
            return LastNEvents()

        unique_key_uuids = list({e.api_key_uuid for e in events})
        key_names_map = self.key_service.get_names_by_uuids(unique_key_uuids)

        # TODO: Implement soft delete for keys/groups in Postgres (deleted_at column)
        # so that deleted keys still have resolvable names, removing the need for this fallback.
        def _resolved_key_name(uuid: UUID) -> str:
            return key_names_map.get(uuid, f'Deleted Key ({str(uuid)[:8]})')

        for event in events:
            event.api_key_active = event.api_key_uuid in key_names_map
            resolved_name = _resolved_key_name(event.api_key_uuid)
            event = self.clean_model_empty_strings(event)

            match event.event_type:
                case 'FALLBACK':
                    fallbacks.append(
                        FallbackEventDetailDTO(
                            timestamp=event.timestamp,
                            api_key_uuid=event.api_key_uuid,
                            route_name=event.route_name,
                            api_key_name=resolved_name,
                            api_key_active=event.api_key_active,
                            event_type='FALLBACK',
                            target=event.target,
                            fallback=event.fallback,
                        )
                    )
                case 'GUARDRAIL':
                    guardrails.append(
                        GuardrailEventDetailDTO(
                            timestamp=event.timestamp,
                            api_key_uuid=event.api_key_uuid,
                            route_name=event.route_name,
                            api_key_name=resolved_name,
                            api_key_active=event.api_key_active,
                            event_type='GUARDRAIL',
                            name=event.name,
                            type=event.type,
                            where=event.where,
                            parameters=event.parameters,
                            behavior=event.behavior,
                        )
                    )
                case 'RATE_LIMIT':
                    rate_limit.append(
                        RateLimitEventDetailDTO(
                            timestamp=event.timestamp,
                            api_key_uuid=event.api_key_uuid,
                            route_name=event.route_name,
                            api_key_name=resolved_name,
                            api_key_active=event.api_key_active,
                            event_type='RATE_LIMIT',
                        )
                    )
                case 'TOKEN_INPUT_LIMIT':
                    token_input_limit.append(
                        TokenInputLimitEventDetailDTO(
                            timestamp=event.timestamp,
                            api_key_uuid=event.api_key_uuid,
                            route_name=event.route_name,
                            api_key_name=resolved_name,
                            api_key_active=event.api_key_active,
                            event_type='TOKEN_INPUT_LIMIT',
                        )
                    )
                case 'TOKEN_OUTPUT_LIMIT':
                    token_output_limit.append(
                        TokenOutputLimitEventDetailDTO(
                            timestamp=event.timestamp,
                            api_key_uuid=event.api_key_uuid,
                            route_name=event.route_name,
                            api_key_name=resolved_name,
                            api_key_active=event.api_key_active,
                            event_type='TOKEN_OUTPUT_LIMIT',
                        )
                    )
                case 'CACHE_HIT':
                    cache_triggered.append(
                        CacheHitEventDetailDTO(
                            timestamp=event.timestamp,
                            api_key_uuid=event.api_key_uuid,
                            route_name=event.route_name,
                            api_key_name=resolved_name,
                            api_key_active=event.api_key_active,
                            event_type='CACHE_HIT',
                            target=event.target,
                        )
                    )
                case _:
                    logger.warning('Unable to determine event type')

        return LastNEvents.create_dto(
            fallbacks=fallbacks,
            guardrails=guardrails,
            rate_limit=rate_limit,
            token_input_limit=token_input_limit,
            token_output_limit=token_output_limit,
            cache_triggered=cache_triggered,
            route_config=route_config,
        )

    @staticmethod
    def _build_route_config_out(
        route_config: GatewayRouteConfig,
        config: GatewayConfig,
    ) -> GatewayRouteConfigOut:
        route_dict = route_config.model_dump()

        guardrail_names: list[str] | None = route_dict.get('guardrails')
        if guardrail_names and config.guardrails:
            by_name = {g.name: g for g in config.guardrails}
            resolved_guardrails: list[dict] = []
            for name in guardrail_names:
                gr = by_name.get(name)
                if gr is None:
                    logger.warning(
                        'Guardrail %s referenced by route %s not found in top-level guardrails registry',
                        name,
                        route_config.route_name,
                    )
                    continue
                resolved_guardrails.append(gr.model_dump())
            route_dict['guardrails'] = resolved_guardrails
        else:
            route_dict['guardrails'] = []

        chat_by_id = {m.model_id: m for m in (config.chat_models or [])}
        embed_by_id = {m.model_id: m for m in (config.embedding_models or [])}
        transcription_by_id = {
            m.model_id: m for m in (config.transcription_models or [])
        }

        chat_ids: list[str] | None = route_dict.get('chat_models')
        if chat_ids is None:
            route_dict['chat_models'] = None
        else:
            resolved_chat: list[dict] = []
            for mid in chat_ids:
                chat_model = chat_by_id.get(mid)
                if chat_model is None:
                    logger.warning(
                        'Chat model_id %s referenced by route %s not found in top-level chat_models registry',
                        mid,
                        route_config.route_name,
                    )
                    continue
                resolved_chat.append(chat_model.model_dump())
            route_dict['chat_models'] = resolved_chat

        embed_ids: list[str] | None = route_dict.get('embedding_models')
        if embed_ids is None:
            route_dict['embedding_models'] = None
        else:
            resolved_embed: list[dict] = []
            for mid in embed_ids:
                embedding_model = embed_by_id.get(mid)
                if embedding_model is None:
                    logger.warning(
                        'Embedding model_id %s referenced by route %s not found in top-level embedding_models registry',
                        mid,
                        route_config.route_name,
                    )
                    continue
                resolved_embed.append(embedding_model.model_dump())
            route_dict['embedding_models'] = resolved_embed

        transcription_ids: list[str] | None = route_dict.get('transcription_models')
        if transcription_ids is None:
            route_dict['transcription_models'] = None
        else:
            resolved_transcription: list[dict] = []
            for mid in transcription_ids:
                transcription_model = transcription_by_id.get(mid)
                if transcription_model is None:
                    logger.warning(
                        'Transcription model_id %s referenced by route %s not found in top-level transcription_models registry',
                        mid,
                        route_config.route_name,
                    )
                    continue
                resolved_transcription.append(transcription_model.model_dump())
            route_dict['transcription_models'] = resolved_transcription

        routing_name: str | None = route_dict.get('routing')
        if routing_name:
            routing_config = config.routing_by_name.get(routing_name)
            route_dict['routing'] = (
                routing_config.model_dump() if routing_config else None
            )
        else:
            route_dict['routing'] = None

        mcp_aliases: list[str] | None = route_dict.get('mcp_servers')
        if mcp_aliases is None:
            route_dict['mcp_servers'] = None
        else:
            route_dict['mcp_servers'] = [
                server.model_dump()
                for server in config.get_route_mcp_servers(route_config.route_name)
            ]

        return GatewayRouteConfigOut(**route_dict)

    def get_costs_chart_data(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        group_by: Literal['keys', 'groups', 'models'],
    ) -> CostChartDataDTO:
        _from_utc, _to_utc, timezone_offset_seconds = prepare_chart_time_range(
            _from, _to
        )
        granularity = determine_granularity(_from, _to)
        chart_data_points = self.event_dao.get_costs_chart_data(
            project_uuid,
            route_names,
            _from_utc,
            _to_utc,
            granularity,
            group_by,
            timezone_offset_seconds,
        )
        if not chart_data_points:
            return CostChartDataDTO(
                granularity=granularity,
                timestamp=[],
                data=[],
                total=0.0,
            )

        _to_utc = _to_utc or datetime.now(timezone.utc)
        _from_utc = _from_utc or datetime.fromtimestamp(
            chart_data_points[0].timestamp, timezone.utc
        )

        all_timestamps = generate_chart_timestamps(
            _from_utc, _to_utc, granularity, timezone_offset_seconds
        )

        groups_data: dict[str, dict[int, float]] = {}
        for point in chart_data_points:
            groups_data.setdefault(point.group_by_value, {})[point.timestamp] = (
                point.total_cost
            )

        name_to_uuid: dict[str, UUID | None] = {}
        # TODO: Implement soft delete for keys/groups in Postgres (deleted_at column)
        # so that deleted keys still have resolvable names, removing the need for this fallback.
        if group_by in ('keys', 'groups') and groups_data:
            uuid_str_to_obj: dict[str, UUID] = {}
            for uid_str in groups_data:
                with contextlib.suppress(ValueError):
                    uuid_str_to_obj[uid_str] = UUID(uid_str)
            unique_ids = list(uuid_str_to_obj.values())
            names_map = (
                self.key_service.get_names_by_uuids(unique_ids)
                if group_by == 'keys'
                else self.group_service.get_names_by_uuids(unique_ids)
            )
            entity_label = 'Key' if group_by == 'keys' else 'Group'
            resolved: dict[str, dict[int, float]] = {}
            for uuid_str, ts_data in groups_data.items():
                uuid_obj = uuid_str_to_obj.get(uuid_str)
                if uuid_obj:
                    resolved_name = names_map.get(
                        uuid_obj,
                        f'Deleted {entity_label} ({uuid_str[:8]})',
                    )
                else:
                    resolved_name = uuid_str
                resolved.setdefault(resolved_name, {}).update(ts_data)
                name_to_uuid[resolved_name] = uuid_obj
            groups_data = resolved

        series_list = [
            CostChartDataSeriesDTO(
                name=name,
                uuid=name_to_uuid.get(name),
                data=[groups_data[name].get(ts, 0.0) for ts in all_timestamps],
            )
            for name in sorted(groups_data.keys())
        ]

        total = sum(point.total_cost for point in chart_data_points)
        return CostChartDataDTO(
            granularity=granularity,
            timestamp=all_timestamps,
            data=series_list,
            total=total,
        )

    def get_costs_chart_data_by_route(
        self,
        project_uuid: UUID,
        entity_column: Literal['API_KEY_UUID', 'GROUP_UUID', 'MODEL_ID'],
        entity_value: str,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
    ) -> CostChartDataDTO:
        _from_utc, _to_utc, timezone_offset_seconds = prepare_chart_time_range(
            _from, _to
        )
        granularity = determine_granularity(_from, _to)
        chart_data_points = self.event_dao.get_costs_chart_data_by_route(
            project_uuid,
            entity_column,
            entity_value,
            route_names,
            _from_utc,
            _to_utc,
            granularity,
            timezone_offset_seconds,
        )
        if not chart_data_points:
            return CostChartDataDTO(
                granularity=granularity, timestamp=[], data=[], total=0.0
            )

        _to_utc = _to_utc or datetime.now(timezone.utc)
        _from_utc = _from_utc or datetime.fromtimestamp(
            chart_data_points[0].timestamp, timezone.utc
        )
        all_timestamps = generate_chart_timestamps(
            _from_utc, _to_utc, granularity, timezone_offset_seconds
        )
        groups_data: dict[str, dict[int, float]] = {}
        for point in chart_data_points:
            groups_data.setdefault(point.group_by_value, {})[point.timestamp] = (
                point.total_cost
            )

        series_list = [
            CostChartDataSeriesDTO(
                name=name,
                data=[groups_data[name].get(ts, 0.0) for ts in all_timestamps],
            )
            for name in sorted(groups_data.keys())
        ]
        total = sum(point.total_cost for point in chart_data_points)
        return CostChartDataDTO(
            granularity=granularity,
            timestamp=all_timestamps,
            data=series_list,
            total=total,
        )

    def get_cost_breakdown(
        self,
        project_uuid: UUID,
        entity_column: Literal['API_KEY_UUID', 'GROUP_UUID', 'MODEL_ID'],
        entity_value: str,
        timestamp: int,
        granularity: Literal['hours', 'days', 'weeks', 'months'],
        routes: list[str] | None,
    ) -> list[ModelCostDTO]:
        _from = datetime.fromtimestamp(timestamp, timezone.utc)
        _to = get_bucket_end_timestamp(_from, granularity)
        results = self.event_dao.get_cost_breakdown_by_entity(
            project_uuid,
            entity_column,
            entity_value,
            _from,
            _to,
            routes,
        )
        return [
            ModelCostDTO(route_name=r.route_name, cost=float(r.total_cost))
            for r in results
        ]

    def get_invocation_chart_data(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        granularity: Literal['hours', 'days', 'weeks', 'months'],
        include_models: bool,
    ) -> InvocationChartDataDTO:
        _from_utc, _to_utc, timezone_offset_seconds = prepare_chart_time_range(
            _from, _to
        )
        chart_data_points = self.event_dao.get_invocation_chart_data(
            project_uuid,
            route_names,
            _from_utc,
            _to_utc,
            granularity,
            include_models,
            timezone_offset_seconds,
        )
        if not chart_data_points:
            return InvocationChartDataDTO(
                granularity=granularity,
                timestamp=[],
                data=[],
                total=0,
            )

        _to_utc = _to_utc or datetime.now(timezone.utc)
        _from_utc = _from_utc or datetime.fromtimestamp(
            chart_data_points[0].timestamp, timezone.utc
        )

        all_timestamps = generate_chart_timestamps(
            _from_utc, _to_utc, granularity, timezone_offset_seconds
        )

        groups_data: dict[str, dict[int, float]] = {}
        for point in chart_data_points:
            groups_data.setdefault(point.group_by_value, {})[point.timestamp] = (
                point.value
            )
        total = sum(point.value for point in chart_data_points)
        if include_models:
            series_list = [
                ChartDataSeriesDTO(
                    name=group_name,
                    data=[
                        groups_data[group_name].get(ts, 0.0) for ts in all_timestamps
                    ],
                )
                for group_name in sorted(groups_data.keys())
            ]
            return InvocationChartDataDTO(
                granularity=granularity,
                timestamp=all_timestamps,
                data=series_list,
                total=total,
            )
        aggregated = [
            sum(group.get(ts, 0.0) for group in groups_data.values())
            for ts in all_timestamps
        ]
        return InvocationChartDataDTO(
            granularity=granularity,
            timestamp=all_timestamps,
            data=aggregated,
            total=total,
        )

    def get_summary_costs(
        self,
        project_uuid: UUID,
        config: GatewayConfig,
        route_names: list[str] | None = None,
        _from: datetime | None = None,
        _to: datetime | None = None,
        _with_saved_tokens: bool = False,
    ) -> CostDataDTO:
        all_route_names = list(config.routes.keys())
        routes_to_query = route_names if route_names is not None else all_route_names

        cache_enabled = False
        has_chat_models = False
        has_judges = False
        has_embedding_models = False
        has_semantic_cache = False
        has_transcription_models = False
        for rn in routes_to_query:
            route_config = config.routes.get(rn)
            if route_config is None:
                continue
            if config.cache is not None and route_config.caching is not None:
                cache_enabled = True
            (
                route_has_chat_models,
                route_has_judge,
                route_has_embedding_models,
                route_has_semantic_cache,
                route_has_transcription_models,
            ) = config.get_route_feature_flags(route_config)
            has_chat_models = has_chat_models or route_has_chat_models
            has_judges = has_judges or route_has_judge
            has_embedding_models = has_embedding_models or route_has_embedding_models
            has_semantic_cache = has_semantic_cache or route_has_semantic_cache
            has_transcription_models = (
                has_transcription_models or route_has_transcription_models
            )

        dao_route_names = None if route_names is None else routes_to_query

        costs_data = self.event_dao.get_summary_costs(
            project_uuid,
            dao_route_names,
            _from,
            _to,
            cache_enabled,
            _with_saved_tokens,
        )
        if has_semantic_cache:
            semantic_cache_costs = self.event_dao.get_semantic_cache_details(
                project_uuid,
                dao_route_names,
                _from,
                _to,
                _with_saved_tokens,
            )
        else:
            semantic_cache_costs = None

        detailed_breakdown = self.event_dao.get_detailed_cost_breakdown(
            project_uuid, dao_route_names, _from, _to
        )

        return CostDataDTO.from_dao(
            costs_data,
            semantic_cache_costs,
            detailed_breakdown,
            has_chat_models=has_chat_models,
            has_judges=has_judges,
            has_embedding_models=has_embedding_models,
            has_semantic_cache=has_semantic_cache,
            has_transcription_models=has_transcription_models,
        )

    def get_token_chart_data(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        granularity: Literal['hours', 'days', 'weeks', 'months'],
    ) -> TokenChartDataDTO:
        _from_utc, _to_utc, timezone_offset_seconds = prepare_chart_time_range(
            _from, _to
        )
        token_chart_data_points = self.event_dao.get_token_chart_data(
            project_uuid,
            route_names,
            _from_utc,
            _to_utc,
            granularity,
            timezone_offset_seconds,
        )
        if not token_chart_data_points:
            return TokenChartDataDTO(
                total=0,
                granularity=granularity,
                timestamp=[],
                data=[],
            )

        _to_utc = _to_utc or datetime.now(timezone.utc)
        _from_utc = _from_utc or datetime.fromtimestamp(
            token_chart_data_points[0].timestamp, timezone.utc
        )

        all_timestamps = generate_chart_timestamps(
            _from_utc, _to_utc, granularity, timezone_offset_seconds
        )

        event_type_data: dict[str, dict[int, int]] = {}
        total_tokens = 0
        for point in token_chart_data_points:
            event_type_data.setdefault(point.event_type, {})[point.timestamp] = (
                point.total_tokens
            )
            total_tokens += point.total_tokens

        input_series_data = event_type_data.get('INPUT_TOKEN_PROCESSED', {})
        output_series_data = event_type_data.get('OUTPUT_TOKEN_PROCESSED', {})

        series_list = [
            TokenChartDataSeriesDTO(
                name='INPUT',
                data=[input_series_data.get(ts, 0) for ts in all_timestamps],
            ),
            TokenChartDataSeriesDTO(
                name='OUTPUT',
                data=[output_series_data.get(ts, 0) for ts in all_timestamps],
            ),
        ]

        return TokenChartDataDTO(
            total=total_tokens,
            granularity=granularity,
            timestamp=all_timestamps,
            data=series_list,
        )

    def get_all_routes_costs(
        self,
        project_uuid: UUID,
        config: GatewayConfig,
        _from: datetime | None = None,
        _to: datetime | None = None,
        _with_saved_tokens: bool = False,
    ) -> UsageCostsDTO:

        route_cost_data_list = self.event_dao.get_all_routes_summary_costs(
            project_uuid, _from, _to, _with_saved_tokens
        )
        cost_by_route = {data.route_name: data for data in route_cost_data_list}

        detailed_breakdowns = self.event_dao.get_all_routes_detailed_cost_breakdown(
            project_uuid, _from, _to
        )
        breakdown_by_route = {b.route_name: b for b in detailed_breakdowns}

        total = 0.0
        route_dtos: list[RouteCostDTO] = []

        for route_name in config.routes:
            route_config = config.routes[route_name]
            cache_enabled = (
                config.cache is not None and route_config.caching is not None
            )

            if route_name in cost_by_route:
                cost_data = cost_by_route[route_name]
                if not cache_enabled:
                    cost_data = CostData(
                        input_cost=cost_data.input_cost,
                        output_cost=cost_data.output_cost,
                        total_cost=cost_data.total_cost,
                        cache_triggered=None,
                        saved_amount_input=None,
                        saved_amount_output=None,
                        total_saved_amount=None,
                        cache_saved_tokens_input=None,
                        cache_saved_tokens_output=None,
                        total_cached_tokens=None,
                    )
            else:
                cost_data = CostData(
                    input_cost=0.0,
                    output_cost=0.0,
                    total_cost=0.0,
                    cache_triggered=0 if cache_enabled else None,
                    saved_amount_input=0.0 if cache_enabled else None,
                    saved_amount_output=0.0 if cache_enabled else None,
                    total_saved_amount=0.0 if cache_enabled else None,
                    cache_saved_tokens_input=0
                    if (cache_enabled and _with_saved_tokens)
                    else None,
                    cache_saved_tokens_output=0
                    if (cache_enabled and _with_saved_tokens)
                    else None,
                    total_cached_tokens=0
                    if (cache_enabled and _with_saved_tokens)
                    else None,
                )

            detailed_breakdown = breakdown_by_route.get(
                route_name,
                DetailedCostBreakdown(),
            )

            (
                has_chat_models,
                has_judges,
                has_embedding_models,
                has_semantic_cache,
                has_transcription_models,
            ) = config.get_route_feature_flags(route_config)

            cost_dto = CostDataDTO.from_dao(
                cost_data,
                None,
                detailed_breakdown,
                has_chat_models=has_chat_models,
                has_judges=has_judges,
                has_embedding_models=has_embedding_models,
                has_semantic_cache=has_semantic_cache,
                has_transcription_models=has_transcription_models,
            )

            total += (
                cost_dto.total
                if cost_dto.total is not None
                else cost_dto.total_cost or 0.0
            )

            route_dtos.append(RouteCostDTO(route_name=route_name, summary=cost_dto))

        return UsageCostsDTO(total=total, routes=route_dtos)

    def get_most_expensive_route(
        self,
        project_uuid: UUID,
        config: GatewayConfig,
        _from: datetime | None = None,
        _to: datetime | None = None,
    ) -> MostExpensiveRouteDTO | None:
        configured_routes = list(config.routes.keys())
        route = self.event_dao.get_most_expensive_route(
            project_uuid, configured_routes, _from=_from, _to=_to
        )
        if route is None:
            return None

        _from_utc, _to_utc, timezone_offset_seconds = prepare_chart_time_range(
            _from, _to
        )
        granularity = determine_granularity(_from, _to)
        chart_data_points = self.event_dao.get_cost_chart_data(
            project_uuid,
            route.route_name,
            _from_utc,
            _to_utc,
            granularity,
            timezone_offset_seconds,
        )

        if not chart_data_points:
            return MostExpensiveRouteDTO(
                name=route.route_name,
                increment_percentage=0.0,
                chart=MostExpensiveRouteChartDataDTO(
                    total=route.total_cost,
                    granularity=granularity,
                    timestamp=[],
                    data=[],
                ),
            )

        _to_utc = _to_utc or datetime.now(timezone.utc)
        _from_utc = _from_utc or datetime.fromtimestamp(
            chart_data_points[0].timestamp, timezone.utc
        )

        all_timestamps = generate_chart_timestamps(
            _from_utc, _to_utc, granularity, timezone_offset_seconds
        )

        bucket_data: dict[int, float] = {}
        for point in chart_data_points:
            bucket_data[point.timestamp] = point.cost

        data = [bucket_data.get(ts, 0) for ts in all_timestamps]
        increment_percentage = calculate_increment_percentage(data)
        chart = MostExpensiveRouteChartDataDTO(
            total=route.total_cost,
            granularity=granularity,
            timestamp=all_timestamps,
            data=data,
        )
        return MostExpensiveRouteDTO(
            name=route.route_name,
            increment_percentage=increment_percentage,
            chart=chart,
        )

    @staticmethod
    async def _get_progress_bar(
        limiter, item, is_budget: bool = False
    ) -> WindowProgressBarDTO | None:
        if limiter is None or item is None:
            return None
        stats = await limiter.get_window_stats(item)
        limit = item.limit
        filled = limit - stats.remaining
        if is_budget:
            window_size = limit / BUDGET_MULTIPLIER
            window_filled = filled / BUDGET_MULTIPLIER
        else:
            window_size = float(limit)
            window_filled = float(max(0, filled))
        pct = (window_filled / window_size * 100) if window_size > 0 else 0.0
        return WindowProgressBarDTO(
            window_length=item.window_seconds,
            window_start_time=stats.reset_time - item.window_seconds,
            window_end_time=stats.reset_time,
            window_size=window_size,
            window_filled_size=window_filled,
            window_filled_percentage=pct,
        )

    async def get_route_limits_progress(
        self,
        gateway_routes: dict,
        project_name: str,
        route_names: list[str] | None,
        window_statuses: list[WindowStatus] | None = None,
    ) -> list[RouteProgressBarDTO]:
        prefix = f'{project_name}/'
        if route_names is not None:
            routes_to_check = {
                name: gateway_routes[f'{prefix}{name}']
                for name in route_names
                if f'{prefix}{name}' in gateway_routes
            }
        else:
            routes_to_check = {
                key[len(prefix) :]: value for key, value in gateway_routes.items()
            }

        async def _get_route_progress(
            route_name: str, gateway_route
        ) -> RouteProgressBarDTO:
            token_limiter = gateway_route.token_limiter
            budget_limiter = gateway_route.budget_limiter
            req_rate_limiter = gateway_route.request_rate_limiter

            (
                budget_bar,
                token_input_bar,
                token_output_bar,
                rate_bar,
            ) = await asyncio.gather(
                self._get_progress_bar(
                    getattr(budget_limiter, 'limiter', None),
                    getattr(budget_limiter, 'item', None),
                    is_budget=True,
                ),
                self._get_progress_bar(
                    getattr(token_limiter, 'input_limiter', None),
                    getattr(token_limiter, 'input_item', None),
                ),
                self._get_progress_bar(
                    getattr(token_limiter, 'output_limiter', None),
                    getattr(token_limiter, 'output_item', None),
                ),
                self._get_progress_bar(
                    getattr(req_rate_limiter, 'limiter', None),
                    getattr(req_rate_limiter, 'item', None),
                ),
            )

            has_any = any(
                v is not None
                for v in [budget_bar, token_input_bar, token_output_bar, rate_bar]
            )
            return RouteProgressBarDTO(
                route_name=route_name,
                progress_bar=RouteProgressBarsDTO(
                    budget=budget_bar,
                    token_input=token_input_bar,
                    token_output=token_output_bar,
                    rate=rate_bar,
                )
                if has_any
                else None,
            )

        results = list(
            await asyncio.gather(
                *[
                    _get_route_progress(name, route)
                    for name, route in routes_to_check.items()
                ]
            )
        )

        if window_statuses is None:
            return results

        filtered = []
        for route in results:
            pb = route.progress_bar
            if WindowStatus.OK in window_statuses:
                if pb is None:
                    filtered.append(route)
                    continue
                windows = [
                    w
                    for w in [pb.budget, pb.token_input, pb.token_output, pb.rate]
                    if w is not None
                ]
                if all(w.window_status == WindowStatus.OK for w in windows):
                    filtered.append(route)
                    continue
            if pb is not None:
                windows = [
                    w
                    for w in [pb.budget, pb.token_input, pb.token_output, pb.rate]
                    if w is not None
                ]
                if WindowStatus.WARNING in window_statuses and any(
                    w.window_status == WindowStatus.WARNING for w in windows
                ):
                    filtered.append(route)
                    continue
                if WindowStatus.CRITICAL in window_statuses and any(
                    w.window_status == WindowStatus.CRITICAL for w in windows
                ):
                    filtered.append(route)
                    continue
        return filtered
