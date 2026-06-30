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
    """Each test starts with empty preprocessing and plugins-validator registries.

    Registering a plugin also registers an plugins validator, so both globals
    must be reset between tests.
    """
    preprocessing_module._registered.clear()
    config_hooks._plugins_validators.clear()
    config_hooks._known_plugin_keys.clear()
    yield
    preprocessing_module._registered.clear()
    config_hooks._plugins_validators.clear()
    config_hooks._known_plugin_keys.clear()


def _config(plugins):
    """Build a GatewayConfig as in production (plugins validated at load)."""
    return GatewayConfig(
        chat_models=[{'model_id': 'm', 'model': 'openai/gpt-4o'}],
        routes={'r': {'chat_models': ['m'], 'plugins': plugins}},
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
    """Plugins that enables *key* with optional plugin-specific settings."""
    return {key: {'enabled': True, **extra}}


def test_config_key_is_top_level_package():
    # Derives the plugin's top-level package name (== its entry-point name in
    # ENABLED_PLUGINS), not the class name.
    expected = Upper.__module__.partition('.')[0]
    assert _config_key(Upper()) == expected
    assert _config_key(BadRequest()) == expected


async def test_no_plugins_is_noop():
    messages = [HumanMessage(content='hello')]
    out = await run_preprocessing(messages)
    assert out is messages
    assert out[0].content == 'hello'


async def test_enabled_plugin_transforms():
    register_preprocessing_plugin(Upper(), name='upper')
    out = await run_preprocessing([HumanMessage(content='hello')], _on('upper'))
    assert out[0].content == 'HELLO'


async def test_skipped_when_extension_is_none():
    register_preprocessing_plugin(Upper(), name='upper')
    out = await run_preprocessing([HumanMessage(content='hello')], None)
    assert out[0].content == 'hello'


async def test_skipped_when_key_missing():
    register_preprocessing_plugin(Upper(), name='upper')
    out = await run_preprocessing(
        [HumanMessage(content='hello')], {'other_plugin': {'enabled': True}}
    )
    assert out[0].content == 'hello'


async def test_skipped_when_enabled_false():
    register_preprocessing_plugin(Upper(), name='upper')
    out = await run_preprocessing(
        [HumanMessage(content='hello')], {'upper': {'enabled': False}}
    )
    assert out[0].content == 'hello'


async def test_plugin_reads_route_specific_config():
    register_preprocessing_plugin(Suffix(), name='suffix')
    out = await run_preprocessing(
        [HumanMessage(content='x')], _on('suffix', suffix='-done')
    )
    assert out[0].content == 'x-done'


async def test_enabled_subset_runs():
    register_preprocessing_plugin(Suffix(), name='suffix')
    register_preprocessing_plugin(Upper(), name='upper')
    # Only suffix enabled: upper is skipped (its key absent from plugins).
    out = await run_preprocessing(
        [HumanMessage(content='x')], _on('suffix', suffix='-a')
    )
    assert out[0].content == 'x-a'


async def test_runs_in_extension_key_order():
    # Registration order is suffix, upper — but plugins lists upper first.
    register_preprocessing_plugin(Suffix(), name='suffix')
    register_preprocessing_plugin(Upper(), name='upper')
    plugins = {**_on('upper'), **_on('suffix', suffix='-z')}
    out = await run_preprocessing([HumanMessage(content='ab')], plugins)
    # upper ran first, then suffix: 'AB' -> 'AB-z'
    assert out[0].content == 'AB-z'

    # Reversed plugins order -> reversed chain: 'ab-z' -> 'AB-Z'
    plugins = {**_on('suffix', suffix='-z'), **_on('upper')}
    out = await run_preprocessing([HumanMessage(content='ab')], plugins)
    assert out[0].content == 'AB-Z'


async def test_is_enabled_override_runs_without_flag():
    # Key present but no explicit ``enabled`` flag: default would skip, the
    # override opts in.
    register_preprocessing_plugin(AlwaysOn(), name='always_on')
    out = await run_preprocessing([HumanMessage(content='hello')], {'always_on': {}})
    assert out[0].content == 'hello!'


async def test_override_does_not_run_when_key_absent():
    register_preprocessing_plugin(AlwaysOn(), name='always_on')
    out = await run_preprocessing([HumanMessage(content='hello')], None)
    assert out[0].content == 'hello'


async def test_failing_plugin_is_fail_closed():
    register_preprocessing_plugin(Boom(), name='boom')
    with pytest.raises(PreprocessingError):
        await run_preprocessing([HumanMessage(content='hello')], _on('boom'))


async def test_chain_stops_after_failure():
    register_preprocessing_plugin(Boom(), name='boom')
    register_preprocessing_plugin(Upper(), name='upper')
    messages = [HumanMessage(content='hello')]
    plugins = {**_on('boom'), **_on('upper')}
    with pytest.raises(PreprocessingError):
        await run_preprocessing(messages, plugins)
    # second plugin never ran
    assert messages[0].content == 'hello'


async def test_app_error_propagates_unchanged():
    """A plugin may raise a structured gateway error to control the response."""
    register_preprocessing_plugin(BadRequest(), name='bad_request')
    with pytest.raises(GatewayBadRequest):
        await run_preprocessing([HumanMessage(content='hello')], _on('bad_request'))


def test_plugin_validates_its_slice():
    register_preprocessing_plugin(Validating(), name='validating')
    with pytest.raises(Exception, match='threshold required'):
        _config(_on('validating'))


def test_plugin_validate_passes_on_valid_slice():
    register_preprocessing_plugin(Validating(), name='validating')
    _config(_on('validating', threshold=1))


def test_validate_not_called_when_slice_absent():
    register_preprocessing_plugin(Validating(), name='validating')
    register_preprocessing_plugin(Upper(), name='other')
    # 'validating' slice absent (only the other, claimed key is present) and no
    # plugins at all: its validate must not run (it would raise).
    _config({'other': {'enabled': True}})
    _config(None)


def test_schema_rejects_unknown_key():
    register_preprocessing_plugin(SchemaPlugin(), name='schema_plugin')
    with pytest.raises(Exception, match='Extra inputs are not permitted'):
        _config({'schema_plugin': {'enabled': True, 'bogus': 1}})


def test_schema_accepts_declared_keys():
    register_preprocessing_plugin(SchemaPlugin(), name='schema_plugin')
    _config({'schema_plugin': {'enabled': True, 'threshold': 9}})
