"""Preprocessing plugins.

A hook that lets plugins transform the incoming chat messages *before* model
selection and the input guardrails. Plugins register an implementation at import
time (during ``discover_plugins()``).

Contract:
- A plugin implements :class:`PreprocessingPlugin` and registers an instance via
  :func:`register_preprocessing_plugin`.
- ``preprocess`` takes the messages, the plugin's own slice of the route's
  ``plugins`` config and the plugin's own per-request ``context`` (a dict), and
  returns the same structure (``list[BaseMessage]``) so the chain composes.
- ``postprocess`` takes the response text, the same slice and the same
  ``context``, and returns the text sent back to the client. It runs on
  non-streaming chat completions, after output guardrails and after the
  response is cached, in reverse chain order. Default: returns the text as is.
- Plugins receive only the **client's** chat messages. The route's configured
  system prompt is injected *after* preprocessing runs, so it is never passed to
  a plugin and cannot be modified by one.
- Per-route, opt-in: a plugin runs only when its config key is present in the
  route's ``plugins`` and it is enabled there (see
  :meth:`PreprocessingPlugin.is_enabled`). Plugins run in the order their keys
  appear in ``plugins`` (route config order); with none enabled the chain is
  a no-op.
- A plugin validates its own ``plugins`` slice at config-load time by
  overriding :meth:`PreprocessingPlugin.validate`.
- Fail-closed: if a plugin raises, the chain stops and the request is aborted.
- ``context`` lives for one request only: it is never cached, logged or traced.
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
import logging
from typing import Any

from fastapi import status
from langchain_core.messages import BaseMessage
from traceloop.sdk.decorators import task, workflow

from radicalbit_ai_gateway.utils.app_config import get_app_config
from radicalbit_ai_gateway.utils.config_hooks import (
    PluginConfig,
    register_plugin_config_validator,
)
from radicalbit_ai_gateway.utils.exceptions import AppError, GatewayError

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


class PreprocessingError(GatewayError):
    """Raised when a preprocessing plugin fails. Aborts the request (fail-closed).

    Subclasses ``GatewayError`` so it is handled by the registered
    ``gateway_exception_handler`` and returned as a structured JSON error.
    """

    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            log_message=log_message,
            code='preprocessing_error',
        )


class PostprocessingError(GatewayError):
    """Raised when a postprocessing plugin fails. Aborts the response (fail-closed)."""

    def __init__(self, message: str, *, log_message: str | None = None):
        super().__init__(
            message,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            log_message=log_message,
            code='postprocessing_error',
        )


class PreprocessingConfig(PluginConfig):
    """Base schema for a preprocessing plugin's ``plugins`` slice.

    Inherits ``extra='forbid'`` from :class:`PluginConfig` (a route may only
    set the parameters a plugin declares) and adds the opt-in ``enabled`` flag.
    Subclass to add plugin-specific fields::

        class MyConfig(PreprocessingConfig):
            threshold: int = 5
    """

    enabled: bool = False


class PreprocessingPlugin(ABC):
    """Implemented by plugins that want to transform incoming chat messages."""

    #: Optional schema for this plugin's ``plugins`` slice. When set, the
    #: default :meth:`validate` checks the slice against it, rejecting unknown
    #: keys and invalid types. Subclass :class:`PreprocessingConfig`.
    config_schema: type[PreprocessingConfig] | None = None

    def is_enabled(self, config: dict | None) -> bool:
        """Whether this plugin runs for a route, given its config slice.

        Default: opt-in — runs only when the slice has a truthy ``enabled``
        flag. Override for custom gating.
        """
        return isinstance(config, dict) and bool(config.get('enabled', False))

    def validate(self, config: dict) -> None:
        """Validate this plugin's own ``plugins`` slice at config-load time.

        Called once per route that declares a slice for this plugin (its config
        key is present), via the plugins validator registered in
        :func:`register_preprocessing_plugin`. Raise ``ValueError`` on invalid
        config to fail config validation.

        Default: validate against :attr:`config_schema` if set (which rejects
        unknown keys); otherwise a no-op. Override for custom validation.
        """
        if self.config_schema is not None:
            self.config_schema.model_validate(config)

    @abstractmethod
    async def preprocess(
        self,
        messages: list[BaseMessage],
        config: dict | None,
        context: dict[str, Any],
    ) -> list[BaseMessage]:
        """Transform *messages* and return the same structure.

        *messages* are the client's chat messages only; the route's configured
        system prompt is injected after preprocessing and is never present here.

        *config* is this plugin's slice of the route's ``plugins`` config
        (the value under this plugin's key); ``None`` when the route declares
        no slice for it. Read route-specific settings from it as needed.

        *context* is this plugin's own state for this request: what it stores
        here is handed back to :meth:`postprocess` for the same request.

        Each message's ``content`` can take two shapes, and an implementation
        that edits text should handle both:

        - ``str`` — plain text content. Operate on it directly.
        - ``list`` — multimodal content, i.e. a list of parts (dicts). Only the
          text parts carry text: iterate the list and act on parts where
          ``part.get('type') == 'text'`` (the text is in ``part['text']``).
          Leave non-text parts (e.g. ``image_url``) untouched.

        Template for a text-transforming plugin (replace ``transform`` with
        your own logic)::

            for message in messages:
                content = message.content
                if isinstance(content, str):
                    message.content = transform(content)
                elif isinstance(content, list):
                    for part in content:
                        if (
                            isinstance(part, dict)
                            and part.get('type') == 'text'
                            and isinstance(part.get('text'), str)
                        ):
                            part['text'] = transform(part['text'])
            return messages
        """
        ...

    async def postprocess(
        self, content: str, config: dict | None, context: dict[str, Any]
    ) -> str:
        """Transform the response text sent back to the client.

        *config* and *context* are the same that :meth:`preprocess` received for
        this request. Default: returns *content* unchanged.
        """
        return content


def _config_key(plugin: PreprocessingPlugin) -> str:
    """Resolve a plugin's ``plugins`` config key: its top-level package name,
    which equals the entry-point name used in ``ENABLED_PLUGINS`` (e.g. a plugin
    in package ``uppercase_preprocessor`` keys on ``uppercase_preprocessor``).
    """
    return type(plugin).__module__.partition('.')[0]


# Registry of config key -> (plugin, task-wrapped runner). The executed chain is
# NOT registry order: per request it follows the route's ``plugins`` key order
# (see ``_enabled_chain``). Last registration per key wins.
_PluginRunner = Callable[
    [list[BaseMessage], dict | None, dict[str, Any]], Awaitable[list[BaseMessage]]
]
_PostRunner = Callable[[str, dict | None, dict[str, Any]], Awaitable[str]]
_registered: dict[str, tuple[PreprocessingPlugin, _PluginRunner, _PostRunner]] = {}


def register_preprocessing_plugin(
    plugin: PreprocessingPlugin, name: str | None = None
) -> None:
    """Register a preprocessing plugin to join the chain.

    Call from a plugin module at import time. Plugins run in the order their
    keys appear in the route's ``plugins`` config (route config order), not in
    registration order; see :func:`_enabled_chain`. Its ``preprocess``
    method is wrapped with a traceloop ``task`` span named ``preprocess.<key>``
    once, here, rather than per request.

    The plugin's ``plugins`` config key defaults to its package name (see
    :func:`_config_key`); pass *name* to override it (e.g. in tests where several
    plugin classes share one module).
    """
    key = name or _config_key(plugin)

    @task(name=f'preprocess.{key}')
    async def _run(
        messages: list[BaseMessage], config: dict | None, context: dict[str, Any]
    ) -> list[BaseMessage]:
        return await plugin.preprocess(messages, config, context)

    @task(name=f'postprocess.{key}')
    async def _run_post(
        content: str, config: dict | None, context: dict[str, Any]
    ) -> str:
        return await plugin.postprocess(content, config, context)

    register_plugin_config_validator(key, plugin.validate)
    _registered[key] = (plugin, _run, _run_post)
    logger.info('Registered preprocessing plugin: %s', key)


async def _invoke(
    key: str,
    run: _PluginRunner,
    messages: list[BaseMessage],
    config: dict | None,
    context: dict[str, Any],
) -> list[BaseMessage]:
    """Run one plugin's task-wrapped runner with fail-closed error wrapping.

    An ``AppError`` is propagated unchanged so a plugin can control the response;
    any other exception is wrapped in :class:`PreprocessingError`.
    """
    try:
        return await run(messages, config, context)
    except AppError:
        # The plugin raised a structured gateway error on purpose; let it through.
        raise
    except Exception as e:
        raise PreprocessingError(
            'A preprocessing step failed.',
            log_message=f'preprocessing plugin {key} failed: {e}',
        ) from e


def _enabled_chain(
    plugins: dict | None,
) -> list[tuple[str, _PluginRunner, _PostRunner, dict | None]]:
    """Resolve the ordered ``(key, runner, config)`` chain for *plugins*.

    A plugin is included only when its config key is present in *plugins* and
    :meth:`PreprocessingPlugin.is_enabled` returns True for its slice. The order
    follows the keys' order in *plugins* (the route's config order). Plugins
    keys that are not registered preprocessing plugins are ignored.
    """
    by_key = plugins if isinstance(plugins, dict) else {}
    chain: list[tuple[str, _PluginRunner, _PostRunner, dict | None]] = []
    for key, config in by_key.items():
        entry = _registered.get(key)
        if entry is None:
            continue
        plugin, run, run_post = entry
        if plugin.is_enabled(config):
            chain.append((key, run, run_post, config))
    return chain


@workflow(name='run_preprocessing')
async def _run_chain(
    messages: list[BaseMessage],
    chain: list[tuple[str, _PluginRunner, _PostRunner, dict | None]],
    context: dict[str, dict[str, Any]],
) -> list[BaseMessage]:
    """Run a resolved preprocessing *chain*, fail-closed per plugin."""
    for key, run, _, config in chain:
        messages = await _invoke(
            key, run, messages, config, context.setdefault(key, {})
        )
    return messages


async def run_preprocessing(
    messages: list[BaseMessage],
    plugins: dict | None = None,
    context: dict[str, dict[str, Any]] | None = None,
) -> list[BaseMessage]:
    """Run the preprocessing chain over *messages* for a route's *plugins*.

    Each plugin's slice is passed to ``preprocess``; plugins run in the route's
    config order (see :func:`_enabled_chain`). When no plugin is enabled this is
    a no-op that returns *messages* unchanged **without** opening a workflow
    span; otherwise the chain runs inside the ``run_preprocessing`` workflow.

    *context* is the request's plugin state, keyed by plugin: pass the same dict
    to :func:`run_postprocessing` for this request.
    """
    chain = _enabled_chain(plugins)
    if not chain:
        return messages
    return await _run_chain(messages, chain, {} if context is None else context)


@workflow(name='run_postprocessing')
async def _run_post_chain(
    content: str,
    chain: list[tuple[str, _PluginRunner, _PostRunner, dict | None]],
    context: dict[str, dict[str, Any]],
) -> str:
    """Run a resolved chain's ``postprocess`` in reverse order, fail-closed."""
    for key, _, run_post, config in reversed(chain):
        try:
            content = await run_post(content, config, context.setdefault(key, {}))
        except AppError:
            raise
        except Exception as e:
            raise PostprocessingError(
                'A postprocessing step failed.',
                log_message=f'postprocessing plugin {key} failed: {e}',
            ) from e
    return content


async def run_postprocessing(
    content: str,
    plugins: dict | None,
    context: dict[str, dict[str, Any]],
) -> str:
    """Run ``postprocess`` of the route's enabled plugins over the response text.

    Plugins run in reverse config order, so the first to touch the request is the
    last to touch the response. No-op without a workflow span when no plugin is
    enabled.
    """
    chain = _enabled_chain(plugins)
    if not chain:
        return content
    return await _run_post_chain(content, chain, context)
