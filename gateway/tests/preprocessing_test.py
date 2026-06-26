from langchain_core.messages import HumanMessage
import pytest

from radicalbit_ai_gateway.models.gateway_config import GatewayConfig
import radicalbit_ai_gateway.preprocessing as preprocessing_module
from radicalbit_ai_gateway.preprocessing import (
    PreprocessingConfig,
    PreprocessingError,
    PreprocessingPlugin,
    _config_key,
    register_preprocessing_plugin,
    run_preprocessing,
)
from radicalbit_ai_gateway.utils import config_hooks
from radicalbit_ai_gateway.utils.exceptions import GatewayBadRequest


@pytest.fixture(autouse=True)
def _clear_registry():
    """Each test starts with empty preprocessing and extension-validator registries.

    Registering a plugin also registers an extension validator, so both globals
    must be reset between tests.
    """
    preprocessing_module._registered.clear()
    config_hooks._extension_validators.clear()
    yield
    preprocessing_module._registered.clear()
    config_hooks._extension_validators.clear()


def _config(extension):
    """Build a GatewayConfig as in production (extension validated at load)."""
    return GatewayConfig(
        chat_models=[{'model_id': 'm', 'model': 'openai/gpt-4o'}],
        routes={'r': {'chat_models': ['m'], 'extension': extension}},
    )


class Upper(PreprocessingPlugin):
    async def preprocess(self, messages, config):
        for m in messages:
            if isinstance(m.content, str):
                m.content = m.content.upper()
        return messages


class Suffix(PreprocessingPlugin):
    async def preprocess(self, messages, config):
        suffix = (config or {}).get('suffix', '')
        for m in messages:
            if isinstance(m.content, str):
                m.content = m.content + suffix
        return messages


class AlwaysOn(PreprocessingPlugin):
    """Overrides gating to run regardless of the ``enabled`` flag."""

    def is_enabled(self, config):
        return True

    async def preprocess(self, messages, config):
        for m in messages:
            if isinstance(m.content, str):
                m.content = m.content + '!'
        return messages


class Validating(PreprocessingPlugin):
    """Validates its own slice: requires a ``threshold`` key."""

    def validate(self, config):
        if 'threshold' not in config:
            raise ValueError('threshold required')

    async def preprocess(self, messages, config):
        return messages


class SchemaConfig(PreprocessingConfig):
    threshold: int = 5


class SchemaPlugin(PreprocessingPlugin):
    """Uses a declared schema: only ``enabled`` and ``threshold`` allowed."""

    config_schema = SchemaConfig

    async def preprocess(self, messages, config):
        return messages


class Boom(PreprocessingPlugin):
    async def preprocess(self, messages, config):
        raise RuntimeError('Error')


class BadRequest(PreprocessingPlugin):
    async def preprocess(self, messages, config):
        raise GatewayBadRequest('Error')


def _on(key: str, **extra) -> dict:
    """Extension that enables *key* with optional plugin-specific settings."""
    return {key: {'enabled': True, **extra}}


def test_config_key_derives_snake_case():
    assert _config_key(Upper()) == 'upper'
    assert _config_key(BadRequest()) == 'bad_request'


async def test_no_plugins_is_noop():
    messages = [HumanMessage(content='hello')]
    out = await run_preprocessing(messages)
    assert out is messages
    assert out[0].content == 'hello'


async def test_enabled_plugin_transforms():
    register_preprocessing_plugin(Upper())
    out = await run_preprocessing([HumanMessage(content='hello')], _on('upper'))
    assert out[0].content == 'HELLO'


async def test_skipped_when_extension_is_none():
    register_preprocessing_plugin(Upper())
    out = await run_preprocessing([HumanMessage(content='hello')], None)
    assert out[0].content == 'hello'


async def test_skipped_when_key_missing():
    register_preprocessing_plugin(Upper())
    out = await run_preprocessing(
        [HumanMessage(content='hello')], {'other_plugin': {'enabled': True}}
    )
    assert out[0].content == 'hello'


