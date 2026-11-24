"""One fallback chain for every model call: the target model first, then its
fallbacks, until one answers.

A call is a function of one candidate. It returns a ``Reply`` (a ``Refused``
one when no fallback would answer better) or raises ``TryNext`` to give the
next candidate its turn; any other error does too,
unless the call's context says it is final. A stream falls back only before
its first item: once the client has part of a reply, an error ends it.

The chain records the call (``recorder.py``): the reply's usage when a model
answers, and the last model tried when none did.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from functools import partial
import time
from typing import Any, Generic, NoReturn

from typing_extensions import Never, TypeVar

from radicalbit_ai_gateway.invocation.recorder import Call, Recorder, Tokens
from radicalbit_ai_gateway.models.model import Model

T = TypeVar('T')
# What ``on_exhausted`` returns: Never when it raises.
R = TypeVar('R', default=Never)
# The client a candidate calls its model with.
C = TypeVar('C', default=object)
# The same, for a frozen candidate: one with a narrower client is one too.
C_co = TypeVar('C_co', covariant=True, default=object)


@dataclass(frozen=True)
class Candidate(Generic[C_co]):
    """A model the chain may call, with the client that calls it.

    ``position`` 0 is the target; the others are its fallbacks, in order.
    """

    model: Model
    client: C_co
    position: int = 0

    @property
    def is_fallback(self) -> bool:
        return self.position > 0


def candidates(
    target: tuple[Model, C], fallbacks: Sequence[tuple[Model, C]] = ()
) -> list[Candidate[C]]:
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
        last_resort: Reply[Any] | None = None,
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


@dataclass(frozen=True)
class Refused(Reply[T]):
    """The model refused the request, and any fallback would too: ``value``
    is the answer, recorded as a failed call.
    """


class Spent(Exception):  # noqa: N818 — a signal, not an error
    """The call recorded what it spent, then failed with ``__cause__`` (a
    limit's error): it is raised as is, with no fallback.
    """


class NoAnswerError(Exception):
    """No candidate answered, and the last one tried gave no error saying why."""


@dataclass(frozen=True)
class Failure:
    """A candidate that did not answer, and why."""

    candidate: Candidate
    error: BaseException | None
    last_resort: Reply[Any] | None = None


def _raise_last(failures: list[Failure]) -> NoReturn:
    error = failures[-1].error if failures else None
    if error is None:
        raise NoAnswerError('No model answered the call')
    raise error


def _not_recordable(*_: object) -> None:
    raise RuntimeError(
        'The call has no recorder: give its CallContext a recorder and a call, '
        'or its own record and record_failure'
    )


def _record_invocation(
    recorder: Recorder, call: Call, candidate: Candidate, usage: Any, latency_ms: float
) -> None:
    recorder.invocation(
        call,
        candidate.model,
        latency_ms,
        tokens=usage or Tokens(),
        fallback_triggered=candidate.is_fallback,
    )


def _record_failure(
    recorder: Recorder, call: Call, candidate: Candidate, latency_ms: float
) -> None:
    recorder.failure(
        call, candidate.model, latency_ms, fallback_triggered=candidate.is_fallback
    )


@dataclass
class Attempt(Generic[C]):
    """A candidate's turn in a stream. The stream sets ``usage`` as it goes."""

    candidate: Candidate[C]
    usage: Any = None


@dataclass
class CallContext(Generic[R]):
    """What every call of a chain shares.

    ``record`` records a reply's usage (default: the invocation and its
    ``Tokens``), ``record_failure`` a call no model answered (default: the
    last model tried, see ``Recorder.failure``). The defaults record through
    ``recorder`` for ``call``; a context with neither has nothing to record
    with, and fails when asked to. ``on_failure`` logs a candidate's error before the next one is
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
    on_exhausted: Callable[[list[Failure]], R] = field(default=_raise_last)
    # ``record`` and ``record_failure``, or their defaults.
    record_reply: Callable[[Candidate, Any, float], None] = field(init=False)
    record_no_answer: Callable[[Candidate, float], None] = field(init=False)

    def __post_init__(self) -> None:
        """Resolve ``record_reply`` and ``record_no_answer``."""
        call, recorder = self.call, self.recorder
        if call is not None and recorder is not None:
            self.record_reply = self.record or partial(
                _record_invocation, recorder, call
            )
            self.record_no_answer = self.record_failure or partial(
                _record_failure, recorder, call
            )
        else:
            self.record_reply = self.record or _not_recordable
            self.record_no_answer = self.record_failure or _not_recordable


class FallbackChain(Generic[R, C]):
    def __init__(self, candidates: list[Candidate[C]], context: CallContext[R]):
        self.candidates = candidates
        self.context = context
        self._start = time.monotonic()

    def latency_ms(self) -> float:
        """Milliseconds since the chain started."""
        return (time.monotonic() - self._start) * 1000

    def record(self, candidate: Candidate, usage: Any) -> None:
        """Record what ``candidate`` spent."""
        self.context.record_reply(candidate, usage, self.latency_ms())

    def _record_failure(self, candidate: Candidate) -> None:
        self.context.record_no_answer(candidate, self.latency_ms())

    async def call(self, fn: Callable[[Candidate[C]], Awaitable[Reply[T]]]) -> T | R:
        """Return the value of the first candidate's reply."""
        self._start = time.monotonic()
        failures: list[Failure] = []
        last: Candidate[C] | None = None
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
                if spent.__cause__ is None:
                    raise
                raise spent.__cause__ from None
            except Exception as error:
                last, last_spent = candidate, False
                if self.context.final(error):
                    self._record_failure(candidate)
                    raise
                self.context.on_failure(candidate, error)
                failures.append(Failure(candidate, error))
                continue
            if isinstance(reply, Refused):
                self._record_failure(candidate)
                return reply.value
            if reply.usage is not None:
                self.record(candidate, reply.usage)
            return reply.value
        if last is not None and not last_spent:
            self._record_failure(last)
        return self.context.on_exhausted(failures)

    async def stream(
        self, fn: Callable[[Attempt[C]], AsyncIterator[T]]
    ) -> AsyncIterator[T]:
        """Yield the items of the first candidate's stream.

        The last candidate tried is recorded with what its stream spent, when
        the stream ends, fails, or the consumer stops it.
        """
        self._start = time.monotonic()
        failures: list[Failure] = []
        attempt: Attempt[C] | None = None
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
