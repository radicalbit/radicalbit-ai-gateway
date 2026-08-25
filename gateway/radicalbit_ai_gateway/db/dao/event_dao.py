from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import Float, String, and_, desc, func as F, literal, select, text

from radicalbit_ai_gateway.db.clickhouse_database import ClickHouseDatabase
from radicalbit_ai_gateway.db.dao.tags_filter import add_tags_filter
from radicalbit_ai_gateway.db.models.event import (
    CostChartDataPoint,
    CostData,
    Counters,
    DetailedCostBreakdown,
    EventDetails,
    InvocationChartDataPoint,
    LastEventFallback,
    LastEventGuardrail,
    ModelInvocationCounter,
    MostExpensiveChartData,
    MostExpensiveRoute,
    RouteCostBreakdown,
    RouteCostData,
    RouteDetailedCostBreakdown,
    SemanticCacheCostData,
    TokenChartDataPoint,
    TokensCounter,
)
from radicalbit_ai_gateway.db.tables.event_table import Event
from radicalbit_ai_gateway.utils.chart_utils import (
    get_bucket_function,
    with_timezone_offset,
)


class EventDAO:
    def __init__(self, database: ClickHouseDatabase):
        self.db = database
        self.T = Event.__table__
        self.ATTRIBUTES = self.T.c['ATTRIBUTES']
        self._token_metric_types = [
            'INPUT_TOKEN_PROCESSED',
            'OUTPUT_TOKEN_PROCESSED',
            'CACHE_INPUT_TOKENS',
            'CACHE_OUTPUT_TOKENS',
        ]

    def _count_metric(self, event_type: str):
        return F.sumIf(literal(1), self.T.c['EVENT_TYPE'] == event_type)

    def _get_metric_columns(self) -> list:
        return [
            self._count_metric('GUARDRAIL').label('guardrail_value'),
            self._count_metric('FALLBACK').label('fallback_value'),
            self._count_metric('ROUTING').label('routing_value'),
            self._count_metric('RATE_LIMIT').label('rate_limit_triggered'),
            self._count_metric('TOKEN_INPUT_LIMIT').label(
                'token_input_limit_triggered'
            ),
            self._count_metric('TOKEN_OUTPUT_LIMIT').label(
                'token_output_limit_triggered'
            ),
            self._count_metric('CACHE_HIT').label('cache_triggered'),
        ]

    def _get_detailed_cost_breakdown_columns(self) -> list:
        T = self.T

        chat_input_direct = F.sumIf(
            T.c['COST'],
            F.and_(
                T.c['EVENT_TYPE'] == 'INPUT_TOKEN_PROCESSED',
                T.c['MODEL_TYPE'] == 'chat-model',
                T.c['IS_CACHED_TOKENS'] == False,  # noqa: E712
                T.c['IS_JUDGE'] == False,  # noqa: E712
            ),
        )

        chat_input_cached = F.sumIf(
            T.c['COST'],
            F.and_(
                T.c['EVENT_TYPE'] == 'INPUT_TOKEN_PROCESSED',
                T.c['MODEL_TYPE'] == 'chat-model',
                T.c['IS_CACHED_TOKENS'] == True,  # noqa: E712
                T.c['IS_JUDGE'] == False,  # noqa: E712
            ),
        )

        chat_input_judges = F.sumIf(
            T.c['COST'],
            F.and_(
                T.c['EVENT_TYPE'] == 'INPUT_TOKEN_PROCESSED',
                T.c['MODEL_TYPE'] == 'chat-model',
                T.c['IS_JUDGE'] == True,  # noqa: E712
                T.c['IS_CACHED_TOKENS'] == False,  # noqa: E712
            ),
        )

        chat_input_judges_cached = F.sumIf(
            T.c['COST'],
            F.and_(
                T.c['EVENT_TYPE'] == 'INPUT_TOKEN_PROCESSED',
                T.c['MODEL_TYPE'] == 'chat-model',
                T.c['IS_JUDGE'] == True,  # noqa: E712
                T.c['IS_CACHED_TOKENS'] == True,  # noqa: E712
            ),
        )

        chat_output_direct = F.sumIf(
            T.c['COST'],
            F.and_(
                T.c['EVENT_TYPE'] == 'OUTPUT_TOKEN_PROCESSED',
                T.c['MODEL_TYPE'] == 'chat-model',
                T.c['IS_JUDGE'] == False,  # noqa: E712
            ),
        )

        chat_output_judges = F.sumIf(
            T.c['COST'],
            F.and_(
                T.c['EVENT_TYPE'] == 'OUTPUT_TOKEN_PROCESSED',
                T.c['IS_JUDGE'] == True,  # noqa: E712
            ),
        )

        embedding_input_total = F.sumIf(
            T.c['COST'],
            F.and_(
                T.c['EVENT_TYPE'] == 'INPUT_TOKEN_PROCESSED',
                T.c['MODEL_TYPE'] == 'embeddings',
            ),
        )

        embedding_input_direct = F.sumIf(
            T.c['COST'],
            F.and_(
                T.c['EVENT_TYPE'] == 'INPUT_TOKEN_PROCESSED',
                T.c['MODEL_TYPE'] == 'embeddings',
                F.or_(
                    T.c['CACHE_TYPE'] == '',
                    T.c['CACHE_TYPE'] == 'exact',
                ),
            ),
        )

        embedding_input_semantic_cache = F.sumIf(
            T.c['COST'],
            F.and_(
                T.c['EVENT_TYPE'] == 'INPUT_TOKEN_PROCESSED',
                T.c['MODEL_TYPE'] == 'embeddings',
                T.c['CACHE_TYPE'] == 'semantic',
            ),
        )

        transcription_duration = F.sumIf(
            T.c['COST'],
            F.and_(
                T.c['EVENT_TYPE'] == 'INPUT_TOKEN_PROCESSED',
                T.c['MODEL_TYPE'] == 'transcription',
                T.c['CACHE_TYPE'] == 'duration',
            ),
        )

        transcription_audio = F.sumIf(
            T.c['COST'],
            F.and_(
                T.c['EVENT_TYPE'] == 'INPUT_TOKEN_PROCESSED',
                T.c['MODEL_TYPE'] == 'transcription',
                T.c['CACHE_TYPE'] == 'audio',
            ),
        )

        transcription_text = F.sumIf(
            T.c['COST'],
            F.and_(
                T.c['EVENT_TYPE'] == 'INPUT_TOKEN_PROCESSED',
                T.c['MODEL_TYPE'] == 'transcription',
                T.c['CACHE_TYPE'] == '',
            ),
        )

        transcription_output = F.sumIf(
            T.c['COST'],
            F.and_(
                T.c['EVENT_TYPE'] == 'OUTPUT_TOKEN_PROCESSED',
                T.c['MODEL_TYPE'] == 'transcription',
            ),
        )

        return [
            chat_input_direct.label('chat_input_direct'),
            chat_input_cached.label('chat_input_cached'),
            chat_input_judges.label('chat_input_judges'),
            chat_input_judges_cached.label('chat_input_judges_cached'),
            chat_output_direct.label('chat_output_direct'),
            chat_output_judges.label('chat_output_judges'),
            embedding_input_total.label('embedding_input_total'),
            embedding_input_direct.label('embedding_input_direct'),
            embedding_input_semantic_cache.label('embedding_input_semantic_cache'),
            transcription_duration.label('transcription_duration'),
            transcription_audio.label('transcription_audio'),
            transcription_text.label('transcription_text'),
            transcription_output.label('transcription_output'),
        ]

    def _get_attrs_per_metric(self, event_type: str) -> list:
        if event_type == 'FALLBACK':
            return [
                self.T.c['TARGET'].label('target'),
                self.T.c['FALLBACK'].label('fallback'),
            ]
        if event_type == 'GUARDRAIL':
            return [
                self.T.c['GUARDRAIL_NAME'].label('name'),
                self.T.c['GUARDRAIL_TYPE'].label('type'),
                self.T.c['GUARDRAIL_WHERE'].label('where'),
                self.T.c['GUARDRAIL_PARAMS'].label('parameters'),
                self.T.c['GUARDRAIL_BEHAVIOR'].label('behavior'),
            ]
        return []

    def _add_project_filter(self, conditions: list, project_uuid: UUID | None) -> None:
        if project_uuid is not None:
            conditions.append(self.T.c['PROJECT_UUID'] == str(project_uuid))

    def _add_tags_filter(self, conditions: list, tags: list[str] | None) -> None:
        add_tags_filter(conditions, self.T.c['TAGS'], tags=tags)

    def get_all_counters(
        self,
        project_uuid: UUID,
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> Counters:
        T = self.T
        conditions = []
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if _from:
            conditions.append(T.c['TIMESTAMP'] >= _from)
        if _to:
            conditions.append(T.c['TIMESTAMP'] <= _to)
        stmt = select(*self._get_metric_columns()).where(*conditions).select_from(Event)
        with self.db.begin_session() as session:
            res = session.execute(stmt).first()
            if res is None:
                return Counters()
            return Counters.model_validate(res)

    def get_all_counters_by_route(
        self,
        project_uuid: UUID,
        route_name: str,
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> Counters:
        T = self.T
        conditions = [T.c['ROUTE_NAME'] == route_name]
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        columns_to_select = [
            T.c['ROUTE_NAME'].label('route_name'),
            *self._get_metric_columns(),
        ]
        if _from:
            conditions.append(T.c['TIMESTAMP'] >= _from)
        if _to:
            conditions.append(T.c['TIMESTAMP'] <= _to)
        stmt = (
            select(*columns_to_select)
            .group_by(T.c['ROUTE_NAME'])
            .where(*conditions)
            .select_from(Event)
        )

        with self.db.begin_session() as session:
            res = session.execute(stmt).first()
            if res is None:
                return Counters()
            return Counters.model_validate(res)

    def get_last_event(
        self,
        project_uuid: UUID,
        event_type: str,
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> LastEventFallback | LastEventGuardrail | None:
        T = self.T
        base_cols = [
            T.c['ROUTE_NAME'].label('route_name'),
            T.c['TIMESTAMP'].label('timestamp'),
            T.c['API_KEY_UUID'].label('api_key_uuid'),
            T.c['API_KEY_NAME'].label('api_key_name'),
        ]
        conditions = [T.c['EVENT_TYPE'] == event_type]
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if _from:
            conditions.append(T.c['TIMESTAMP'] >= _from)
        if _to:
            conditions.append(T.c['TIMESTAMP'] <= _to)
        extra_attrs = self._get_attrs_per_metric(event_type=event_type)
        stmt = select(*base_cols, *extra_attrs).where(*conditions)
        stmt = stmt.order_by(desc(T.c['TIMESTAMP']))
        with self.db.begin_session() as session:
            res = session.execute(stmt).first()
            if res is None:
                return None
            if event_type == 'FALLBACK':
                return LastEventFallback.model_validate(res)
            return LastEventGuardrail.model_validate(res)

    def get_last_event_route(
        self,
        project_uuid: UUID,
        event_type: str,
        route_name: str,
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> LastEventFallback | LastEventGuardrail | None:
        T = self.T
        base_cols = [
            T.c['ROUTE_NAME'].label('route_name'),
            T.c['TIMESTAMP'].label('timestamp'),
            T.c['API_KEY_UUID'].label('api_key_uuid'),
            T.c['API_KEY_NAME'].label('api_key_name'),
        ]
        conditions = [T.c['EVENT_TYPE'] == event_type, T.c['ROUTE_NAME'] == route_name]
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if _from:
            conditions.append(T.c['TIMESTAMP'] >= _from)
        if _to:
            conditions.append(T.c['TIMESTAMP'] <= _to)
        extra_attrs = self._get_attrs_per_metric(event_type=event_type)
        stmt = (
            select(
                *base_cols,
                *extra_attrs,
            )
            .where(*conditions)
            .order_by(T.c['TIMESTAMP'].desc())
        )
        with self.db.begin_session() as session:
            res = session.execute(stmt).first()
            if res is None:
                return None
            if event_type == 'FALLBACK':
                return LastEventFallback.model_validate(res)
            return LastEventGuardrail.model_validate(res)

    def get_routing_model_counters(
        self,
        project_uuid: UUID,
        _from: datetime | None,
        _to: datetime | None,
        route_name: str | None = None,
        tags: list[str] | None = None,
    ) -> list[ModelInvocationCounter]:
        T = self.T
        conditions = [T.c['EVENT_TYPE'] == 'ROUTING']
        if route_name:
            conditions.append(T.c['ROUTE_NAME'] == route_name)
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if _from:
            conditions.append(T.c['TIMESTAMP'] >= _from)
        if _to:
            conditions.append(T.c['TIMESTAMP'] <= _to)
        stmt = (
            select(
                T.c['ROUTING_SELECTED_MODEL_ID'].label('model_id'),
                F.count().label('value'),
            )
            .where(*conditions)
            .group_by(T.c['ROUTING_SELECTED_MODEL_ID'])
            .select_from(Event)
        )
        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return [
                ModelInvocationCounter.model_validate(
                    dict(zip(['model_id', 'value'], row))
                )
                for row in res
            ]

    def get_tokens_by_model(
        self,
        project_uuid: UUID,
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> list[TokensCounter]:
        FIELD_NAMES = ['event_type', 'route_name', 'model_id', 'value']
        T = self.T
        conditions = [T.c['EVENT_TYPE'].in_(self._token_metric_types)]
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if _from:
            conditions.append(T.c['TIMESTAMP'] >= _from)
        if _to:
            conditions.append(T.c['TIMESTAMP'] <= _to)
        stmt = (
            select(
                T.c['EVENT_TYPE'].label('event_type'),
                T.c['ROUTE_NAME'].label('route_name'),
                self.T.c['MODEL_ID'].label('model_id'),
                F.sum(self.T.c['VALUE']).cast(Float).label('value'),
            )
            .where(*conditions)
            .group_by(T.c['EVENT_TYPE'], T.c['ROUTE_NAME'], self.T.c['MODEL_ID'])
            .select_from(Event)
        )
        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return [
                TokensCounter.model_validate(dict(zip(FIELD_NAMES, row_tuple)))
                for row_tuple in res
            ]

    def get_tokens_by_model_per_route(
        self,
        project_uuid: UUID,
        route_name: str,
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> list[TokensCounter]:
        T = self.T
        FIELD_NAMES = ['event_type', 'route_name', 'model_id', 'value']
        conditions = [
            T.c['EVENT_TYPE'].in_(self._token_metric_types),
            T.c['ROUTE_NAME'] == route_name,
        ]
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if _from:
            conditions.append(T.c['TIMESTAMP'] >= _from)
        if _to:
            conditions.append(T.c['TIMESTAMP'] <= _to)
        stmt = (
            select(
                T.c['EVENT_TYPE'],
                T.c['ROUTE_NAME'],
                self.T.c['MODEL_ID'].label('model_id'),
                F.sum(self.T.c['VALUE']).cast(Float).label('value'),
            )
            .where(*conditions)
            .group_by(T.c['EVENT_TYPE'], T.c['ROUTE_NAME'], self.T.c['MODEL_ID'])
            .select_from(Event)
        )
        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return [
                TokensCounter.model_validate(dict(zip(FIELD_NAMES, row_tuple)))
                for row_tuple in res
            ]

    def get_latest_n_per_event_type(
        self,
        project_uuid: UUID,
        route_name: str,
        n: int,
        _from: datetime | None = None,
        _to: datetime | None = None,
        tags: list[str] | None = None,
    ) -> list[EventDetails] | None:
        T = self.T
        field_names = [
            'timestamp',
            'api_key_uuid',
            'api_key_name',
            'route_name',
            'event_type',
            'target',
            'fallback',
            'name',
            'type',
            'where',
            'parameters',
            'behavior',
        ]
        event_types = [
            'FALLBACK',
            'GUARDRAIL',
            'RATE_LIMIT',
            'TOKEN_INPUT_LIMIT',
            'TOKEN_OUTPUT_LIMIT',
            'CACHE_HIT',
        ]
        row_number_col = (
            F.row_number()
            .over(partition_by=T.c['EVENT_TYPE'], order_by=desc(T.c['TIMESTAMP']))
            .label('row_num')
        )
        inner_cols = [
            T.c['TIMESTAMP'].label('timestamp'),
            T.c['API_KEY_UUID'].label('api_key_uuid'),
            T.c['API_KEY_NAME'].label('api_key_name'),
            T.c['ROUTE_NAME'].label('route_name'),
            T.c['EVENT_TYPE'].label('event_type'),
            self.T.c['TARGET'].label('target'),
            self.T.c['FALLBACK'].label('fallback'),
            self.T.c['GUARDRAIL_NAME'].label('name'),
            self.T.c['GUARDRAIL_TYPE'].label('type'),
            self.T.c['GUARDRAIL_WHERE'].label('where'),
            self.T.c['GUARDRAIL_PARAMS'].label('parameters'),
            self.T.c['GUARDRAIL_BEHAVIOR'].label('behavior'),
            row_number_col,
        ]

        conditions = [
            T.c['EVENT_TYPE'].in_(event_types),
            T.c['ROUTE_NAME'] == route_name,
        ]
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if _from:
            conditions.append(T.c['TIMESTAMP'] >= _from)
        if _to:
            conditions.append(T.c['TIMESTAMP'] <= _to)

        subquery_stmt = (select(*inner_cols).where(and_(*conditions))).subquery()

        final_cols = [
            subquery_stmt.c['timestamp'],
            subquery_stmt.c['api_key_uuid'],
            subquery_stmt.c['api_key_name'],
            subquery_stmt.c['route_name'],
            subquery_stmt.c['event_type'],
            subquery_stmt.c['target'],
            subquery_stmt.c['fallback'],
            subquery_stmt.c['name'],
            subquery_stmt.c['type'],
            subquery_stmt.c['where'],
            subquery_stmt.c['parameters'],
            subquery_stmt.c['behavior'],
        ]

        final_stmt = (
            select(*final_cols)
            .where(subquery_stmt.c.row_num <= n)
            .order_by(subquery_stmt.c.event_type.asc(), desc(subquery_stmt.c.timestamp))
        )
        with self.db.begin_session() as session:
            res = session.execute(final_stmt).all()
            if res is None:
                return None
            return [
                EventDetails.model_validate(dict(zip(field_names, row_tuple)))
                for row_tuple in res
            ]

    def get_costs_chart_data(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        granularity: Literal['hours', 'days', 'weeks', 'months'],
        group_by: Literal['keys', 'groups', 'models'],
        timezone_offset_seconds: int = 0,
        tags: list[str] | None = None,
    ) -> list[CostChartDataPoint]:
        T = self.T

        bucket_expr = with_timezone_offset(
            get_bucket_function(granularity),
            timezone_offset_seconds,
            self.T.c['TIMESTAMP'],
        )

        group_by_column = (
            F.cast(T.c['API_KEY_UUID'], String)
            if group_by == 'keys'
            else F.cast(T.c['GROUP_UUID'], String)
            if group_by == 'groups'
            else self.T.c['MODEL_ID'].label('model_id')
        )

        FIELD_NAMES = ['bucket', 'group_by_value', 'total_cost']
        conditions = [
            T.c['EVENT_TYPE'].in_(['INPUT_TOKEN_PROCESSED', 'OUTPUT_TOKEN_PROCESSED']),
        ]
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if route_names is not None:
            conditions.append(T.c['ROUTE_NAME'].in_(route_names))
        if _from is not None:
            conditions.append(T.c['TIMESTAMP'] >= _from)
        if _to is not None:
            conditions.append(T.c['TIMESTAMP'] <= _to)
        stmt = (
            select(
                bucket_expr.label('bucket'),
                group_by_column.label('group_by_value'),
                F.sum(T.c['COST']).label('total_cost'),
            )
            .select_from(Event)
            .where(*conditions)
            .group_by(text('bucket'), group_by_column)
            .order_by(text('bucket'), text('group_by_value'))
        )

        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return [
                CostChartDataPoint.model_validate(dict(zip(FIELD_NAMES, row_tuple)))
                for row_tuple in res
            ]

    def get_costs_chart_data_by_route(
        self,
        project_uuid: UUID,
        entity_column: Literal['API_KEY_UUID', 'GROUP_UUID', 'MODEL_ID'],
        entity_value: str,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        granularity: Literal['hours', 'days', 'weeks', 'months'],
        timezone_offset_seconds: int = 0,
        tags: list[str] | None = None,
    ) -> list[CostChartDataPoint]:
        T = self.T
        bucket_expr = with_timezone_offset(
            get_bucket_function(granularity), timezone_offset_seconds, T.c['TIMESTAMP']
        )
        FIELD_NAMES = ['bucket', 'group_by_value', 'total_cost']
        conditions = [
            T.c['EVENT_TYPE'].in_(['INPUT_TOKEN_PROCESSED', 'OUTPUT_TOKEN_PROCESSED']),
        ]
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if route_names is not None:
            conditions.append(T.c['ROUTE_NAME'].in_(route_names))
        if entity_column in ('API_KEY_UUID', 'GROUP_UUID'):
            conditions.append(F.cast(T.c[entity_column], String) == entity_value)
        else:
            conditions.append(T.c[entity_column] == entity_value)
        if _from is not None:
            conditions.append(T.c['TIMESTAMP'] >= _from)
        if _to is not None:
            conditions.append(T.c['TIMESTAMP'] <= _to)
        route_col = T.c['ROUTE_NAME']
        stmt = (
            select(
                bucket_expr.label('bucket'),
                route_col.label('group_by_value'),
                F.sum(T.c['COST']).label('total_cost'),
            )
            .select_from(Event)
            .where(*conditions)
            .group_by(text('bucket'), route_col)
            .order_by(text('bucket'), text('group_by_value'))
        )
        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return [
                CostChartDataPoint.model_validate(dict(zip(FIELD_NAMES, row_tuple)))
                for row_tuple in res
            ]

    def get_cost_breakdown_by_entity(
        self,
        project_uuid: UUID,
        entity_column: Literal['API_KEY_UUID', 'GROUP_UUID', 'MODEL_ID'],
        entity_value: str,
        _from: datetime,
        _to: datetime,
        route_names: list[str] | None,
        tags: list[str] | None = None,
    ) -> list[RouteCostBreakdown]:
        T = self.T
        FIELD_NAMES = ['route_name', 'total_cost']
        conditions = [
            T.c['EVENT_TYPE'].in_(['INPUT_TOKEN_PROCESSED', 'OUTPUT_TOKEN_PROCESSED']),
            T.c['TIMESTAMP'] >= _from,
            T.c['TIMESTAMP'] <= _to,
        ]
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if entity_column in ('API_KEY_UUID', 'GROUP_UUID'):
            conditions.append(F.cast(T.c[entity_column], String) == entity_value)
        else:
            conditions.append(T.c[entity_column] == entity_value)
        if route_names is not None:
            conditions.append(T.c['ROUTE_NAME'].in_(route_names))
        route_col = T.c['ROUTE_NAME']
        stmt = (
            select(
                route_col.label('route_name'),
                F.sum(T.c['COST']).label('total_cost'),
            )
            .select_from(Event)
            .where(*conditions)
            .group_by(route_col)
            .order_by(route_col)
        )
        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return [
                RouteCostBreakdown.model_validate(dict(zip(FIELD_NAMES, row_tuple)))
                for row_tuple in res
            ]

    def get_invocation_chart_data(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        granularity: Literal['hours', 'days', 'weeks', 'months'],
        include_models: bool,
        timezone_offset_seconds: int = 0,
        tags: list[str] | None = None,
    ) -> list[InvocationChartDataPoint]:
        T = self.T
        FIELD_NAMES = ['bucket', 'group_by_value', 'value']

        bucket_expr = with_timezone_offset(
            get_bucket_function(granularity),
            timezone_offset_seconds,
            self.T.c['TIMESTAMP'],
        )

        conditions = [T.c['EVENT_TYPE'] == 'MODEL_INVOCATION']
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if route_names is not None:
            conditions.append(T.c['ROUTE_NAME'].in_(route_names))
        if _from is not None:
            conditions.append(T.c['TIMESTAMP'] >= _from)
        if _to is not None:
            conditions.append(T.c['TIMESTAMP'] <= _to)

        if include_models:
            group_by_column = T.c['MODEL_ID'].label('model_id')
            stmt = (
                select(
                    bucket_expr.label('bucket'),
                    group_by_column.label('group_by_value'),
                    F.sum(T.c['VALUE']).label('value'),
                )
                .select_from(Event)
                .where(*conditions)
                .group_by(text('bucket'), group_by_column)
                .order_by(text('bucket'), text('group_by_value'))
            )
        else:
            stmt = (
                select(
                    bucket_expr.label('bucket'),
                    literal('all').label('group_by_value'),
                    F.sum(T.c['VALUE']).label('value'),
                )
                .select_from(Event)
                .where(*conditions)
                .group_by(text('bucket'))
                .order_by(text('bucket'))
            )

        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return [
                InvocationChartDataPoint.model_validate(
                    dict(zip(FIELD_NAMES, row_tuple))
                )
                for row_tuple in res
            ]

    def get_summary_costs(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        cache_enabled: bool,
        _with_saved_tokens: bool,
        tags: list[str] | None = None,
    ) -> CostData:
        T = self.T
        conditions = [
            T.c['EVENT_TYPE'].in_([*self._token_metric_types, 'CACHE_HIT']),
            F.or_(
                self.T.c['CACHE_TYPE'] == '',
                self.T.c['CACHE_TYPE'] == 'exact',
            ),
        ]
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if route_names is not None:
            conditions.append(T.c['ROUTE_NAME'].in_(route_names))
        if _from is not None:
            conditions.append(
                T.c['TIMESTAMP'] >= _from,
            )
        if _to is not None:
            conditions.append(
                T.c['TIMESTAMP'] <= _to,
            )
        columns = [
            F.sumIf(T.c['COST'], T.c['EVENT_TYPE'] == 'INPUT_TOKEN_PROCESSED').label(
                'input_cost'
            ),
            F.sumIf(T.c['COST'], T.c['EVENT_TYPE'] == 'OUTPUT_TOKEN_PROCESSED').label(
                'output_cost'
            ),
            F.sumIf(
                T.c['COST'],
                T.c['EVENT_TYPE'].in_(
                    ['INPUT_TOKEN_PROCESSED', 'OUTPUT_TOKEN_PROCESSED']
                ),
            ).label('total_cost'),
        ]
        if cache_enabled:
            columns.extend(
                [
                    F.countIf(T.c['EVENT_TYPE'] == 'CACHE_HIT').label(
                        'cache_triggered'
                    ),
                    F.sumIf(
                        T.c['COST'], T.c['EVENT_TYPE'] == 'CACHE_INPUT_TOKENS'
                    ).label('saved_amount_input'),
                    F.sumIf(
                        T.c['COST'], T.c['EVENT_TYPE'] == 'CACHE_OUTPUT_TOKENS'
                    ).label('saved_amount_output'),
                    F.sumIf(
                        T.c['COST'],
                        T.c['EVENT_TYPE'].in_(
                            ['CACHE_INPUT_TOKENS', 'CACHE_OUTPUT_TOKENS']
                        ),
                    ).label('total_saved_amount'),
                ]
            )
            if _with_saved_tokens:
                columns.extend(
                    [
                        F.sumIf(
                            T.c['VALUE'], T.c['EVENT_TYPE'] == 'CACHE_INPUT_TOKENS'
                        ).label('cache_saved_tokens_input'),
                        F.sumIf(
                            T.c['VALUE'], T.c['EVENT_TYPE'] == 'CACHE_OUTPUT_TOKENS'
                        ).label('cache_saved_tokens_output'),
                        F.sumIf(
                            T.c['VALUE'],
                            T.c['EVENT_TYPE'].in_(
                                ['CACHE_INPUT_TOKENS', 'CACHE_OUTPUT_TOKENS']
                            ),
                        ).label('total_cached_tokens'),
                    ]
                )
        stmt = select(*columns).where(*conditions).select_from(Event)
        with self.db.begin_session() as session:
            res = session.execute(stmt).first()
            return CostData.model_validate(res)

    def get_token_chart_data(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        granularity: Literal['hours', 'days', 'weeks', 'months'],
        timezone_offset_seconds: int = 0,
        tags: list[str] | None = None,
    ) -> list[TokenChartDataPoint]:
        T = self.T
        FIELD_NAMES = ['bucket', 'event_type', 'total_tokens']

        bucket_expr = with_timezone_offset(
            get_bucket_function(granularity),
            timezone_offset_seconds,
            self.T.c['TIMESTAMP'],
        )

        conditions = [
            T.c['EVENT_TYPE'].in_(['INPUT_TOKEN_PROCESSED', 'OUTPUT_TOKEN_PROCESSED']),
        ]
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if route_names is not None:
            conditions.append(T.c['ROUTE_NAME'].in_(route_names))
        if _from is not None:
            conditions.append(T.c['TIMESTAMP'] >= _from)
        if _to is not None:
            conditions.append(T.c['TIMESTAMP'] <= _to)

        stmt = (
            select(
                bucket_expr.label('bucket'),
                T.c['EVENT_TYPE'].label('event_type'),
                F.sum(T.c['VALUE']).label('total_tokens'),
            )
            .select_from(Event)
            .where(*conditions)
            .group_by(text('bucket'), T.c['EVENT_TYPE'])
            .order_by(text('bucket'), T.c['EVENT_TYPE'])
        )

        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return [
                TokenChartDataPoint.model_validate(dict(zip(FIELD_NAMES, row_tuple)))
                for row_tuple in res
            ]

    def get_semantic_cache_details(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        _with_saved_tokens: bool,
        tags: list[str] | None = None,
    ) -> SemanticCacheCostData:
        T = self.T
        cache_triggered = F.countIf(T.c['EVENT_TYPE'] == 'CACHE_HIT')
        llm_input_request_savings = F.sumIf(
            T.c['COST'],
            T.c['EVENT_TYPE'] == 'CACHE_INPUT_TOKENS',
        )
        llm_output_request_savings = F.sumIf(
            T.c['COST'],
            T.c['EVENT_TYPE'] == 'CACHE_OUTPUT_TOKENS',
        )
        llm_total_request_savings = F.sumIf(
            T.c['COST'],
            T.c['EVENT_TYPE'].in_(['CACHE_INPUT_TOKENS', 'CACHE_OUTPUT_TOKENS']),
        )
        embedding_inference_cost = F.sumIf(
            T.c['COST'], T.c['EVENT_TYPE'] == 'INPUT_TOKEN_PROCESSED'
        )
        columns = [
            cache_triggered.label('cache_triggered'),
            llm_input_request_savings.label('llm_input_request_savings'),
            llm_output_request_savings.label('llm_output_request_savings'),
            llm_total_request_savings.label('llm_total_request_savings'),
            embedding_inference_cost.label('embedding_inference_cost'),
            (llm_total_request_savings - embedding_inference_cost).label('net_savings'),
        ]
        if _with_saved_tokens:
            columns.extend(
                [
                    F.sumIf(
                        T.c['VALUE'], T.c['EVENT_TYPE'] == 'CACHE_INPUT_TOKENS'
                    ).label('cache_saved_tokens_input'),
                    F.sumIf(
                        T.c['VALUE'], T.c['EVENT_TYPE'] == 'CACHE_OUTPUT_TOKENS'
                    ).label('cache_saved_tokens_output'),
                    F.sumIf(
                        T.c['VALUE'],
                        T.c['EVENT_TYPE'].in_(
                            ['CACHE_INPUT_TOKENS', 'CACHE_OUTPUT_TOKENS']
                        ),
                    ).label('total_cached_tokens'),
                ]
            )
        conditions = [
            self.T.c['CACHE_TYPE'] == 'semantic',
        ]
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if route_names is not None:
            conditions.append(T.c['ROUTE_NAME'].in_(route_names))
        if _from is not None:
            conditions.append(
                T.c['TIMESTAMP'] >= _from,
            )
        if _to is not None:
            conditions.append(
                T.c['TIMESTAMP'] <= _to,
            )
        stmt = select(*columns).where(*conditions)
        with self.db.begin_session() as session:
            res = session.execute(stmt).first()
            return SemanticCacheCostData.model_validate(res)

    def get_detailed_cost_breakdown(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> DetailedCostBreakdown:
        T = self.T
        conditions = []
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if route_names is not None:
            conditions.append(T.c['ROUTE_NAME'].in_(route_names))
        if _from is not None:
            conditions.append(T.c['TIMESTAMP'] >= _from)
        if _to is not None:
            conditions.append(T.c['TIMESTAMP'] <= _to)

        stmt = (
            select(*self._get_detailed_cost_breakdown_columns())
            .where(*conditions)
            .select_from(Event)
        )
        with self.db.begin_session() as session:
            res = session.execute(stmt).first()
            return DetailedCostBreakdown.model_validate(res)

    def get_all_routes_detailed_cost_breakdown(
        self,
        project_uuid: UUID,
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> list[RouteDetailedCostBreakdown]:
        T = self.T
        conditions = []
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if _from is not None:
            conditions.append(T.c['TIMESTAMP'] >= _from)
        if _to is not None:
            conditions.append(T.c['TIMESTAMP'] <= _to)

        columns = [
            T.c['ROUTE_NAME'].label('route_name'),
            *self._get_detailed_cost_breakdown_columns(),
        ]

        stmt = (
            select(*columns)
            .where(*conditions)
            .group_by(T.c['ROUTE_NAME'])
            .select_from(Event)
        )

        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            field_names = [
                'route_name',
                'chat_input_direct',
                'chat_input_cached',
                'chat_input_judges',
                'chat_input_judges_cached',
                'chat_output_direct',
                'chat_output_judges',
                'embedding_input_total',
                'embedding_input_direct',
                'embedding_input_semantic_cache',
                'transcription_duration',
                'transcription_audio',
                'transcription_text',
                'transcription_output',
            ]
            return [
                RouteDetailedCostBreakdown.model_validate(dict(zip(field_names, row)))
                for row in res
            ]

    def get_all_routes_summary_costs(
        self,
        project_uuid: UUID,
        _from: datetime | None,
        _to: datetime | None,
        _with_saved_tokens: bool,
        tags: list[str] | None = None,
    ) -> list[RouteCostData]:
        T = self.T
        route_name = T.c['ROUTE_NAME']
        input_cost = F.sumIf(T.c['COST'], T.c['EVENT_TYPE'] == 'INPUT_TOKEN_PROCESSED')
        output_cost = F.sumIf(
            T.c['COST'], T.c['EVENT_TYPE'] == 'OUTPUT_TOKEN_PROCESSED'
        )
        total_cost = F.sumIf(
            T.c['COST'],
            T.c['EVENT_TYPE'].in_(['INPUT_TOKEN_PROCESSED', 'OUTPUT_TOKEN_PROCESSED']),
        )
        cache_triggered = F.countIf(T.c['EVENT_TYPE'] == 'CACHE_HIT')
        partial_saved_amount_input = F.sumIf(
            T.c['COST'],
            F.and_(
                T.c['EVENT_TYPE'] == 'CACHE_INPUT_TOKENS',
                F.or_(
                    T.c['CACHE_TYPE'] == '',
                    T.c['CACHE_TYPE'] == 'exact',
                ),
            ),
        )
        partial_saved_amount_output = F.sumIf(
            T.c['COST'],
            F.and_(
                T.c['EVENT_TYPE'] == 'CACHE_OUTPUT_TOKENS',
                F.or_(
                    T.c['CACHE_TYPE'] == '',
                    T.c['CACHE_TYPE'] == 'exact',
                ),
            ),
        )
        partial_saved_amount = F.sumIf(
            T.c['COST'],
            F.and_(
                T.c['EVENT_TYPE'].in_(['CACHE_INPUT_TOKENS', 'CACHE_OUTPUT_TOKENS']),
                F.or_(
                    T.c['CACHE_TYPE'] == '',
                    T.c['CACHE_TYPE'] == 'exact',
                ),
            ),
        )
        # semantic
        llm_input_request_savings = F.sumIf(
            T.c['COST'],
            and_(
                T.c['EVENT_TYPE'] == 'CACHE_INPUT_TOKENS',
                T.c['CACHE_TYPE'] == 'semantic',
                T.c['CACHE_TYPE'] == 'semantic',
            ),
        )
        llm_output_request_savings = F.sumIf(
            T.c['COST'],
            and_(
                T.c['EVENT_TYPE'] == 'CACHE_OUTPUT_TOKENS',
                T.c['CACHE_TYPE'] == 'semantic',
            ),
        )
        llm_total_request_savings = F.sumIf(
            T.c['COST'],
            and_(
                T.c['EVENT_TYPE'].in_(['CACHE_INPUT_TOKENS', 'CACHE_OUTPUT_TOKENS']),
                T.c['CACHE_TYPE'] == 'semantic',
            ),
        )
        embedding_inference_cost = F.sumIf(
            T.c['COST'],
            and_(
                T.c['EVENT_TYPE'] == 'INPUT_TOKEN_PROCESSED',
                T.c['CACHE_TYPE'] == 'semantic',
            ),
        )
        columns = [
            route_name.label('route_name'),
            input_cost.label('input_cost'),
            output_cost.label('output_cost'),
            total_cost.label('total_cost'),
            cache_triggered.label('cache_triggered'),
            partial_saved_amount_input.label('partial_saved_amount_input'),
            partial_saved_amount_output.label('partial_saved_amount_output'),
            partial_saved_amount.label('partial_saved_amount'),
            llm_input_request_savings.label('llm_input_request_savings'),
            llm_output_request_savings.label('llm_output_request_savings'),
            llm_total_request_savings.label('llm_total_request_savings'),
            embedding_inference_cost.label('embedding_inference_cost'),
            (partial_saved_amount_input + llm_input_request_savings).label(
                'saved_amount_input'
            ),
            (partial_saved_amount_output + llm_output_request_savings).label(
                'saved_amount_output'
            ),
            (
                partial_saved_amount
                + (llm_total_request_savings - embedding_inference_cost)
            ).label('total_saved_amount'),
        ]
        if _with_saved_tokens:
            columns.extend(
                [
                    F.sumIf(
                        T.c['VALUE'], T.c['EVENT_TYPE'] == 'CACHE_INPUT_TOKENS'
                    ).label('cache_saved_tokens_input'),
                    F.sumIf(
                        T.c['VALUE'], T.c['EVENT_TYPE'] == 'CACHE_OUTPUT_TOKENS'
                    ).label('cache_saved_tokens_output'),
                    F.sumIf(
                        T.c['VALUE'],
                        T.c['EVENT_TYPE'].in_(
                            ['CACHE_INPUT_TOKENS', 'CACHE_OUTPUT_TOKENS']
                        ),
                    ).label('total_cached_tokens'),
                ]
            )
        conditions = [T.c['EVENT_TYPE'].in_([*self._token_metric_types, 'CACHE_HIT'])]
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if _from is not None:
            conditions.append(T.c['TIMESTAMP'] >= _from)
        if _to is not None:
            conditions.append(T.c['TIMESTAMP'] <= _to)
        stmt = (
            select(*columns)
            .where(*conditions)
            .group_by(T.c['ROUTE_NAME'])
            .select_from(Event)
        )
        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            field_names = [
                'route_name',
                'input_cost',
                'output_cost',
                'total_cost',
                'cache_triggered',
                'partial_saved_amount_input',
                'partial_saved_amount_output',
                'partial_saved_amount',
                'llm_input_request_savings',
                'llm_output_request_savings',
                'llm_total_request_savings',
                'embedding_inference_cost',
                'saved_amount_input',
                'saved_amount_output',
                'total_saved_amount',
            ]
            if _with_saved_tokens:
                field_names.extend(
                    [
                        'cache_saved_tokens_input',
                        'cache_saved_tokens_output',
                        'total_cached_tokens',
                    ]
                )
            return [
                RouteCostData.model_validate(dict(zip(field_names, row))) for row in res
            ]

    def get_most_expensive_route(
        self,
        project_uuid: UUID,
        configured_routes: list[str],
        _from: datetime | None = None,
        _to: datetime | None = None,
        tags: list[str] | None = None,
    ) -> MostExpensiveRoute | None:
        if not configured_routes:
            return None
        T = self.T
        FIELD_NAMES = ['route_name', 'total_cost']
        conditions = [
            T.c['EVENT_TYPE'].in_(['INPUT_TOKEN_PROCESSED', 'OUTPUT_TOKEN_PROCESSED']),
            T.c['ROUTE_NAME'].in_(configured_routes),
        ]
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if _from is not None:
            conditions.append(self.T.c['TIMESTAMP'] >= _from)
        if _to is not None:
            conditions.append(self.T.c['TIMESTAMP'] <= _to)

        route_stmt = (
            select(
                self.T.c['ROUTE_NAME'].label('route_name'),
                F.sum(Event.cost).label('total_cost'),
            )
            .select_from(Event)
            .where(*conditions)
            .group_by(self.T.c['ROUTE_NAME'])
            .order_by(text('total_cost DESC'))
            .limit(1)
        )

        with self.db.begin_session() as session:
            res = session.execute(route_stmt).first()
            if res is None:
                return None
            return MostExpensiveRoute.model_validate(dict(zip(FIELD_NAMES, res)))

    def get_cost_chart_data(
        self,
        project_uuid: UUID,
        route_name: str,
        _from: datetime | None,
        _to: datetime | None,
        granularity: Literal['hours', 'days', 'weeks', 'months'],
        timezone_offset_seconds: int = 0,
        tags: list[str] | None = None,
    ) -> list[MostExpensiveChartData]:
        T = self.T
        FIELD_NAMES = ['bucket', 'cost']

        bucket_expr = with_timezone_offset(
            get_bucket_function(granularity),
            timezone_offset_seconds,
            self.T.c['TIMESTAMP'],
        )

        conditions = [
            T.c['ROUTE_NAME'] == route_name,
            T.c['EVENT_TYPE'].in_(['INPUT_TOKEN_PROCESSED', 'OUTPUT_TOKEN_PROCESSED']),
        ]
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if _from is not None:
            conditions.append(T.c['TIMESTAMP'] >= _from)
        if _to is not None:
            conditions.append(T.c['TIMESTAMP'] <= _to)

        stmt = (
            select(
                bucket_expr.label('bucket'),
                F.sum(T.c['COST']).label('cost'),
            )
            .select_from(Event)
            .where(*conditions)
            .group_by(text('bucket'))
            .order_by(text('bucket'))
        )

        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return [
                MostExpensiveChartData.model_validate(dict(zip(FIELD_NAMES, row_tuple)))
                for row_tuple in res
            ]
