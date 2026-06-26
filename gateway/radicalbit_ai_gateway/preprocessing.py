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
from dataclasses import dataclass
import logging

from fastapi import status
from langchain_core.messages import BaseMessage
from traceloop.sdk.decorators import task, workflow

from radicalbit_ai_gateway.utils.exceptions import AppError, GatewayError

logger = logging.getLogger('radicalbit_ai_gateway')


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


@dataclass
class _Entry:
    """A registered plugin plus its task-wrapped runner.

    ``runner`` is decorated with :func:`task` once at registration (using a
    per-plugin span name) so the wrapper is built at startup, not per request.
    """

    name: str
    plugin: PreprocessingPlugin
    runner: Callable[[list[BaseMessage]], Awaitable[list[BaseMessage]]]


# Registry. Chain order == registration order (i.e. plugin load order).
_registered: list[_Entry] = []


def register_preprocessing_plugin(plugin: PreprocessingPlugin) -> None:
    """Register a preprocessing plugin to join the chain.

    Call from a plugin module at import time. The plugin runs in the order it
    was registered, relative to other preprocessing plugins. Its ``preprocess``
    method is wrapped with a traceloop ``task`` span named ``preprocess.<Plugin>``
    once, here, rather than per request.
    """
    name = type(plugin).__name__
    span_name = f'preprocess.{name}'

    @task(name=span_name)
    async def _run(messages: list[BaseMessage]) -> list[BaseMessage]:
        return await plugin.preprocess(messages)

    _registered.append(_Entry(name=name, plugin=plugin, runner=_run))
    logger.info('Registered preprocessing plugin: %s', name)


def get_preprocessing_plugins() -> list[PreprocessingPlugin]:
    """Return the registered preprocessing plugins, in chain order."""
    return [entry.plugin for entry in _registered]


async def _invoke_entry(
    entry: _Entry, messages: list[BaseMessage]
) -> list[BaseMessage]:
    """Run one plugin's task-wrapped runner with fail-closed error wrapping.

    An ``AppError`` is propagated unchanged so a plugin can control the response;
    any other exception is wrapped in :class:`PreprocessingError`.
    """
    try:
        return await entry.runner(messages)
    except AppError:
        # The plugin raised a structured gateway error on purpose; let it through.
        raise
    except Exception as e:
        raise PreprocessingError(
            'A preprocessing step failed.',
            log_message=f'preprocessing plugin {entry.name} failed: {e}',
        ) from e


@workflow(name='run_preprocessing')
async def run_preprocessing(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Run the preprocessing chain over *messages*.

    No-op when no plugins are registered. Fail-closed per plugin via
    :func:`_invoke_entry`.
    """
    current = messages
    for entry in _registered:
        current = await _invoke_entry(entry, current)
    return current
