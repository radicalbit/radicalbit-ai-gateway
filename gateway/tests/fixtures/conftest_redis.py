import pytest
from redis import Redis
from redis.exceptions import ConnectionError
from testcontainers.redis import RedisContainer


def get_redis_url(container: RedisContainer) -> str:
    host = container.get_container_host_ip()
    port = container.get_exposed_port(6379)
    return f'redis://{host}:{port}/0'


@pytest.fixture(scope='session')
def redis_connection_url():
    with RedisContainer('valkey/valkey-bundle:8.1.2') as redis_container:
        url = get_redis_url(redis_container)
        client = Redis.from_url(url)
        try:
            client.ping()
        except ConnectionError as e:
            pytest.fail(
                f'Failed to connect to Testcontainers Redis at {url}. Error: {e}'
            )
        yield url
        client.flushdb()


@pytest.fixture(scope='session')
def redis_client(redis_connection_url):
    return Redis.from_url(redis_connection_url)
