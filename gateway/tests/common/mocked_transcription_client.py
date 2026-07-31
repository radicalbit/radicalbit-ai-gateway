class _MockTranscriptionStream:
    """Mimics `AsyncStream[TranscriptionStreamEvent]` for a fixed list of events."""

    def __init__(self, events):
        self._events = events

    def __aiter__(self):
        return self._agen()

    async def _agen(self):
        for event in self._events:
            yield event


class _MockTranscriptions:
    def __init__(
        self,
        response=None,
        exception=None,
        captured_kwargs=None,
        stream_events=None,
    ):
        self._response = response
        self._exception = exception
        self._captured_kwargs = captured_kwargs
        self._stream_events = stream_events

    async def create(self, **kwargs):
        if self._captured_kwargs is not None:
            self._captured_kwargs.update(kwargs)
        if self._exception is not None:
            raise self._exception
        if kwargs.get('stream'):
            return _MockTranscriptionStream(self._stream_events or [])
        return self._response


class _MockAudio:
    def __init__(self, transcriptions: _MockTranscriptions):
        self.transcriptions = transcriptions


class MockTranscriptionClient:
    """Mimics the subset of the OpenAI SDK client surface that
    `TranscriptionModelInvoker` uses, without hitting the network.

    `captured_kwargs` is populated with the kwargs passed to
    `audio.transcriptions.create(...)`, so tests can assert on the upstream
    `response_format` policy. `stream_events`, if provided, is what a
    `stream=True` call returns (an async-iterable of stream events); a
    `response`/`exception` still control the non-streaming call.
    """

    def __init__(self, response=None, exception=None, stream_events=None):
        self.captured_kwargs: dict = {}
        self.audio = _MockAudio(
            _MockTranscriptions(
                response, exception, self.captured_kwargs, stream_events
            )
        )
