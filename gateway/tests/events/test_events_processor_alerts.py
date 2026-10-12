from unittest.mock import MagicMock

from radicalbit_ai_gateway.events.events_processor import _dispatch_alert_if_matching
from radicalbit_ai_gateway.models.event_payload import (
    CacheEventPayload,
    FallbackEventPayload,
    GuardrailEventPayload,
)
from radicalbit_ai_gateway.models.event_type import EventType

BASE = {
    'request_uuid': 'r1',
    'route_name': 'chat',
    'value': 1,
    'api_key_uuid': 'k1',
    'api_key_name': 'key',
    'group_uuid': 'g1',
    'group_name': 'group',
    'project_uuid': 'p1',
    'project_name': 'acme',
}


def dispatched_event(event) -> str | None:
    service = MagicMock()
    _dispatch_alert_if_matching(service, event)
    if not service.dispatch_event_notification.called:
        return None
    return service.dispatch_event_notification.call_args.kwargs['event_name']


def test_guardrail_event_dispatches_by_phase_and_name():
    event = GuardrailEventPayload(
        **BASE,
        event_type=EventType.GUARDRAIL,
        name='pii',
        type='contains',
        where='INPUT',
        parameters='',
        behavior='block',
    )

    assert dispatched_event(event) == 'guardrail-input-pii'


def test_fallback_event_dispatches():
    event = FallbackEventPayload(
        **BASE, event_type=EventType.FALLBACK, target='gpt-4', fallback='gpt-3.5'
    )

    assert dispatched_event(event) == 'fallback-triggered'


def test_cache_hit_is_not_alertable():
    event = CacheEventPayload(
        **BASE, event_type=EventType.CACHE_HIT, cache_type='exact', model_id='gpt-4'
    )

    assert dispatched_event(event) is None
