from collections.abc import AsyncIterable, AsyncIterator, Sequence
from functools import cached_property
from typing import Any

from openai import AsyncOpenAI
from openai.resources.audio import AsyncAudio, AsyncTranscriptions
from typing_extensions import override


class _MockTranscriptionStream:
    """Mimics `AsyncStream[TranscriptionStreamEvent]` for a fixed list of events."""

    def __init__(self, events: Sequence[object]):
        self._events = events

    def __aiter__(self) -> AsyncIterator[object]:
        return self._agen()

    async def _agen(self) -> AsyncIterator[object]:
        for event in self._events:
            yield event


class _MockTranscriptions(AsyncTranscriptions):
    def __init__(
        self,
        client: AsyncOpenAI,
        response: object,
        exception: Exception | None,
        captured_kwargs: dict[str, Any],
        stream: AsyncIterable[object],
    ):
        super().__init__(client)
        self._response = response
        self._exception = exception
        self._captured_kwargs = captured_kwargs
        self._stream = stream

    @override
    async def create(self, **kwargs: Any) -> Any:
        self._captured_kwargs.update(kwargs)
        if self._exception is not None:
            raise self._exception
        if kwargs.get('stream'):
            return self._stream
        return self._response


class _MockAudio(AsyncAudio):
    def __init__(self, client: AsyncOpenAI, transcriptions: _MockTranscriptions):
        super().__init__(client)
        self._transcriptions = transcriptions

    @cached_property
    @override
    def transcriptions(self) -> AsyncTranscriptions:
        return self._transcriptions


class MockTranscriptionClient(AsyncOpenAI):
    """An OpenAI SDK client whose `audio.transcriptions.create(...)` answers
    from the test, without hitting the network.

    `captured_kwargs` is populated with the kwargs passed to
    `audio.transcriptions.create(...)`, so tests can assert on the upstream
    `response_format` policy. A `stream=True` call returns `stream`, or else
    an async-iterable of `stream_events`; a `response`/`exception` still
    control the non-streaming call.
    """

    def __init__(
        self,
        response: object = None,
        exception: Exception | None = None,
        stream_events: Sequence[object] = (),
        stream: AsyncIterable[object] | None = None,
    ):
        super().__init__(api_key='test-key')
        self.captured_kwargs: dict[str, Any] = {}
        self._mock_audio = _MockAudio(
            self,
            _MockTranscriptions(
                self,
                response,
                exception,
                self.captured_kwargs,
                stream
                if stream is not None
                else _MockTranscriptionStream(stream_events),
            ),
        )

    @cached_property
    @override
    def audio(self) -> AsyncAudio:
        return self._mock_audio
