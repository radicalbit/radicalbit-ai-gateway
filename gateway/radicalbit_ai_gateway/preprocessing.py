"""Preprocessing plugins.

A hook that lets plugins transform the incoming chat messages *before* they
reach the input guardrails. Plugins register an implementation at import time
(during ``discover_plugins()``).

Contract:
- A plugin implements :class:`PreprocessingPlugin` and registers an instance via
  :func:`register_preprocessing_plugin`.
- ``preprocess`` takes the messages and returns the same structure
  (``list[BaseMessage]``) so the chain composes.
- Plugins run in registration order. With no plugins registered the chain is a
  no-op and messages pass through unchanged.
- Fail-closed: if a plugin raises, the chain stops and the request is aborted.
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
import logging

from fastapi import status
from langchain_core.messages import BaseMessage
from traceloop.sdk.decorators import task, workflow

from radicalbit_ai_gateway.utils.app_config import get_app_config
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


class PreprocessingPlugin(ABC):
    """Implemented by plugins that want to transform incoming chat messages."""

    @abstractmethod
    async def preprocess(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """Transform *messages* and return the same structure.

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


# Registry of (plugin name, task-wrapped runner). Chain order == registration
# order (i.e. plugin load order).
_PluginRunner = Callable[[list[BaseMessage]], Awaitable[list[BaseMessage]]]
_registered: list[tuple[str, _PluginRunner]] = []


def register_preprocessing_plugin(plugin: PreprocessingPlugin) -> None:
    """Register a preprocessing plugin to join the chain.

    Call from a plugin module at import time. The plugin runs in the order it
    was registered, relative to other preprocessing plugins. Its ``preprocess``
    method is wrapped with a traceloop ``task`` span named ``preprocess.<Plugin>``
    once, here, rather than per request.
    """
    name = type(plugin).__name__

    @task(name=f'preprocess.{name}')
    async def _run(messages: list[BaseMessage]) -> list[BaseMessage]:
        return await plugin.preprocess(messages)

    _registered.append((name, _run))
    logger.info('Registered preprocessing plugin: %s', name)


async def _invoke(
    name: str, run: _PluginRunner, messages: list[BaseMessage]
) -> list[BaseMessage]:
    """Run one plugin's task-wrapped runner with fail-closed error wrapping.

    An ``AppError`` is propagated unchanged so a plugin can control the response;
    any other exception is wrapped in :class:`PreprocessingError`.
    """
    try:
        return await run(messages)
    except AppError:
        # The plugin raised a structured gateway error on purpose; let it through.
        raise
    except Exception as e:
        raise PreprocessingError(
            'A preprocessing step failed.',
            log_message=f'preprocessing plugin {name} failed: {e}',
        ) from e


@workflow(name='run_preprocessing')
async def run_preprocessing(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Run the preprocessing chain over *messages*.

    No-op when no plugins are registered. Fail-closed per plugin via
    :func:`_invoke`.
    """
    for name, run in _registered:
        messages = await _invoke(name, run, messages)
    return messages
