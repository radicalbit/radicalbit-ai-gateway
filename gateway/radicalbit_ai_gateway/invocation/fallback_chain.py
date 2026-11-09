"""One fallback chain for every model call: the target model first, then its
fallbacks, until one answers.

A call is a function of one candidate. It returns a ``Reply`` or raises
``TryNext`` to give the next candidate its turn; any other error does too,
unless the call's context says it is final. A stream falls back only before
its first item: once the client has part of a reply, an error ends it.

The chain records the call (``recorder.py``): the reply's usage when a model
answers, and the last model tried when none did.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
import time
from typing import Any, Generic, NoReturn, TypeVar

from radicalbit_ai_gateway.invocation.recorder import Call, Recorder, Tokens
from radicalbit_ai_gateway.models.model import Model

T = TypeVar('T')


@dataclass(frozen=True)
class Candidate:
    """A model the chain may call, with the client that calls it.

    ``position`` 0 is the target; the others are its fallbacks, in order.
    """

    model: Model
    client: Any
    position: int = 0

    @property
    def is_fallback(self) -> bool:
        return self.position > 0


def candidates(
    target: tuple[Model, Any], fallbacks: list[tuple[Model, Any]] = ()
) -> list[Candidate]:
    """Return the target, then its fallbacks, as candidates."""
    return [
        Candidate(model, client, position)
        for position, (model, client) in enumerate([target, *fallbacks])
    ]


@dataclass(frozen=True)
class Reply(Generic[T]):
    """A candidate's answer, and what it spent (None: nothing to record)."""

    value: T
    usage: Any = None


class TryNext(Exception):  # noqa: N818 — a signal, not an error
    """The candidate gave no answer worth returning: try the next one.

    ``error`` is why. ``last_resort`` is a reply to return when no later
    candidate answers. ``spent`` is True when the call already recorded what
    it spent (a judge's or router's bad answer).
    """

    def __init__(
        self,
        error: BaseException | None = None,
        *,
        last_resort: Reply | None = None,
        spent: bool = False,
    ):
        super().__init__(error)
        self.error = error
        self.last_resort = last_resort
        self.spent = spent


class Skip(Exception):  # noqa: N818 — a signal, not an error
    """The candidate cannot serve this call: it is not tried, and no model
    call is recorded for it. ``error``, when given, says why: it reaches
    ``on_exhausted`` as a failure (an undefined model).
    """

    def __init__(self, error: BaseException | None = None):
        super().__init__(error)
        self.error = error


class Refused(Exception):  # noqa: N818 — a signal, not an error
    """The model refused the request, and any fallback would too: return
    ``value`` as the answer, recorded as a failed call.
    """

    def __init__(self, value: Any):
        super().__init__(value)
        self.value = value


class Spent(Exception):  # noqa: N818 — a signal, not an error
    """The call recorded what it spent, then failed with ``__cause__`` (a
    limit's error): it is raised as is, with no fallback.
    """


@dataclass(frozen=True)
class Failure:
    """A candidate that did not answer, and why."""

    candidate: Candidate
    error: BaseException | None
    last_resort: Reply | None = None


def _raise_last(failures: list[Failure]) -> NoReturn:
    raise failures[-1].error


@dataclass
class Attempt:
    """A candidate's turn in a stream. The stream sets ``usage`` as it goes."""

    candidate: Candidate
    usage: Any = None


@dataclass
class CallContext:
    """What every call of a chain shares.

    ``record`` records a reply's usage (default: the invocation and its
    ``Tokens``), ``record_failure`` a call no model answered (default: the
    last model tried, see ``Recorder.failure``). ``on_failure`` logs a candidate's error before the next one is
    tried. ``final`` tells the errors not worth a fallback: they are raised
    as they are. ``on_exhausted`` turns the failures into the call's result
    when no candidate answered: it raises, or returns a last resort or a
    default.
    """

    call: Call | None
    recorder: Recorder | None
    record: Callable[[Candidate, Any, float], None] | None = None
    record_failure: Callable[[Candidate, float], None] | None = None
    on_failure: Callable[[Candidate, BaseException], None] = lambda c, e: None
    final: Callable[[BaseException], bool] = lambda e: False
    on_exhausted: Callable[[list[Failure]], Any] = field(default=_raise_last)


class FallbackChain:
    def __init__(self, candidates: list[Candidate], context: CallContext):
        self.candidates = candidates
        self.context = context
        self._start = time.monotonic()

    def latency_ms(self) -> float:
        """Milliseconds since the chain started."""
        return (time.monotonic() - self._start) * 1000

    def record(self, candidate: Candidate, usage: Any) -> None:
        """Record what ``candidate`` spent."""
        if self.context.record is not None:
            self.context.record(candidate, usage, self.latency_ms())
            return
        self.context.recorder.invocation(
            self.context.call,
            candidate.model,
            self.latency_ms(),
            tokens=usage or Tokens(),
            fallback_triggered=candidate.is_fallback,
        )

    def _record_failure(self, candidate: Candidate) -> None:
        if self.context.record_failure is not None:
            self.context.record_failure(candidate, self.latency_ms())
            return
        self.context.recorder.failure(
            self.context.call,
            candidate.model,
            self.latency_ms(),
            fallback_triggered=candidate.is_fallback,
        )

    async def call(self, fn: Callable[[Candidate], Awaitable[Reply[T]]]) -> T:
        """Return the value of the first candidate's reply."""
        self._start = time.monotonic()
        failures: list[Failure] = []
        last: Candidate | None = None
        last_spent = False
        for candidate in self.candidates:
            try:
                reply = await fn(candidate)
            except Skip as skip:
                if skip.error is not None:
                    failures.append(Failure(candidate, skip.error))
                continue
            except TryNext as signal:
                last, last_spent = candidate, signal.spent
                failures.append(Failure(candidate, signal.error, signal.last_resort))
                continue
            except Spent as spent:
                raise spent.__cause__ from None
            except Refused as refusal:
                self._record_failure(candidate)
                return refusal.value
            except Exception as error:
                last, last_spent = candidate, False
                if self.context.final(error):
                    self._record_failure(candidate)
                    raise
                self.context.on_failure(candidate, error)
                failures.append(Failure(candidate, error))
                continue
            if reply.usage is not None:
                self.record(candidate, reply.usage)
            return reply.value
        if last is not None and not last_spent:
            self._record_failure(last)
        return self.context.on_exhausted(failures)

    async def stream(
        self, fn: Callable[[Attempt], AsyncIterator[T]]
    ) -> AsyncIterator[T]:
        """Yield the items of the first candidate's stream.

        The last candidate tried is recorded with what its stream spent, when
        the stream ends, fails, or the consumer stops it.
        """
        self._start = time.monotonic()
        failures: list[Failure] = []
        attempt: Attempt | None = None
        try:
            for candidate in self.candidates:
                current = Attempt(candidate)
                started = False
                try:
                    async for item in fn(current):
                        attempt = current
                        started = True
                        yield item
                except Skip as skip:
                    if skip.error is not None:
                        failures.append(Failure(candidate, skip.error))
                    continue
                except TryNext as signal:
                    attempt = current
                    failures.append(Failure(candidate, signal.error))
                    continue
                except Exception as error:
                    attempt = current
                    if started or self.context.final(error):
                        raise
                    self.context.on_failure(candidate, error)
                    failures.append(Failure(candidate, error))
                    continue
                attempt = current
                return
            self.context.on_exhausted(failures)
        finally:
            if attempt is not None:
                self.record(attempt.candidate, attempt.usage)
