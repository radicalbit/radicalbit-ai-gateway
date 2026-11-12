from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi_pagination import Page, Params
from fastapi_pagination.ext.sqlalchemy import paginate
from sqlalchemy import Float, Row, String, and_, desc, func as F, literal, select, text
from sqlalchemy.sql import ColumnElement

from radicalbit_ai_gateway.db.clickhouse_database import ClickHouseDatabase
from radicalbit_ai_gateway.db.dao.tags_filter import add_tags_filter
from radicalbit_ai_gateway.db.models.event import (
    CostChartDataPoint,
    CostData,
    Counters,
    DetailedCostBreakdown,
    EventDetails,
    EventsSummary,
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
from radicalbit_ai_gateway.models.event_type import (
    LIMIT_BLOCK_EVENT_TYPES,
    PROCESSED_TOKEN_EVENT_TYPES,
    EventType,
)
from radicalbit_ai_gateway.utils.chart_utils import (
    get_bucket_function,
    with_timezone_offset,
)

McpEntityColumn = Literal['MCP_ALIAS', 'GROUP_UUID', 'API_KEY_UUID']
# A column a chart series can be keyed by. The target is the tool, prompt or
# resource an invocation addressed inside one server.
McpSeriesColumn = Literal['MCP_ALIAS', 'GROUP_UUID', 'API_KEY_UUID', 'MCP_TARGET']

# The event column each MCP chart grouping reads its entity from.
MCP_ENTITY_COLUMNS: dict[str, McpEntityColumn] = {
    'services': 'MCP_ALIAS',
    'groups': 'GROUP_UUID',
    'keys': 'API_KEY_UUID',
}


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
            self._count_metric('AUDIO_DURATION_LIMIT').label(
                'duration_limit_triggered'
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

        # Exact cache hits on decision requests are recorded at $0, so direct
        # input is the whole decision cost.
        decision_input = F.sumIf(
            T.c['COST'],
            F.and_(
                T.c['EVENT_TYPE'] == 'INPUT_TOKEN_PROCESSED',
                T.c['MODEL_TYPE'] == 'decision_model',
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
            decision_input.label('decision_input'),
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

    def _mcp_invocation_conditions(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None,
    ) -> list:
        """Build the predicate both MCP usage reads share.

        The chart and the ranked table start from the same rows, so a filter
        can never narrow one of them and not the other.
        """
        conditions = [self.T.c['EVENT_TYPE'] == 'MCP_INVOCATION']
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if route_names is not None:
            conditions.append(self.T.c['ROUTE_NAME'].in_(route_names))
        if _from is not None:
            conditions.append(self.T.c['TIMESTAMP'] >= _from)
        if _to is not None:
            conditions.append(self.T.c['TIMESTAMP'] <= _to)
        return conditions

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

    def _route_conditions(
        self,
        project_uuid: UUID,
        route_names: list[str],
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None,
    ) -> list:
        """Build the predicate the per-route metric reads share."""
        T = self.T
        conditions = [T.c['ROUTE_NAME'].in_(route_names)]
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if _from:
            conditions.append(T.c['TIMESTAMP'] >= _from)
        if _to:
            conditions.append(T.c['TIMESTAMP'] <= _to)
        return conditions

    def get_counters_of_routes(
        self,
        project_uuid: UUID,
        route_names: list[str],
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> dict[str, Counters]:
        """Count the events of each route, in one query for all of them.

        A route with no event is absent from the result.
        """
        if not route_names:
            return {}
        T = self.T
        stmt = (
            select(T.c['ROUTE_NAME'].label('route_name'), *self._get_metric_columns())
            .where(*self._route_conditions(project_uuid, route_names, _from, _to, tags))
            .group_by(T.c['ROUTE_NAME'])
            .select_from(Event)
        )
        with self.db.begin_session() as session:
            rows = session.execute(stmt).all()
        return {row.route_name: Counters.model_validate(row) for row in rows}

    def get_all_counters_by_route(
        self,
        project_uuid: UUID,
        route_name: str,
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> Counters:
        counters = self.get_counters_of_routes(
            project_uuid, [route_name], _from, _to, tags=tags
        )
        return counters.get(route_name, Counters())

    _LAST_EVENT_FIELDS = (
        'route_name',
        'timestamp',
        'api_key_uuid',
        'api_key_name',
        'target',
        'fallback',
        'name',
        'type',
        'where',
        'parameters',
        'behavior',
    )

    def _latest_event(self) -> ColumnElement:
        """Aggregate a group of events down to its latest one.

        argMax keeps one row per group in a single pass; ordering the events
        by TIMESTAMP to take the first would sort every one of them.
        """
        T = self.T
        return F.argMax(
            F.tuple(
                T.c['ROUTE_NAME'],
                T.c['TIMESTAMP'],
                T.c['API_KEY_UUID'],
                T.c['API_KEY_NAME'],
                T.c['TARGET'],
                T.c['FALLBACK'],
                T.c['GUARDRAIL_NAME'],
                T.c['GUARDRAIL_TYPE'],
                T.c['GUARDRAIL_WHERE'],
                T.c['GUARDRAIL_PARAMS'],
                T.c['GUARDRAIL_BEHAVIOR'],
            ),
            T.c['TIMESTAMP'],
        )

    def _last_event(
        self, event_type: str, values: tuple
    ) -> LastEventFallback | LastEventGuardrail:
        model = LastEventFallback if event_type == 'FALLBACK' else LastEventGuardrail
        return model.model_validate(dict(zip(self._LAST_EVENT_FIELDS, values)))

    def get_last_events(
        self,
        project_uuid: UUID,
        event_types: list[str],
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> dict[str, LastEventFallback | LastEventGuardrail]:
        """Return the project's latest event of each type, in one query.

        Keyed by event type; a type with no event is absent.
        """
        if not event_types:
            return {}
        T = self.T
        conditions = [T.c['EVENT_TYPE'].in_(event_types)]
        self._add_project_filter(conditions, project_uuid)
        self._add_tags_filter(conditions, tags=tags)
        if _from:
            conditions.append(T.c['TIMESTAMP'] >= _from)
        if _to:
            conditions.append(T.c['TIMESTAMP'] <= _to)
        stmt = (
            select(T.c['EVENT_TYPE'], self._latest_event())
            .where(*conditions)
            .group_by(T.c['EVENT_TYPE'])
            .select_from(Event)
        )
        with self.db.begin_session() as session:
            rows = session.execute(stmt).all()
        return {
            event_type: self._last_event(event_type, values)
            for event_type, values in rows
        }

    def get_last_event(
        self,
        project_uuid: UUID,
        event_type: str,
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> LastEventFallback | LastEventGuardrail | None:
        last_events = self.get_last_events(
            project_uuid, [event_type], _from, _to, tags=tags
        )
        return last_events.get(event_type)

    def get_last_events_of_routes(
        self,
        project_uuid: UUID,
        event_types: list[str],
        route_names: list[str],
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> dict[tuple[str, str], LastEventFallback | LastEventGuardrail]:
        """Return the latest event of each type on each route, in one query.

        Keyed by `(route_name, event_type)`; a pair with no event is absent.
        """
        if not route_names or not event_types:
            return {}
        T = self.T
        conditions = self._route_conditions(project_uuid, route_names, _from, _to, tags)
        stmt = (
            select(T.c['ROUTE_NAME'], T.c['EVENT_TYPE'], self._latest_event())
            .where(T.c['EVENT_TYPE'].in_(event_types), *conditions)
            .group_by(T.c['ROUTE_NAME'], T.c['EVENT_TYPE'])
            .select_from(Event)
        )
        with self.db.begin_session() as session:
            rows = session.execute(stmt).all()
        return {
            (route_name, event_type): self._last_event(event_type, values)
            for route_name, event_type, values in rows
        }

    def get_last_event_route(
        self,
        project_uuid: UUID,
        event_type: str,
        route_name: str,
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> LastEventFallback | LastEventGuardrail | None:
        last_events = self.get_last_events_of_routes(
            project_uuid, [event_type], [route_name], _from, _to, tags=tags
        )
        return last_events.get((route_name, event_type))

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

    def get_tokens_by_model_of_routes(
        self,
        project_uuid: UUID,
        route_names: list[str],
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> list[TokensCounter]:
        """Sum the tokens of each model on each route, in one query."""
        if not route_names:
            return []
        T = self.T
        FIELD_NAMES = ['event_type', 'route_name', 'model_id', 'value']
        conditions = self._route_conditions(project_uuid, route_names, _from, _to, tags)
        stmt = (
            select(
                T.c['EVENT_TYPE'],
                T.c['ROUTE_NAME'],
                self.T.c['MODEL_ID'].label('model_id'),
                F.sum(self.T.c['VALUE']).cast(Float).label('value'),
            )
            .where(T.c['EVENT_TYPE'].in_(self._token_metric_types), *conditions)
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
        return self.get_tokens_by_model_of_routes(
            project_uuid, [route_name], _from, _to, tags=tags
        )

    def get_routing_model_counters_of_routes(
        self,
        project_uuid: UUID,
        route_names: list[str],
        _from: datetime | None,
        _to: datetime | None,
        tags: list[str] | None = None,
    ) -> dict[str, list[ModelInvocationCounter]]:
        """Count the models routing chose on each route, in one query.

        A route where routing never ran is absent from the result.
        """
        if not route_names:
            return {}
        T = self.T
        conditions = self._route_conditions(project_uuid, route_names, _from, _to, tags)
        stmt = (
            select(
                T.c['ROUTE_NAME'],
                T.c['ROUTING_SELECTED_MODEL_ID'],
                F.count(),
            )
            .where(T.c['EVENT_TYPE'] == 'ROUTING', *conditions)
            .group_by(T.c['ROUTE_NAME'], T.c['ROUTING_SELECTED_MODEL_ID'])
            .select_from(Event)
        )
        counters: dict[str, list[ModelInvocationCounter]] = {}
        with self.db.begin_session() as session:
            rows = session.execute(stmt).all()
        for route_name, model_id, value in rows:
            counters.setdefault(route_name, []).append(
                ModelInvocationCounter(model_id=model_id, value=value)
            )
        return counters

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
            'AUDIO_DURATION_LIMIT',
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

    @staticmethod
    def _distinct(condition: ColumnElement, *values: ColumnElement) -> ColumnElement:
        """Collect the distinct `values` tuples of the events matching `condition`."""
        return F.groupUniqArrayIf(F.tuple(*values), condition)

    def _attribute(self, key: str) -> ColumnElement:
        """Read one ATTRIBUTES entry, '' when the event has no such key."""
        return F.arrayElement(self.ATTRIBUTES, key)

    def get_request_summaries(
        self,
        project_uuid: UUID,
        request_uuids: list[str],
        date_from: date,
        date_to: date,
    ) -> dict[str, EventsSummary]:
        """Aggregate the events of a page of requests, one row per request.

        One query for the whole page, bounded to `[date_from, date_to]` on
        DATE so ClickHouse prunes partitions. Requests with no event are
        absent from the result.
        """
        if not request_uuids:
            return {}

        T = self.T
        processed_tokens = T.c['EVENT_TYPE'].in_(PROCESSED_TOKEN_EVENT_TYPES)
        conditions = [
            T.c['REQUEST_UUID'].in_(request_uuids),
            T.c['DATE'] >= date_from,
            T.c['DATE'] <= date_to,
        ]
        self._add_project_filter(conditions, project_uuid)
        columns = [
            F.sumIf(T.c['VALUE'], processed_tokens).label('total_tokens'),
            F.sumIf(T.c['COST'], processed_tokens).label('cost'),
            self._distinct(
                T.c['EVENT_TYPE'] == 'GUARDRAIL',
                T.c['GUARDRAIL_NAME'],
                T.c['GUARDRAIL_BEHAVIOR'],
                T.c['GUARDRAIL_WHERE'],
            ).label('guardrails'),
            self._distinct(T.c['EVENT_TYPE'] == 'CACHE_HIT', T.c['CACHE_TYPE']).label(
                'cache_hits'
            ),
            self._distinct(
                T.c['EVENT_TYPE'] == 'FALLBACK', T.c['TARGET'], T.c['FALLBACK']
            ).label('fallbacks'),
            self._distinct(
                T.c['EVENT_TYPE'] == 'ROUTING',
                T.c['ROUTING_NAME'],
                T.c['ROUTING_SELECTED_MODEL_ID'],
            ).label('routings'),
            self._distinct(
                T.c['EVENT_TYPE'].in_(
                    [*LIMIT_BLOCK_EVENT_TYPES, EventType.LIMIT_THRESHOLD.value]
                ),
                T.c['EVENT_TYPE'],
                self._attribute('limit_scope'),
                self._attribute('category'),
                self._attribute('threshold_percentage'),
            ).label('limits'),
        ]
        stmt = (
            select(T.c['REQUEST_UUID'], *columns)
            .select_from(Event)
            .where(*conditions)
            .group_by(T.c['REQUEST_UUID'])
        )

        with self.db.begin_session() as session:
            return {
                str(row[0]): EventsSummary.model_validate(
                    {c.name: value for c, value in zip(columns, row[1:])}
                )
                for row in session.execute(stmt).all()
            }

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
                'decision_input',
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

    def get_mcp_key_usage_paginated(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        params: Params,
        tags: list[str] | None = None,
    ) -> Page[Row]:
        """Rank the keys that made MCP invocations in a project.

        Membership comes from the event type alone: the emission side already
        decided what counts as an invocation, so no method or outcome filter
        belongs here.
        """
        T = self.T
        conditions = self._mcp_invocation_conditions(
            project_uuid=project_uuid,
            route_names=route_names,
            _from=_from,
            _to=_to,
            tags=tags,
        )

        group_by_columns = [
            T.c['API_KEY_UUID'],
            T.c['API_KEY_NAME'],
            T.c['GROUP_UUID'],
            T.c['GROUP_NAME'],
        ]
        stmt = (
            select(
                T.c['API_KEY_UUID'].label('key_uuid'),
                T.c['API_KEY_NAME'].label('key_name'),
                T.c['GROUP_UUID'].label('group_uuid'),
                T.c['GROUP_NAME'].label('group_name'),
                F.count().label('counter'),
                F.max(T.c['TIMESTAMP']).label('last_call'),
            )
            .select_from(Event)
            .where(*conditions)
            .group_by(*group_by_columns)
            # A total order. Count alone would let a key show up on two pages.
            # The key identifier breaks a full tie, read as text so the order
            # is the one an operator sees on screen.
            .order_by(
                text('counter DESC'),
                text('last_call DESC'),
                F.toString(T.c['API_KEY_UUID']),
            )
        )

        with self.db.begin_session() as session:
            # unique=False: every row is one key, so there is nothing to dedup.
            return paginate(session, stmt, params, unique=False)

    def _mcp_entity_column(self, entity_column: McpSeriesColumn) -> ColumnElement:
        """Read an entity column as text, so it groups and compares as a string.

        The alias and the target are already text. The two uuid columns are
        cast, so a caller can pass the uuid it got back from the grouped chart
        as it is.
        """
        column = self.T.c[entity_column]
        if entity_column in ('MCP_ALIAS', 'MCP_TARGET'):
            return column
        return F.cast(column, String)

    def _bucket_mcp_invocations(
        self,
        series_expr: ColumnElement,
        conditions: list,
        granularity: Literal['hours', 'days', 'weeks', 'months'],
        timezone_offset_seconds: int,
    ) -> list[InvocationChartDataPoint]:
        """Count MCP invocations per bucket and series value.

        The grouped chart and the per-entity drill-down both end here, so a
        drilled-in series can never disagree with its bar on the chart.
        """
        FIELD_NAMES = ['bucket', 'group_by_value', 'value']

        bucket_expr = with_timezone_offset(
            get_bucket_function(granularity),
            timezone_offset_seconds,
            self.T.c['TIMESTAMP'],
        )

        stmt = (
            select(
                bucket_expr.label('bucket'),
                series_expr.label('group_by_value'),
                F.count().label('value'),
            )
            .select_from(Event)
            .where(*conditions)
            .group_by(text('bucket'), series_expr)
            .order_by(text('bucket'), text('group_by_value'))
        )

        with self.db.begin_session() as session:
            res = session.execute(stmt).all()
            return [
                InvocationChartDataPoint.model_validate(
                    dict(zip(FIELD_NAMES, row_tuple))
                )
                for row_tuple in res
            ]

    def get_mcp_server_chart_data(
        self,
        project_uuid: UUID,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        granularity: Literal['hours', 'days', 'weeks', 'months'],
        group_by: Literal['services', 'groups', 'keys'],
        timezone_offset_seconds: int = 0,
        tags: list[str] | None = None,
    ) -> list[InvocationChartDataPoint]:
        """Bucket MCP invocations over time, one row per bucket and entity.

        Membership comes from the event type alone. The emission side already
        decided what counts. Deciding it again here would let the two drift.

        An invocation naming a server that is not configured on the route
        carries an empty alias. Those rows are kept, not dropped, so this
        count still agrees with the ranked key usage.
        """
        conditions = self._mcp_invocation_conditions(
            project_uuid=project_uuid,
            route_names=route_names,
            _from=_from,
            _to=_to,
            tags=tags,
        )
        return self._bucket_mcp_invocations(
            series_expr=self._mcp_entity_column(MCP_ENTITY_COLUMNS[group_by]),
            conditions=conditions,
            granularity=granularity,
            timezone_offset_seconds=timezone_offset_seconds,
        )

    def get_mcp_server_chart_data_by_entity(
        self,
        project_uuid: UUID,
        entity_column: McpEntityColumn,
        entity_value: str,
        route_names: list[str] | None,
        _from: datetime | None,
        _to: datetime | None,
        granularity: Literal['hours', 'days', 'weeks', 'months'],
        timezone_offset_seconds: int = 0,
        tags: list[str] | None = None,
        series_column: McpSeriesColumn | None = None,
    ) -> list[InvocationChartDataPoint]:
        """Bucket one entity's MCP invocations over time, one row per bucket.

        One aggregate serves the server, group and key drill-downs. It takes
        the column and the value, like the cost drill-down does. An entity
        with no rows in the window comes back empty. No registry can tell an
        unknown alias from a quiet one. A group or key lookup on every tick
        is not worth its cost.

        ``series_column`` is the column each row is keyed by. Left unset, it
        is the entity column, so the entity is its own single series. The
        server drill-down passes ``MCP_TARGET`` to get one series per tool,
        prompt or resource inside that server.

        Same membership rule as the grouped chart: the event type alone. No
        method or outcome filter belongs here either.
        """
        entity_expr = self._mcp_entity_column(entity_column)
        conditions = self._mcp_invocation_conditions(
            project_uuid=project_uuid,
            route_names=route_names,
            _from=_from,
            _to=_to,
            tags=tags,
        )
        conditions.append(entity_expr == entity_value)
        return self._bucket_mcp_invocations(
            series_expr=self._mcp_entity_column(series_column or entity_column),
            conditions=conditions,
            granularity=granularity,
            timezone_offset_seconds=timezone_offset_seconds,
        )

    def get_request_events(
        self,
        project_uuid: UUID,
        request_uuid: UUID,
        date_from: date,
        date_to: date,
    ) -> list[dict]:
        """Every event of one request, oldest first.

        Bounded to `[date_from, date_to]` on DATE so ClickHouse prunes
        partitions. GUARDRAIL_PARAMS is not read, and the `parameters` copy
        of it is dropped from ATTRIBUTES: guardrail parameters never leave.
        """
        T = self.T
        columns = [
            'EVENT_TYPE',
            'TIMESTAMP',
            'VALUE',
            'COST',
            'MODEL_ID',
            'MODEL_TYPE',
            'IS_CACHED_TOKENS',
            'CACHE_TYPE',
            'TARGET',
            'FALLBACK',
            'GUARDRAIL_NAME',
            'GUARDRAIL_TYPE',
            'GUARDRAIL_WHERE',
            'GUARDRAIL_BEHAVIOR',
            'IS_JUDGE',
            'IS_ROUTING',
            'ROUTING_NAME',
            'ROUTING_SELECTED_MODEL_ID',
            'MCP_METHOD',
            'MCP_ALIAS',
            'MCP_TARGET',
            'ATTRIBUTES',
        ]
        conditions = [
            T.c['REQUEST_UUID'] == str(request_uuid),
            T.c['DATE'] >= date_from,
            T.c['DATE'] <= date_to,
        ]
        self._add_project_filter(conditions, project_uuid)
        stmt = (
            select(*(T.c[c].label(c.lower()) for c in columns))
            .select_from(Event)
            .where(*conditions)
            .order_by(T.c['TIMESTAMP'])
        )

        with self.db.begin_session() as session:
            events = [row._asdict() for row in session.execute(stmt).all()]
        for event in events:
            event['attributes'] = {
                k: v for k, v in event['attributes'].items() if k != 'parameters'
            }
        return events
