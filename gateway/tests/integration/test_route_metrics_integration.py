"""The dashboard's per-route metrics on real ClickHouse.

Every kind of metric is read once for all the routes of the project, so the
number of queries does not grow with the number of routes.
"""

import datetime
from unittest.mock import MagicMock
import uuid

from tests.common.db_integration_ch import DatabaseIntegrationClickhouse
from tests.common.db_mock import (
    TEST_PROJECT_UUID,
    get_sample_event,
    get_sample_request_event,
)

from radicalbit_ai_gateway.db.dao.event_dao import EventDAO
from radicalbit_ai_gateway.db.dao.request_event_dao import RequestEventDAO
from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
from radicalbit_ai_gateway.models.request_event_type import RequestStatus
from radicalbit_ai_gateway.services.event_service import EventService

PROJECT = TEST_PROJECT_UUID
T0 = datetime.datetime(2026, 3, 10, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _config(route_names: list[str]) -> GatewayConfig:
    return GatewayConfig.model_validate(
        {
            'chat_models': [
                {
                    'model_id': 'gpt',
                    'model': 'openai/gpt-4o-mini',
                    'credentials': {'api_key': 'sk-dummy'},
                }
            ],
            'routes': {name: {'chat_models': ['gpt']} for name in route_names},
        }
    )


def _request(route_name, status=RequestStatus.SUCCESS, error_type='', **kwargs):
    return get_sample_request_event(
        request_uuid=uuid.uuid4(),
        route_name=route_name,
        timestamp=T0,
        project_uuid=PROJECT,
        request_status=status,
        error_type=error_type,
        **kwargs,
    )


def _event(route_name, event_type, value=1, timestamp=T0, **kwargs):
    return get_sample_event(
        request_uuid=uuid.uuid4(),
        route_name=route_name,
        event_type=event_type,
        value=value,
        timestamp=timestamp,
        project_uuid=PROJECT,
        **kwargs,
    )


class TestRouteMetricsIntegration(DatabaseIntegrationClickhouse):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key_service = MagicMock()
        cls.key_service.get_names_by_uuids.return_value = {}

    def _service(self, counted_db=None) -> EventService:
        db = counted_db or self.db
        return EventService(
            event_dao=EventDAO(db),
            request_event_dao=RequestEventDAO(db),
            key_service=self.key_service,
            group_service=MagicMock(),
        )

    def _routes(self, route_names, service=None):
        routes = (service or self._service()).get_total_counter_per_route(
            project_uuid=PROJECT,
            project_name='project',
            config=_config(route_names),
            include_groups=False,
            _from=None,
            _to=None,
        )
        return {route.route_name: route.metrics for route in routes}

    def test_each_route_gets_its_own_metrics(self):
        self.insert(
            [
                _request('route-a'),
                _request('route-a'),
                _request('route-a', RequestStatus.HANDLED_ERROR, 'RateLimitError'),
                _request('route-b'),
            ]
        )
        self.insert(
            [
                _event('route-a', 'INPUT_TOKEN_PROCESSED', value=100, model_id='gpt'),
                _event('route-a', 'OUTPUT_TOKEN_PROCESSED', value=40, model_id='gpt'),
                _event('route-b', 'INPUT_TOKEN_PROCESSED', value=7, model_id='gpt'),
            ]
        )

        metrics = self._routes(['route-a', 'route-b'])

        route_a, route_b = metrics['route-a'], metrics['route-b']
        assert route_a.total_requests == 3
        assert route_a.total_input_token_processed == 100
        assert route_a.total_output_token_processed == 40
        assert [(e.error_type, e.count) for e in route_a.errors.details] == [
            ('RateLimitError', 1)
        ]
        assert route_b.total_requests == 1
        assert route_b.total_input_token_processed == 7
        assert route_b.errors.details == []

    def test_a_route_with_no_traffic_reads_as_zero(self):
        self.insert([_request('route-a')])

        metrics = self._routes(['route-a', 'route-idle'])

        assert metrics['route-idle'].total_requests == 0
        assert metrics['route-idle'].total_input_token_processed == 0
        assert metrics['route-idle'].last_request_timestamp is None

    def test_a_route_outside_the_config_is_left_out(self):
        self.insert([_request('route-a'), _request('route-removed')])

        metrics = self._routes(['route-a'])

        assert list(metrics) == ['route-a']
        assert metrics['route-a'].total_requests == 1

    def test_the_query_count_does_not_grow_with_the_routes(self):
        self.insert([_request(f'route-{i}') for i in range(8)])
        counted_db = MagicMock(wraps=self.db)
        service = self._service(counted_db)

        self._routes(['route-0', 'route-1'], service)
        queries_for_two = len(counted_db.method_calls)
        counted_db.reset_mock()
        self._routes([f'route-{i}' for i in range(8)], service)

        assert queries_for_two == len(counted_db.method_calls) == 6

    def test_the_project_last_event_is_the_latest_of_its_type(self):
        later = T0 + datetime.timedelta(hours=1)
        self.insert(
            [
                _event('route-a', 'GUARDRAIL', name='pii', behavior='BLOCK'),
                _event('route-b', 'GUARDRAIL', timestamp=later, name='toxic'),
                _event('route-a', 'FALLBACK', target='gpt', fallback='backup'),
                _event('route-b', 'RATE_LIMIT', timestamp=later),
            ]
        )

        last_events = EventDAO(self.db).get_last_events(
            PROJECT, ['GUARDRAIL', 'FALLBACK', 'CACHE_HIT'], None, None
        )

        # One entry per type that has an event; CACHE_HIT has none.
        assert set(last_events) == {'GUARDRAIL', 'FALLBACK'}
        assert last_events['GUARDRAIL'].name == 'toxic'
        assert last_events['GUARDRAIL'].route_name == 'route-b'
        assert last_events['GUARDRAIL'].timestamp == later
        assert last_events['FALLBACK'].target == 'gpt'
        assert last_events['FALLBACK'].fallback == 'backup'

    def test_the_last_event_of_a_route_ignores_the_other_routes(self):
        later = T0 + datetime.timedelta(hours=1)
        self.insert(
            [
                _event('route-a', 'GUARDRAIL', name='pii'),
                _event('route-b', 'GUARDRAIL', timestamp=later, name='toxic'),
            ]
        )

        last_events = EventDAO(self.db).get_last_events_of_routes(
            PROJECT, ['GUARDRAIL'], ['route-a', 'route-b', 'route-idle'], None, None
        )

        assert {key: event.name for key, event in last_events.items()} == {
            ('route-a', 'GUARDRAIL'): 'pii',
            ('route-b', 'GUARDRAIL'): 'toxic',
        }