async def test_skipped_when_enabled_false():
    register_preprocessing_plugin(Upper())
    out = await run_preprocessing(
        [HumanMessage(content='hello')], {'upper': {'enabled': False}}
    )
    assert out[0].content == 'hello'


async def test_plugin_reads_route_specific_config():
    register_preprocessing_plugin(Suffix())
    out = await run_preprocessing(
        [HumanMessage(content='x')], _on('suffix', suffix='-done')
    )
    assert out[0].content == 'x-done'


async def test_enabled_subset_runs():
    register_preprocessing_plugin(Suffix())
    register_preprocessing_plugin(Upper())
    # Only suffix enabled: upper is skipped (its key absent from extension).
    out = await run_preprocessing(
        [HumanMessage(content='x')], _on('suffix', suffix='-a')
    )
    assert out[0].content == 'x-a'


async def test_runs_in_extension_key_order():
    # Registration order is suffix, upper — but extension lists upper first.
    register_preprocessing_plugin(Suffix())
    register_preprocessing_plugin(Upper())
    extension = {**_on('upper'), **_on('suffix', suffix='-z')}
    out = await run_preprocessing([HumanMessage(content='ab')], extension)
    # upper ran first, then suffix: 'AB' -> 'AB-z'
    assert out[0].content == 'AB-z'

    # Reversed extension order -> reversed chain: 'ab-z' -> 'AB-Z'
    extension = {**_on('suffix', suffix='-z'), **_on('upper')}
    out = await run_preprocessing([HumanMessage(content='ab')], extension)
    assert out[0].content == 'AB-Z'


async def test_is_enabled_override_runs_without_flag():
    # Key present but no explicit ``enabled`` flag: default would skip, the
    # override opts in.
    register_preprocessing_plugin(AlwaysOn())
    out = await run_preprocessing([HumanMessage(content='hello')], {'always_on': {}})
    assert out[0].content == 'hello!'


async def test_override_does_not_run_when_key_absent():
    register_preprocessing_plugin(AlwaysOn())
    out = await run_preprocessing([HumanMessage(content='hello')], None)
    assert out[0].content == 'hello'


async def test_failing_plugin_is_fail_closed():
    register_preprocessing_plugin(Boom())
    with pytest.raises(PreprocessingError):
        await run_preprocessing([HumanMessage(content='hello')], _on('boom'))


async def test_chain_stops_after_failure():
    register_preprocessing_plugin(Boom())
    register_preprocessing_plugin(Upper())
    messages = [HumanMessage(content='hello')]
    extension = {**_on('boom'), **_on('upper')}
    with pytest.raises(PreprocessingError):
        await run_preprocessing(messages, extension)
    # second plugin never ran
    assert messages[0].content == 'hello'


async def test_app_error_propagates_unchanged():
    """A plugin may raise a structured gateway error to control the response."""
    register_preprocessing_plugin(BadRequest())
    with pytest.raises(GatewayBadRequest):
        await run_preprocessing([HumanMessage(content='hello')], _on('bad_request'))


def test_plugin_validates_its_slice():
    register_preprocessing_plugin(Validating())
    with pytest.raises(Exception, match='threshold required'):
        _config(_on('validating'))


def test_plugin_validate_passes_on_valid_slice():
    register_preprocessing_plugin(Validating())
    _config(_on('validating', threshold=1))


def test_validate_not_called_when_slice_absent():
    register_preprocessing_plugin(Validating())
    # No 'validating' key and no extension at all: validate must not run.
    _config({'other': {'enabled': True}})
    _config(None)


def test_schema_rejects_unknown_key():
    register_preprocessing_plugin(SchemaPlugin())
    with pytest.raises(Exception, match='Extra inputs are not permitted'):
        _config({'schema_plugin': {'enabled': True, 'bogus': 1}})


def test_schema_accepts_declared_keys():
    register_preprocessing_plugin(SchemaPlugin())
    _config({'schema_plugin': {'enabled': True, 'threshold': 9}})
