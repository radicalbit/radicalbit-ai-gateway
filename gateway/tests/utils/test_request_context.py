import pytest

from radicalbit_ai_gateway.utils.request_context import (
    current_route_config_ctx,
    reset_route_context,
    set_current_route_config,
)


@pytest.fixture(autouse=True)
def _clean_ctx():
    current_route_config_ctx.set(None)
    yield
    current_route_config_ctx.set(None)


def test_set_publishes_config():
    set_current_route_config({'route': 'A'})
    assert current_route_config_ctx.get() == {'route': 'A'}


@pytest.mark.asyncio
async def test_reset_decorator_clears_after_success():
    @reset_route_context
    async def handler():
        set_current_route_config({'route': 'A'})
        return 'ok'

    assert await handler() == 'ok'
    assert current_route_config_ctx.get() is None


@pytest.mark.asyncio
async def test_reset_decorator_clears_after_error():
    @reset_route_context
    async def handler():
        set_current_route_config({'route': 'A'})
        raise RuntimeError('boom')

    with pytest.raises(RuntimeError):
        await handler()
    assert current_route_config_ctx.get() is None
