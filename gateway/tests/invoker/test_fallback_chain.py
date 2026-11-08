"""The fallback chain: which candidate answers, and what is recorded."""

from unittest.mock import MagicMock

import pytest

from tests.common.request_identity import IDENTITY

from radicalbit_ai_gateway.invocation.fallback_chain import (
    Attempt,
    CallContext,
    FallbackChain,
    Refused,
    Reply,
    Skip,
    Spent,
    TryNext,
    candidates,
)
from radicalbit_ai_gateway.invocation.recorder import Call, Recorder, Tokens
from radicalbit_ai_gateway.models.model import Model

A = Model(model_id='a', model='openai/a')
B = Model(model_id='b', model='openai/b')
C = Model(model_id='c', model='openai/c')
CALL = Call(identity=IDENTITY, model_type='chat-model', target_model_id='a')


def _chain(**context) -> tuple[FallbackChain, MagicMock]:
    recorder = MagicMock(spec_set=Recorder)
    chain = FallbackChain(
        candidates((A, 'client-a'), [(B, 'client-b'), (C, 'client-c')]),
        CallContext(call=CALL, recorder=recorder, **context),
    )
    return chain, recorder


def _recorded(recorder: MagicMock) -> list[tuple]:
    calls = []
    for c in recorder.method_calls:
        name, args, kwargs = c
        calls.append(
            (name, args[1].model_id, kwargs.get('tokens'), kwargs['fallback_triggered'])
        )
    return calls


async def test_the_first_answer_is_returned_and_recorded():
    chain, recorder = _chain()

    async def fn(candidate):
        if candidate.model is A:
            raise RuntimeError('down')
        return Reply(candidate.client, usage=Tokens(input=3))

    assert await chain.call(fn) == 'client-b'
    assert _recorded(recorder) == [('invocation', 'b', Tokens(input=3), True)]


async def test_a_reply_without_usage_records_nothing():
    chain, recorder = _chain()

    async def fn(candidate):
        return Reply(candidate.client)

    assert await chain.call(fn) == 'client-a'
    assert recorder.method_calls == []


async def test_failures_are_logged_then_exhausted_records_the_last_model_tried():
    logged = []
    chain, recorder = _chain(
        on_failure=lambda c, e: logged.append((c.model.model_id, str(e))),
        on_exhausted=lambda failures: [f.candidate.model.model_id for f in failures],
    )

    async def fn(candidate):
        raise RuntimeError(candidate.client)

    assert await chain.call(fn) == ['a', 'b', 'c']
    assert logged == [('a', 'client-a'), ('b', 'client-b'), ('c', 'client-c')]
    assert _recorded(recorder) == [('failure', 'c', None, True)]


async def test_exhausted_raises_the_last_error_by_default():
    chain, _ = _chain()

    async def fn(candidate):
        raise TryNext(ValueError(candidate.client))

    with pytest.raises(ValueError, match='client-c'):
        await chain.call(fn)


async def test_a_final_error_is_raised_without_fallback():
    chain, recorder = _chain(final=lambda e: isinstance(e, KeyError))

    async def fn(candidate):
        raise KeyError(candidate.client)

    with pytest.raises(KeyError):
        await chain.call(fn)
    assert _recorded(recorder) == [('failure', 'a', None, False)]


async def test_a_refusal_is_returned_without_fallback():
    chain, recorder = _chain()

    async def fn(candidate):
        raise Refused('no')

    assert await chain.call(fn) == 'no'
    assert _recorded(recorder) == [('failure', 'a', None, False)]


async def test_skipped_candidates_are_not_tried():
    chain, recorder = _chain(on_exhausted=len)

    async def fn(candidate):
        if candidate.is_fallback:
            raise Skip
        raise TryNext(RuntimeError('down'))

    assert await chain.call(fn) == 1
    assert _recorded(recorder) == [('failure', 'a', None, False)]


async def test_a_spent_attempt_is_not_recorded_again():
    chain, recorder = _chain(on_exhausted=lambda failures: None)

    async def fn(candidate):
        raise TryNext(RuntimeError('bad answer'), spent=True)

    assert await chain.call(fn) is None
    assert recorder.method_calls == []


async def test_a_last_resort_reaches_on_exhausted():
    chain, _ = _chain(
        on_exhausted=lambda failures: [f.last_resort.value for f in failures]
    )

    async def fn(candidate):
        raise TryNext(last_resort=Reply(candidate.client))

    assert await chain.call(fn) == ['client-a', 'client-b', 'client-c']


async def _collect(chain, fn):
    items = []
    try:
        async for item in chain.stream(fn):
            items.append(item)  # noqa: PERF401 — keep the items before an error
    except Exception as error:
        return items, error
    return items, None


async def test_a_stream_falls_back_before_its_first_item():
    chain, recorder = _chain()

    async def fn(attempt: Attempt):
        if attempt.candidate.model is A:
            raise RuntimeError('refused')
        attempt.usage = Tokens(output=2)
        yield attempt.candidate.client

    assert await _collect(chain, fn) == (['client-b'], None)
    assert _recorded(recorder) == [('invocation', 'b', Tokens(output=2), True)]


async def test_a_stream_does_not_fall_back_after_its_first_item():
    chain, recorder = _chain()

    async def fn(attempt: Attempt):
        attempt.usage = Tokens(output=1)
        yield attempt.candidate.client
        raise RuntimeError('reset')

    items, error = await _collect(chain, fn)

    assert items == ['client-a']
    assert str(error) == 'reset'
    assert _recorded(recorder) == [('invocation', 'a', Tokens(output=1), False)]


async def test_an_exhausted_stream_records_the_last_model_tried():
    chain, recorder = _chain()

    async def fn(attempt: Attempt):
        raise TryNext(RuntimeError(attempt.candidate.client))
        yield  # noqa: RUF027 — makes this an async generator

    items, error = await _collect(chain, fn)

    assert (items, str(error)) == ([], 'client-c')
    assert _recorded(recorder) == [('invocation', 'c', Tokens(), True)]


async def test_a_custom_record_replaces_the_default():
    seen = []
    chain, recorder = _chain(
        record=lambda c, usage, latency: seen.append((c.model.model_id, usage))
    )

    async def fn(candidate):
        return Reply('ok', usage='spent')

    await chain.call(fn)
    assert seen == [('a', 'spent')]
    assert recorder.method_calls == []


async def test_a_custom_failure_record_replaces_the_default():
    seen = []
    chain, recorder = _chain(
        record_failure=lambda c, latency: seen.append(c.model.model_id),
        on_exhausted=lambda failures: None,
    )

    async def fn(candidate):
        raise TryNext

    await chain.call(fn)
    assert seen == ['c']
    assert recorder.method_calls == []


async def test_a_spent_call_raises_its_cause_without_fallback():
    chain, recorder = _chain()
    tried = []

    async def fn(candidate):
        tried.append(candidate.model.model_id)
        raise Spent from KeyError('limit')

    with pytest.raises(KeyError):
        await chain.call(fn)
    assert tried == ['a']
    assert recorder.method_calls == []
