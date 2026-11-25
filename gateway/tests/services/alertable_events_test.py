import uuid

from tests.common.mocked_gateway_config import get_plain_gateway
from tests.routes.test_alert_rule_route import EVERY_LIMIT, route_config

from radicalbit_ai_gateway.models.alert_rule_dto import AlertableEventsOut
from radicalbit_ai_gateway.models.project_entry import ProjectEntry
from radicalbit_ai_gateway.services.alertable_events import AlertableEvents

_PROJECT = uuid.uuid4()


def _without_stores() -> AlertableEvents:
    """No budget, project or credential store: the defaults answer."""
    config = get_plain_gateway('route-A')
    return AlertableEvents({'my-project': ProjectEntry(uuid=_PROJECT, config=config)})


async def test_without_a_project_store_no_project_exists():
    events = _without_stores()

    assert await events.for_project(_PROJECT) == AlertableEventsOut()
    assert (
        await events.project_stale_reason(_PROJECT, 'budget_limit')
        == 'The project no longer exists'
    )


async def test_without_a_credential_store_no_credential_exists():
    events = _without_stores()
    credential = uuid.uuid4()

    assert await events.for_credential(credential) == AlertableEventsOut()
    assert (
        await events.credential_stale_reason(credential, 'rate_limit')
        == 'The credential no longer exists'
    )


async def test_without_a_budget_store_the_route_budget_counts():
    config = route_config(limits=EVERY_LIMIT)
    events = AlertableEvents({'my-project': ProjectEntry(uuid=_PROJECT, config=config)})

    assert await events.offers(_PROJECT, 'chat', 'budget_limit-exceeded-1mo')
