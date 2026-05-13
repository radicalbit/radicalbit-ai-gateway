"""Lightweight wrapper that overrides ``parent`` on a ReadableSpan."""

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanContext


class _RemappedSpan:
    """Delegates all attributes to the original span except ``parent``,
    which is overridden for re-parenting.
    """

    __slots__ = ('_span', '_parent')

    def __init__(self, span: ReadableSpan, parent: SpanContext | None):
        object.__setattr__(self, '_span', span)
        object.__setattr__(self, '_parent', parent)

    def __getattr__(self, name: str):
        return getattr(self._span, name)

    @property
    def parent(self) -> SpanContext | None:
        return self._parent
