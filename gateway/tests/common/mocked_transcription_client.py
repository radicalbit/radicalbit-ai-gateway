class _MockTranscriptions:
    def __init__(self, response=None, exception=None, captured_kwargs=None):
        self._response = response
        self._exception = exception
        self._captured_kwargs = captured_kwargs

    async def create(self, **kwargs):
        if self._captured_kwargs is not None:
            self._captured_kwargs.update(kwargs)
        if self._exception is not None:
            raise self._exception
        return self._response


class _MockAudio:
    def __init__(self, transcriptions: _MockTranscriptions):
        self.transcriptions = transcriptions


class MockTranscriptionClient:
    """Mimics the subset of the OpenAI SDK client surface that
    `TranscriptionModelInvoker` uses, without hitting the network.

    `captured_kwargs` is populated with the kwargs passed to
    `audio.transcriptions.create(...)`, so tests can assert on the upstream
    `response_format` policy.
    """

    def __init__(self, response=None, exception=None):
        self.captured_kwargs: dict = {}
        self.audio = _MockAudio(
            _MockTranscriptions(response, exception, self.captured_kwargs)
        )
