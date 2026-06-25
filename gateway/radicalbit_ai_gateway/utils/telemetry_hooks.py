from collections.abc import Callable

from opentelemetry.sdk.trace.export import SpanExporter

_exporter_wrappers: list[Callable[[SpanExporter], SpanExporter]] = []


def register_exporter_wrapper(fn: Callable[[SpanExporter], SpanExporter]) -> None:
    """Register a callable that wraps (and returns) a span exporter."""
    _exporter_wrappers.append(fn)


def get_exporter_wrappers() -> list[Callable[[SpanExporter], SpanExporter]]:
    """Return the registered exporter wrappers, in registration order."""
    return list(_exporter_wrappers)
