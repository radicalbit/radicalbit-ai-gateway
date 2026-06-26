from langchain_core.messages import HumanMessage
import pytest

import radicalbit_ai_gateway.preprocessing as preprocessing_module
from radicalbit_ai_gateway.preprocessing import (
    PreprocessingError,
    PreprocessingPlugin,
    register_preprocessing_plugin,
    run_preprocessing,
)
from radicalbit_ai_gateway.utils.exceptions import GatewayBadRequest


@pytest.fixture(autouse=True)
def _clear_registry():
    """Each test starts with an empty preprocessing registry."""
    preprocessing_module._registered.clear()
    yield
    preprocessing_module._registered.clear()


class _Upper(PreprocessingPlugin):
    async def preprocess(self, messages):
        for m in messages:
            if isinstance(m.content, str):
                m.content = m.content.upper()
        return messages


class _Suffix(PreprocessingPlugin):
    def __init__(self, suffix: str):
        self._suffix = suffix

    async def preprocess(self, messages):
        for m in messages:
            if isinstance(m.content, str):
                m.content = m.content + self._suffix
        return messages


class _RuntimeError(PreprocessingPlugin):
    async def preprocess(self, messages):
        raise RuntimeError('Error')


class _BadRequestError(PreprocessingPlugin):
    async def preprocess(self, messages):
        raise GatewayBadRequest('Error')


async def test_no_plugins_is_noop():
    messages = [HumanMessage(content='hello')]
    out = await run_preprocessing(messages)
    assert out is messages
    assert out[0].content == 'hello'


async def test_single_plugin_transforms():
    register_preprocessing_plugin(_Upper())
    out = await run_preprocessing([HumanMessage(content='hello')])
    assert out[0].content == 'HELLO'


async def test_chain_runs_in_registration_order():
    register_preprocessing_plugin(_Suffix('-a'))
    register_preprocessing_plugin(_Suffix('-b'))
    out = await run_preprocessing([HumanMessage(content='x')])
    assert out[0].content == 'x-a-b'
    assert len(preprocessing_module._registered) == 2


async def test_failing_plugin_is_fail_closed():
    register_preprocessing_plugin(_RuntimeError())
    with pytest.raises(PreprocessingError):
        await run_preprocessing([HumanMessage(content='hello')])


async def test_chain_stops_after_failure():
    register_preprocessing_plugin(_RuntimeError())
    register_preprocessing_plugin(_Upper())
    messages = [HumanMessage(content='hello')]
    with pytest.raises(PreprocessingError):
        await run_preprocessing(messages)
    # second plugin never ran
    assert messages[0].content == 'hello'


async def test_app_error_propagates_unchanged():
    """A plugin may raise a structured gateway error to control the response."""
    register_preprocessing_plugin(_BadRequestError())
    with pytest.raises(GatewayBadRequest):
        await run_preprocessing([HumanMessage(content='hello')])
