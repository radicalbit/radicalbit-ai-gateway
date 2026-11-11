"""The Requests list on real ClickHouse: one row per request (AG-1105, ADR 0010).

The list pages over `request_event`, then attaches tokens and cost from `event`
and the trace ID from `otel_traces`, one batched query each per page.
"""

import datetime
from unittest.mock import MagicMock
import uuid

from fastapi_pagination import Params

from tests.common.db_integration_ch import DatabaseIntegrationClickhouse
from tests.common.db_mock import (
    TEST_PROJECT_UUID,
    get_sample_event,
    get_sample_otel_span,
    get_sample_request_event,
)

from radicalbit_ai_gateway.db.dao.event_dao import EventDAO
from radicalbit_ai_gateway.db.dao.otel_traces_dao import OtelTracesDAO
from radicalbit_ai_gateway.db.dao.request_event_dao import RequestEventDAO
from radicalbit_ai_gateway.models.request_dto import IconTone
from radicalbit_ai_gateway.models.request_event_type import RequestStatus, RequestType
from radicalbit_ai_gateway.services.requests_service import RequestsService

PROJECT = TEST_PROJECT_UUID
REQUEST_UUID_ATTR = 'traceloop.association.properties.request_uuid'
T0 = datetime.datetime(2026, 3, 10, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _request(request_uuid=None, timestamp=T0, **kwargs):
    return get_sample_request_event(
        request_uuid=request_uuid or uuid.uuid4(),
        timestamp=timestamp,
        project_uuid=PROJECT,
        **kwargs,
    )


def _event(request_uuid, event_type, value=0, cost=0.0, timestamp=T0, **kwargs):
    return get_sample_event(
        request_uuid=request_uuid,
        event_type=event_type,
        value=value,
        cost=cost,
        timestamp=timestamp,
        project_uuid=PROJECT,
        **kwargs,
    )


def _root_span(request_uuid, trace_id, timestamp=T0):
    return get_sample_otel_span(
        timestamp=timestamp,
        trace_id=trace_id,
        span_id=f'root-{trace_id}',
        span_name='chat_completions.workflow',
        span_attributes={REQUEST_UUID_ATTR: str(request_uuid)},
    )


class TestRequestsServiceIntegration(DatabaseIntegrationClickhouse):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.request_event_dao = RequestEventDAO(cls.db)
        cls.event_dao = EventDAO(cls.db)
        cls.otel_traces_dao = OtelTracesDAO(cls.db)
        cls.service = RequestsService(
            request_event_dao=cls.request_event_dao,
            event_dao=cls.event_dao,
            otel_traces_dao=cls.otel_traces_dao,
        )

    def _list(self, page=1, size=50, **filters):
        kwargs = {
            'route_names': None,
            'group_uuids': None,
            'key_uuids': None,
            '_from': None,
            '_to': None,
            **filters,
        }
        return self.service.get_requests(
            project_uuid=PROJECT, params=Params(page=page, size=size), **kwargs
        )

    def test_a_request_with_no_trace_is_a_row_with_a_null_trace_id(self):
        request_uuid = uuid.uuid4()
        key_uuid, group_uuid = uuid.uuid4(), uuid.uuid4()
        self.insert(
            [
                _request(
                    request_uuid,
                    route_name='route-a',
                    api_key_uuid=key_uuid,
                    api_key_name='key-a',
                    group_uuid=group_uuid,
                    group_name='group-a',
                    request_type=RequestType.EMBEDDINGS,
                    request_status=RequestStatus.HANDLED_ERROR,
                    http_status_code=422,
                    duration_ms=12.5,
                    error_type='RequestValidationError',
                    error_code='request_validation_error',
                    tags=['team=a'],
                )
            ]
        )

        page = self._list()

        assert page.total == 1
        [row] = page.items
        assert row.request_uuid == request_uuid
        assert row.trace_id is None
        assert row.route_name == 'route-a'
        assert row.request_type == RequestType.EMBEDDINGS
        assert row.tags == ['team=a']
        assert row.group_uuid == group_uuid
        assert row.group_name == 'group-a'
        assert row.api_key_uuid == key_uuid
        assert row.api_key_name == 'key-a'
        assert row.request_status == RequestStatus.HANDLED_ERROR
        assert row.http_status_code == 422
        assert row.error_type == 'RequestValidationError'
        assert row.error_code == 'request_validation_error'
        assert row.duration_ms == 12.5
        assert row.created_at == int(T0.timestamp())
        assert row.total_tokens == 0
        assert row.cost == 0.0

    def test_a_traced_request_carries_its_trace_id(self):
        traced, untraced = uuid.uuid4(), uuid.uuid4()
        self.insert([_request(traced), _request(untraced)])
        self.insert(
            [
                _root_span(traced, 'trace-1'),
                # A child span carries the attribute too but is not the root.
                get_sample_otel_span(
                    timestamp=T0,
                    trace_id='trace-1',
                    span_id='child',
                    parent_span_id='root-trace-1',
                    span_attributes={REQUEST_UUID_ATTR: str(traced)},
                ),
            ]
        )

        page = self._list()

        trace_ids = {row.request_uuid: row.trace_id for row in page.items}
        assert trace_ids == {traced: 'trace-1', untraced: None}

    def test_a_trace_of_another_project_is_not_attached(self):
        request_uuid = uuid.uuid4()
        self.insert([_request(request_uuid)])
        self.insert(
            [
                get_sample_otel_span(
                    timestamp=T0,
                    trace_id='foreign',
                    span_attributes={
                        REQUEST_UUID_ATTR: str(request_uuid),
                        'traceloop.association.properties.project_uuid': str(
                            uuid.uuid4()
                        ),
                    },
                )
            ]
        )

        [row] = self._list().items

        assert row.trace_id is None

    def test_tokens_and_cost_sum_processed_token_events_including_judges(self):
        request_uuid, other = uuid.uuid4(), uuid.uuid4()
        self.insert([_request(request_uuid), _request(other)])
        self.insert(
            [
                _event(request_uuid, 'INPUT_TOKEN_PROCESSED', value=100, cost=0.001),
                _event(request_uuid, 'OUTPUT_TOKEN_PROCESSED', value=40, cost=0.002),
                # A judge invocation is part of what the request cost.
                _event(
                    request_uuid,
                    'INPUT_TOKEN_PROCESSED',
                    value=10,
                    cost=0.0005,
                    is_judge=True,
                ),
                # Cached tokens are not processed tokens.
                _event(request_uuid, 'CACHE_INPUT_TOKENS', value=1000, cost=0.5),
                _event(request_uuid, 'CACHE_OUTPUT_TOKENS', value=1000, cost=0.5),
                # Other event types carry no tokens.
                _event(request_uuid, 'MODEL_INVOCATION', value=1, cost=0.9),
                _event(other, 'INPUT_TOKEN_PROCESSED', value=7, cost=0.07),
            ]
        )

        rows = {row.request_uuid: row for row in self._list().items}

        assert rows[request_uuid].total_tokens == 150
        assert rows[request_uuid].cost == 0.0035
        assert rows[other].total_tokens == 7
        assert rows[other].cost == 0.07

    def test_events_of_another_project_are_not_attached(self):
        request_uuid = uuid.uuid4()
        self.insert([_request(request_uuid)])
        self.insert(
            [
                get_sample_event(
                    request_uuid=request_uuid,
                    event_type='INPUT_TOKEN_PROCESSED',
                    value=100,
                    cost=1.0,
                    timestamp=T0,
                    project_uuid=uuid.uuid4(),
                )
            ]
        )

        [row] = self._list().items

        assert row.total_tokens == 0
        assert row.cost == 0.0

    def _icons(self, *events):
        """Return the icons of a request holding `events`, (type, kwargs) pairs."""
        request_uuid = uuid.uuid4()
        self.insert([_request(request_uuid)])
        if events:
            self.insert([_event(request_uuid, t, **kw) for t, kw in events])
        [row] = self._list().items
        self.clean()
        return row.icons

    @staticmethod
    def _lit(icons):
        return {
            name
            for name in ['guardrail', 'cache', 'fallback', 'routing', 'limits']
            if getattr(icons, name) is not None
        }

    def test_a_request_with_no_event_shows_no_icon(self):
        assert self._lit(self._icons()) == set()

    def test_a_guardrail_tone_follows_its_behavior(self):
        for behavior, tone in [
            ('BLOCK', IconTone.ERROR),
            ('WARN', IconTone.WARNING),
            ('SOFT_BLOCK', IconTone.WARNING),
            ('REDACT', IconTone.SUCCESS),
            ('', IconTone.SUCCESS),
        ]:
            icons = self._icons(('GUARDRAIL', {'behavior': behavior}))
            assert self._lit(icons) == {'guardrail'}, behavior
            assert icons.guardrail.tone == tone, behavior

    def test_the_highest_tone_wins(self):
        icons = self._icons(
            ('GUARDRAIL', {'name': 'pii', 'behavior': 'REDACT', 'where': 'input'}),
            ('GUARDRAIL', {'name': 'tox', 'behavior': 'BLOCK', 'where': 'output'}),
            ('GUARDRAIL', {'name': 'len', 'behavior': 'WARN', 'where': 'input'}),
        )
        assert icons.guardrail.tone == IconTone.ERROR
        icons = self._icons(
            ('GUARDRAIL', {'behavior': 'REDACT'}),
            ('GUARDRAIL', {'behavior': 'SOFT_BLOCK'}),
        )
        assert icons.guardrail.tone == IconTone.WARNING

    def test_a_guardrail_tooltip_lists_each_guardrail_that_fired(self):
        icons = self._icons(
            ('GUARDRAIL', {'name': 'pii', 'behavior': 'REDACT', 'where': 'input'}),
            ('GUARDRAIL', {'name': 'tox', 'behavior': 'BLOCK', 'where': 'output'}),
        )
        assert {(d.name, d.behavior, d.position) for d in icons.guardrail.details} == {
            ('pii', 'REDACT', 'input'),
            ('tox', 'BLOCK', 'output'),
        }

    def test_a_cache_hit_is_a_success_with_its_cache_type(self):
        icons = self._icons(('CACHE_HIT', {'cache_type': 'semantic'}))
        assert self._lit(icons) == {'cache'}
        assert icons.cache.tone == IconTone.SUCCESS
        assert [d.cache_type for d in icons.cache.details] == ['semantic']

    def test_a_fallback_is_a_warning_with_its_target_and_fallback_model(self):
        icons = self._icons(('FALLBACK', {'target': 'gpt-4o', 'fallback': 'claude'}))
        assert self._lit(icons) == {'fallback'}
        assert icons.fallback.tone == IconTone.WARNING
        [detail] = icons.fallback.details
        assert (detail.target, detail.fallback_model) == ('gpt-4o', 'claude')

    def test_a_routing_is_a_success_with_its_name_and_chosen_model(self):
        icons = self._icons(
            ('ROUTING', {'routing_name': 'smart', 'selected_model_id': 'gpt-4o-mini'})
        )
        assert self._lit(icons) == {'routing'}
        assert icons.routing.tone == IconTone.SUCCESS
        [detail] = icons.routing.details
        assert (detail.routing_name, detail.selected_model) == (
            'smart',
            'gpt-4o-mini',
        )

    def test_every_limit_block_is_an_error(self):
        for limit in [
            'RATE_LIMIT',
            'TOKEN_INPUT_LIMIT',
            'TOKEN_OUTPUT_LIMIT',
            'AUDIO_DURATION_LIMIT',
            'BUDGET_LIMIT',
            'CREDENTIAL_RATE_LIMIT',
            'CREDENTIAL_TOKEN_INPUT_LIMIT',
            'CREDENTIAL_TOKEN_OUTPUT_LIMIT',
            'CREDENTIAL_BUDGET_LIMIT',
            'PROJECT_BUDGET_LIMIT',
        ]:
            icons = self._icons(
                (limit, {'limit_scope': 'credential', 'category': 'budget'})
            )
            assert self._lit(icons) == {'limits'}, limit
            assert icons.limits.tone == IconTone.ERROR, limit
            [detail] = icons.limits.details
            assert (detail.limit_scope, detail.category) == ('credential', 'budget')
            assert detail.threshold_percentage is None

    def test_a_limit_threshold_is_a_warning_with_its_percentage(self):
        icons = self._icons(
            (
                'LIMIT_THRESHOLD',
                {
                    'limit_scope': 'route',
                    'category': 'token_input',
                    'threshold_percentage': '80',
                },
            )
        )
        assert self._lit(icons) == {'limits'}
        assert icons.limits.tone == IconTone.WARNING
        [detail] = icons.limits.details
        assert (detail.limit_scope, detail.category, detail.threshold_percentage) == (
            'route',
            'token_input',
            80,
        )

    def test_a_limit_block_outranks_a_threshold(self):
        icons = self._icons(
            ('LIMIT_THRESHOLD', {'threshold_percentage': '90'}),
            ('RATE_LIMIT', {}),
        )
        assert icons.limits.tone == IconTone.ERROR
        assert len(icons.limits.details) == 2

    def test_mcp_token_and_model_events_show_no_icon(self):
        icons = self._icons(
            ('MCP_INVOCATION', {}),
            ('MODEL_INVOCATION', {}),
            ('INPUT_TOKEN_PROCESSED', {}),
            ('OUTPUT_TOKEN_PROCESSED', {}),
            ('CACHE_INPUT_TOKENS', {}),
            ('CACHE_OUTPUT_TOKENS', {}),
        )
        assert self._lit(icons) == set()

    def test_icons_belong_to_their_own_request(self):
        lit, dark = uuid.uuid4(), uuid.uuid4()
        self.insert([_request(lit), _request(dark)])
        self.insert(
            [
                _event(lit, 'GUARDRAIL', behavior='WARN'),
                _event(lit, 'CACHE_HIT'),
                _event(lit, 'FALLBACK'),
                _event(lit, 'ROUTING'),
                _event(lit, 'RATE_LIMIT'),
                _event(dark, 'INPUT_TOKEN_PROCESSED', value=5),
            ]
        )

        rows = {row.request_uuid: row for row in self._list().items}

        assert self._lit(rows[lit].icons) == {
            'guardrail',
            'cache',
            'fallback',
            'routing',
            'limits',
        }
        assert self._lit(rows[dark].icons) == set()
        assert rows[dark].total_tokens == 5

    def test_a_page_costs_one_events_query_and_one_trace_query(self):
        # Five requests on five different days.
        seeds = [(uuid.uuid4(), T0 - datetime.timedelta(days=i)) for i in range(5)]
        self.insert([_request(u, timestamp=ts) for u, ts in seeds])
        self.insert(
            [
                _event(u, 'INPUT_TOKEN_PROCESSED', value=1, timestamp=ts)
                for u, ts in seeds
            ]
        )
        event_dao = MagicMock(wraps=self.event_dao)
        otel_traces_dao = MagicMock(wraps=self.otel_traces_dao)
        service = RequestsService(
            request_event_dao=self.request_event_dao,
            event_dao=event_dao,
            otel_traces_dao=otel_traces_dao,
        )

        page = service.get_requests(
            project_uuid=PROJECT,
            route_names=None,
            group_uuids=None,
            key_uuids=None,
            _from=None,
            _to=None,
            params=Params(page=1, size=50),
        )

        assert len(page.items) == 5
        assert all(row.total_tokens == 1 for row in page.items)
        assert len(event_dao.method_calls) == 1
        assert len(otel_traces_dao.method_calls) == 1

    def test_events_of_a_request_that_crossed_midnight_are_attached(self):
        # request_event is written when the request ends, its events before.
        just_after_midnight = datetime.datetime(
            2026, 3, 10, 0, 0, 5, tzinfo=datetime.timezone.utc
        )
        just_before_midnight = datetime.datetime(
            2026, 3, 9, 23, 59, 58, tzinfo=datetime.timezone.utc
        )
        request_uuid = uuid.uuid4()
        self.insert([_request(request_uuid, timestamp=just_after_midnight)])
        self.insert(
            [
                _event(
                    request_uuid,
                    'INPUT_TOKEN_PROCESSED',
                    value=30,
                    cost=0.003,
                    timestamp=just_before_midnight,
                ),
                _event(
                    request_uuid,
                    'OUTPUT_TOKEN_PROCESSED',
                    value=20,
                    cost=0.002,
                    timestamp=just_after_midnight,
                ),
            ]
        )
        self.insert([_root_span(request_uuid, 'trace-x', just_before_midnight)])

        [row] = self._list().items

        assert row.total_tokens == 50
        assert row.cost == 0.005
        assert row.trace_id == 'trace-x'

    def test_events_outside_the_page_date_range_are_not_attached(self):
        request_uuid = uuid.uuid4()
        self.insert([_request(request_uuid, timestamp=T0)])
        self.insert(
            [
                _event(request_uuid, 'INPUT_TOKEN_PROCESSED', value=5, cost=0.5),
                _event(
                    request_uuid,
                    'INPUT_TOKEN_PROCESSED',
                    value=1000,
                    cost=10.0,
                    timestamp=T0 - datetime.timedelta(days=3),
                ),
                _event(
                    request_uuid,
                    'INPUT_TOKEN_PROCESSED',
                    value=1000,
                    cost=10.0,
                    timestamp=T0 + datetime.timedelta(days=1),
                ),
            ]
        )

        [row] = self._list().items

        assert row.total_tokens == 5
        assert row.cost == 0.5

    def test_pages_are_newest_first(self):
        uuids = [uuid.uuid4() for _ in range(5)]
        # uuids[0] is the newest
        self.insert(
            [
                _request(u, timestamp=T0 - datetime.timedelta(minutes=i))
                for i, u in enumerate(uuids)
            ]
        )

        first = self._list(page=1, size=2)
        second = self._list(page=2, size=2)
        third = self._list(page=3, size=2)

        assert first.total == 5
        assert [r.request_uuid for r in first.items] == uuids[0:2]
        assert [r.request_uuid for r in second.items] == uuids[2:4]
        assert [r.request_uuid for r in third.items] == uuids[4:5]

    def test_only_the_project_requests_are_listed(self):
        mine = uuid.uuid4()
        self.insert(
            [
                _request(mine),
                get_sample_request_event(timestamp=T0, project_uuid=uuid.uuid4()),
            ]
        )

        page = self._list()

        assert [r.request_uuid for r in page.items] == [mine]

    def test_filters(self):
        group_a, group_b = uuid.uuid4(), uuid.uuid4()
        key_a, key_b = uuid.uuid4(), uuid.uuid4()
        base = _request
        r_route = uuid.uuid4()
        r_group = uuid.uuid4()
        r_key = uuid.uuid4()
        r_type = uuid.uuid4()
        r_tags = uuid.uuid4()
        r_old = uuid.uuid4()
        self.insert(
            [
                base(
                    r_route,
                    route_name='route-x',
                    group_uuid=group_b,
                    api_key_uuid=key_b,
                ),
                base(r_group, group_uuid=group_a, api_key_uuid=key_b),
                base(r_key, group_uuid=group_b, api_key_uuid=key_a),
                base(
                    r_type,
                    group_uuid=group_b,
                    api_key_uuid=key_b,
                    request_type=RequestType.MCP,
                ),
                base(
                    r_tags,
                    group_uuid=group_b,
                    api_key_uuid=key_b,
                    tags=['team=a', 'env=prod'],
                ),
                base(
                    r_old,
                    group_uuid=group_b,
                    api_key_uuid=key_b,
                    timestamp=T0 - datetime.timedelta(days=2),
                ),
            ]
        )

        def listed(**filters):
            return {r.request_uuid for r in self._list(**filters).items}

        assert listed(route_names=['route-x']) == {r_route}
        assert listed(group_uuids=[group_a]) == {r_group}
        assert listed(key_uuids=[key_a]) == {r_key}
        assert listed(request_types=[RequestType.MCP]) == {r_type}
        assert listed(tags=['team=a', 'env=prod']) == {r_tags}
        assert listed(tags=['team=a', 'env=dev']) == set()
        assert listed(
            _from=T0 - datetime.timedelta(days=3),
            _to=T0 - datetime.timedelta(days=1),
        ) == {r_old}
        assert len(listed()) == 6
