"""Core filtering exporter that suppresses noisy LangChain internal spans.

LangChain runnables (RunnableSequence, RunnableParallel, etc.) emit deeply
nested internal spans that clutter traces without adding observability value.
This module filters them out by name prefix and re-parents orphaned children
to their nearest surviving ancestor using a path-compressed remap dictionary.

CLIENT spans (LLM/model calls) are never suppressed so actual model
invocations are always visible in traces.
"""

from cachetools import FIFOCache
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import SpanContext, SpanKind

from radicalbit_ai_gateway.utils.filtering_exporter.remapped_span import _RemappedSpan

_SUPPRESSED_PREFIXES = (
    'RunnableSequence',
    'RunnableParallel',
    'RunnableLambda',
    'RunnableAssign',
    'RunnableWithFallbacks',
    'PromptTemplate',
)

_REMAP_CACHE_SIZE = 100_000


def _should_suppress(span: ReadableSpan) -> bool:
    """Return True for spans that should be suppressed.

    CLIENT spans (LLM/model calls) are never suppressed regardless of name.
    """
    if span.kind == SpanKind.CLIENT:
        return False
    return any(span.name.startswith(p) for p in _SUPPRESSED_PREFIXES)


class FilteringExporter(SpanExporter):
    """Wraps an inner exporter, dropping spans whose names match suppressed
    prefixes and re-parenting orphaned children to their nearest surviving
    ancestor.

    The remap dictionary maps suppressed span IDs to their nearest surviving
    ancestor's span ID (or None if the chain reaches the root).  Path
    compression keeps lookups O(1) amortised.
    """

    def __init__(self, wrapped: SpanExporter):
        self._wrapped = wrapped
        self._remap: dict[int, int] = FIFOCache(maxsize=_REMAP_CACHE_SIZE)

    # ------------------------------------------------------------------
    # Phase helpers — each handles one step of the export pipeline
    # ------------------------------------------------------------------

    def _register_suppressed(self, spans) -> set[int]:
        """Identify spans to suppress and record raw parent mappings.

        For each suppressed span, store ``{suppressed_id → raw_parent_id}``
        in the remap dict.  Returns the set of span IDs suppressed in this
        batch.

        Args:
            spans: Batch of spans from the SDK.

        Returns:
            Set of span IDs that were suppressed.

        """
        suppressed: set[int] = set()
        for s in spans:
            sid = s.context.span_id
            pid = s.parent.span_id if s.parent else None

            if _should_suppress(s):
                suppressed.add(sid)
                if pid is not None:
                    self._remap[sid] = pid
        return suppressed

    def _compress_remap_chains(self, suppressed_in_batch: set[int]) -> None:
        """Apply path compression to remap entries for newly-suppressed spans.

        For each suppressed span, walk the remap chain to find the nearest
        surviving (non-suppressed) ancestor.  Every intermediate node on the
        path is updated to point directly to that ancestor — a union-find-
        style compression that keeps future lookups O(1) instead of
        O(chain-length).

        Only spans suppressed in this batch need re-resolution; previously
        compressed entries already point to a surviving span or None.
        """
        for sid in suppressed_in_batch:
            current = self._remap.get(sid)
            if current is None:
                continue
            path: list[int] = []
            while current is not None and (
                current in suppressed_in_batch or current in self._remap
            ):
                if current in path:
                    # Cycle detected — break to prevent infinite loop.
                    current = None
                    break
                path.append(current)
                current = self._remap.get(current)
            # Point this span and every intermediate directly at the ancestor.
            self._remap[sid] = current
            for intermediate in path:
                self._remap[intermediate] = current

    def _reparent_span(self, span: ReadableSpan) -> ReadableSpan | _RemappedSpan:
        """Return the span unchanged or wrapped with a corrected parent.

        If the span's parent was suppressed, follow the remap chain to find
        the nearest surviving ancestor and return a ``_RemappedSpan`` with
        the corrected parent context.  Otherwise return the original span.
        """
        pid = span.parent.span_id if span.parent else None
        if pid is None or pid not in self._remap:
            return span

        # Walk the remap chain to the surviving ancestor.
        new_pid = pid
        visited: set[int] = set()
        while new_pid is not None and new_pid in self._remap:
            if new_pid in visited:
                # Cycle detected — reparent to root.
                new_pid = None
                break
            visited.add(new_pid)
            new_pid = self._remap[new_pid]

        if new_pid is not None:
            new_parent = SpanContext(
                trace_id=span.parent.trace_id,
                span_id=new_pid,
                is_remote=span.parent.is_remote,
                trace_flags=span.parent.trace_flags,
            )
            return _RemappedSpan(span, new_parent)
        return _RemappedSpan(span, None)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export(self, spans) -> SpanExportResult:
        # 1. Identify suppressed spans and record parent mappings.
        suppressed = self._register_suppressed(spans)

        # 2. Compress remap chains so every entry points to a surviving
        #    ancestor (or None) in O(1).
        self._compress_remap_chains(suppressed)

        # 3. Keep surviving spans, re-parenting those whose parent was
        #    suppressed.
        result = [
            self._reparent_span(s) for s in spans if s.context.span_id not in suppressed
        ]

        if result:
            return self._wrapped.export(result)
        return SpanExportResult.SUCCESS

    def shutdown(self):
        self._wrapped.shutdown()

    def force_flush(self, timeout_millis: int = 0):
        return self._wrapped.force_flush(timeout_millis)
