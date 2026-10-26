"""The alert store keeps the state alert rules share across gateway replicas.

Every test runs on the Valkey testcontainer and on the in-process fallback.
"""

from datetime import UTC, datetime, timedelta

import pytest
from redis import Redis

from radicalbit_ai_gateway.alerting.alert_store import (
    InProcessAlertStore,
    RedisAlertStore,
    build_alert_store,
)

T0 = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime = T0):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture(params=['redis', 'in_process'])
def store(request, clock):
    if request.param == 'in_process':
        return InProcessAlertStore(clock=clock)
    url = request.getfixturevalue('redis_connection_url')
    Redis.from_url(url).flushdb()
    return RedisAlertStore(Redis.from_url(url), clock=clock)


def test_the_store_tells_the_time_of_its_clock(store, clock):
    assert store.now() == T0
    clock.advance(90)
    assert store.now() == T0 + timedelta(seconds=90)


def test_a_key_is_claimed_once(store):
    assert store.claim('alert:limit:r1:w1', ttl_seconds=60) is True
    assert store.claim('alert:limit:r1:w1', ttl_seconds=60) is False


def test_claims_on_different_keys_are_independent(store):
    assert store.claim('alert:limit:r1:w1', ttl_seconds=60) is True
    assert store.claim('alert:limit:r1:w2', ttl_seconds=60) is True


def test_a_counter_counts_and_is_taken_once(store):
    store.increment('alert:window:r1:0', ttl_seconds=600)
    store.increment('alert:window:r1:0', ttl_seconds=600)
    assert store.increment('alert:window:r1:0', ttl_seconds=600) == 3

    assert store.take('alert:window:r1:0') == 3
    assert store.take('alert:window:r1:0') == 0


def test_an_absent_counter_takes_zero(store):
    assert store.take('alert:window:never') == 0


def test_only_windows_closed_by_now_are_due(store):
    store.open_window('r1:0', closes_at=T0)
    store.open_window('r1:1', closes_at=T0 + timedelta(minutes=5))

    assert store.windows_due(T0) == ['r1:0']
    assert sorted(store.windows_due(T0 + timedelta(minutes=5))) == ['r1:0', 'r1:1']


def test_a_window_is_closed_once(store):
    store.open_window('r1:0', closes_at=T0)

    assert store.close_window('r1:0') is True
    assert store.close_window('r1:0') is False
    assert store.windows_due(T0) == []


def test_in_process_claims_and_counters_expire_with_the_clock(clock):
    store = InProcessAlertStore(clock=clock)
    store.claim('claim', ttl_seconds=60)
    store.increment('counter', ttl_seconds=60)

    clock.advance(60)

    assert store.claim('claim', ttl_seconds=60) is True
    assert store.take('counter') == 0


def test_without_redis_the_store_is_in_process():
    assert isinstance(build_alert_store(redis_url=None), InProcessAlertStore)


def test_with_redis_the_store_uses_it(redis_connection_url):
    assert isinstance(
        build_alert_store(redis_url=redis_connection_url), RedisAlertStore
    )
