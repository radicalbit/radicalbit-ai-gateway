"""The request detail on real ClickHouse (AG-1109, ADR 0010).

One request by its UUID: its `request_event` row (the Outcome), its trace ID
if it left one, and every event it emitted in time order.
"""

import datetime
import uuid

import pytest

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
from radicalbit_ai_gateway.models.request_event_type import RequestStatus, RequestType
from radicalbit_ai_gateway.services.requests_service import RequestsService
from radicalbit_ai_gateway.utils.exceptions import GatewayNotFoundError

PROJECT = TEST_PROJECT_UUID
REQUEST_UUID_ATTR = 'traceloop.association.properties.request_uuid'
T0 = datetime.datetime(2026, 3, 10, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _request(request_uuid, timestamp=T0, **kwargs):
    return get_sample_request_event(
        request_uuid=request_uuid,
        timestamp=timestamp,
        project_uuid=PROJECT,
        **kwargs,
    )


def _event(request_uuid, event_type, timestamp=T0, **kwargs):
    return get_sample_event(
        request_uuid=request_uuid,
        event_type=event_type,
        timestamp=timestamp,
        project_uuid=PROJECT,
        **kwargs,
    )


class TestRequestDetailIntegration(DatabaseIntegrationClickhouse):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = RequestsService(
            request_event_dao=RequestEventDAO(cls.db),
            event_dao=EventDAO(cls.db),
            otel_traces_dao=OtelTracesDAO(cls.db),
        )

    def test_an_unknown_request_is_not_found(self):
        with pytest.raises(GatewayNotFoundError):
            self.service.get_request(PROJECT, uuid.uuid4())

    def test_a_request_of_another_project_is_not_found(self):
        request_uuid = uuid.uuid4()
        self.insert([_request(request_uuid)])

        with pytest.raises(GatewayNotFoundError):
            self.service.get_request(uuid.uuid4(), request_uuid)

    def test_a_request_with_no_trace_has_its_outcome_and_a_null_trace_id(self):
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
                    http_status_code=429,
                    duration_ms=12.5,
                    error_type='RateLimitExceededError',
                    error_code='rate_limit_exceeded',
                    tags=['team=a'],
                )
            ]
        )

        detail = self.service.get_request(PROJECT, request_uuid)

        assert detail.request_uuid == request_uuid
        assert detail.trace_id is None
        assert detail.route_name == 'route-a'
        assert detail.request_type == RequestType.EMBEDDINGS
        assert detail.tags == ['team=a']
        assert detail.group_uuid == group_uuid
        assert detail.group_name == 'group-a'
        assert detail.api_key_uuid == key_uuid
        assert detail.api_key_name == 'key-a'
        assert detail.request_status == RequestStatus.HANDLED_ERROR
        assert detail.http_status_code == 429
        assert detail.error_type == 'RateLimitExceededError'
        assert detail.error_code == 'rate_limit_exceeded'
        assert detail.duration_ms == 12.5
        assert detail.created_at == int(T0.timestamp())
        assert detail.events == []

    def test_events_come_in_time_order_with_their_columns(self):
        request_uuid = uuid.uuid4()
        at = lambda ms: T0 - datetime.timedelta(milliseconds=ms)  # noqa: E731
        self.insert([_request(request_uuid)])
        # Inserted out of order on purpose.
        self.insert(
            [
                _event(
                    request_uuid,
                    'OUTPUT_TOKEN_PROCESSED',
                    timestamp=at(10),
                    value=20,
                    cost=0.002,
                    model_id='gpt-4o',
                ),
                _event(
                    request_uuid,
                    'MODEL_INVOCATION',
                    timestamp=at(300),
                    model_id='gpt-4o',
                    model_type='chat',
                ),
                _event(
                    request_uuid,
                    'INPUT_TOKEN_PROCESSED',
                    timestamp=at(20),
                    value=30,
                    cost=0.003,
                    model_id='gpt-4o',
                    is_judge=True,
                ),
                _event(
                    request_uuid,
                    'FALLBACK',
                    timestamp=at(200),
                    target='gpt-4o',
                    fallback='claude',
                ),
                # Another request, and the same request UUID in another project
                _event(uuid.uuid4(), 'MODEL_INVOCATION', timestamp=at(250)),
                get_sample_event(
                    request_uuid=request_uuid,
                    event_type='CACHE_HIT',
                    timestamp=at(250),
                    project_uuid=uuid.uuid4(),
                ),
            ]
        )
        self.insert(
            [
                get_sample_otel_span(
                    timestamp=at(400),
                    trace_id='trace-a',
                    span_id='root-a',
                    span_name='chat_completions.workflow',
                    span_attributes={REQUEST_UUID_ATTR: str(request_uuid)},
                )
            ]
        )

        detail = self.service.get_request(PROJECT, request_uuid)

        assert detail.trace_id == 'trace-a'
        assert [e.event_type for e in detail.events] == [
            'MODEL_INVOCATION',
            'FALLBACK',
            'INPUT_TOKEN_PROCESSED',
            'OUTPUT_TOKEN_PROCESSED',
        ]
        invocation, fallback, input_tokens, output_tokens = detail.events
        assert invocation.timestamp == at(300)
        assert invocation.model_id == 'gpt-4o'
        assert invocation.model_type == 'chat'
        assert fallback.target == 'gpt-4o'
        assert fallback.fallback == 'claude'
        assert fallback.attributes == {'target': 'gpt-4o', 'fallback': 'claude'}
        assert input_tokens.value == 30
        assert input_tokens.cost == 0.003
        assert input_tokens.is_judge is True
        assert output_tokens.value == 20
        assert output_tokens.cost == 0.002
        assert not any(e.blocking for e in detail.events)

    def test_only_block_guardrails_and_limit_events_are_blocking(self):
        request_uuid = uuid.uuid4()
        self.insert([_request(request_uuid)])
        cases = [
            ('GUARDRAIL', 'BLOCK', True),
            ('GUARDRAIL', 'WARN', False),
            ('GUARDRAIL', 'SOFT_BLOCK', False),
            ('RATE_LIMIT', '', True),
            ('TOKEN_INPUT_LIMIT', '', True),
            ('CREDENTIAL_BUDGET_LIMIT', '', True),
            ('PROJECT_BUDGET_LIMIT', '', True),
            ('LIMIT_THRESHOLD', '', False),
            ('MCP_INVOCATION', '', False),
            ('CACHE_HIT', '', False),
        ]
        self.insert(
            [
                _event(
                    request_uuid,
                    event_type,
                    timestamp=T0 - datetime.timedelta(seconds=len(cases) - i),
                    behavior=behavior,
                )
                for i, (event_type, behavior, _) in enumerate(cases)
            ]
        )

        detail = self.service.get_request(PROJECT, request_uuid)

        assert [
            (e.event_type, e.guardrail_behavior or '', e.blocking)
            for e in detail.events
        ] == cases

    def test_guardrail_parameters_are_never_returned(self):
        request_uuid = uuid.uuid4()
        self.insert([_request(request_uuid)])
        self.insert(
            [
                _event(
                    request_uuid,
                    'GUARDRAIL',
                    name='pii',
                    type='presidio',
                    where='input',
                    behavior='BLOCK',
                    parameters="{'secret_pattern': 'sk-.*'}",
                )
            ]
        )

        detail = self.service.get_request(PROJECT, request_uuid)

        [guardrail] = detail.events
        assert guardrail.guardrail_name == 'pii'
        assert guardrail.attributes == {
            'name': 'pii',
            'type': 'presidio',
            'where': 'input',
            'behavior': 'BLOCK',
        }
        body = detail.model_dump_json(by_alias=True)
        assert 'parameters' not in body.lower()
        assert 'guardrailParams' not in body
        assert 'secret_pattern' not in body

    def test_events_of_a_request_that_crossed_midnight_are_listed(self):
        # request_event is written when the request ends, its events before.
        just_after = datetime.datetime(2026, 3, 10, 0, 0, 5, tzinfo=datetime.UTC)
        just_before = datetime.datetime(2026, 3, 9, 23, 59, 58, tzinfo=datetime.UTC)
        request_uuid = uuid.uuid4()
        self.insert([_request(request_uuid, timestamp=just_after)])
        self.insert(
            [
                _event(request_uuid, 'OUTPUT_TOKEN_PROCESSED', timestamp=just_after),
                _event(request_uuid, 'MODEL_INVOCATION', timestamp=just_before),
            ]
        )
        self.insert(
            [
                get_sample_otel_span(
                    timestamp=just_before,
                    trace_id='trace-x',
                    span_id='root-x',
                    span_name='chat_completions.workflow',
                    span_attributes={REQUEST_UUID_ATTR: str(request_uuid)},
                )
            ]
        )

        detail = self.service.get_request(PROJECT, request_uuid)

        assert detail.trace_id == 'trace-x'
        assert [e.event_type for e in detail.events] == [
            'MODEL_INVOCATION',
            'OUTPUT_TOKEN_PROCESSED',
        ]

    def test_events_outside_the_request_date_window_are_not_listed(self):
        request_uuid = uuid.uuid4()
        self.insert([_request(request_uuid, timestamp=T0)])
        self.insert(
            [
                _event(request_uuid, 'MODEL_INVOCATION', timestamp=T0),
                _event(
                    request_uuid,
                    'FALLBACK',
                    timestamp=T0 - datetime.timedelta(days=2),
                ),
                _event(
                    request_uuid,
                    'CACHE_HIT',
                    timestamp=T0 + datetime.timedelta(days=1),
                ),
            ]
        )

        detail = self.service.get_request(PROJECT, request_uuid)

        assert [e.event_type for e in detail.events] == ['MODEL_INVOCATION']
