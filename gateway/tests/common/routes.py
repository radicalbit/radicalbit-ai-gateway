"""Mocked routes for tests of the HTTP handlers.

A handler admits a request, then runs the route's pipeline. For a mocked
route, ``answered_by_mocks`` serves the pipeline from the mock's own
attributes, which tests configure:

- ``invoke`` answers a chat completion with an ``InvokeResponse``;
- ``invoke_embeddings`` answers an embeddings request;
- ``invoke_transcription`` and ``invoke_transcription_stream`` answer a
  transcription;
- ``prepare_stream`` returns a ``Prepared`` (the stream's headers), then
  ``invoke_stream`` yields its chunks, or ``invoke_stream_buffered``
  returns them with the headers when the route has output guardrails.

Each is called with the caller in loose fields (``limits``,
``request_uuid``, ``api_key_uuid``…) and the request's fields.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import partial
from unittest.mock import AsyncMock, MagicMock, patch

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.pipeline import (
    chat as chat_pipeline,
    embeddings as embeddings_pipeline,
    transcription as transcription_pipeline,
)


@dataclass
class Prepared:
    """What a mocked route's ``prepare_stream`` returns: the stream's headers."""

    headers: dict[str, str] = field(default_factory=dict)


def mock_route() -> MagicMock:
    """Return a mocked GatewayRoute whose requests are scoped to the mock
    itself, as a real route's are: ``for_request`` is the real one.
    """
    route = MagicMock(spec=GatewayRoute)
    route.for_request = partial(GatewayRoute.for_request, route)
    route.guardrails = MagicMock()
    route.cache = MagicMock()
    route.invoke = AsyncMock()
    route.prepare_stream = AsyncMock(return_value=Prepared())
    route.invoke_stream = MagicMock()
    route.invoke_stream_buffered = AsyncMock()
    route.invoke_embeddings = AsyncMock()
    route.invoke_transcription = AsyncMock()
    route.invoke_transcription_stream = MagicMock()
    return route


def _caller(scope) -> dict:
    identity = scope.identity
    return {
        'limits': scope.limits,
        'request_uuid': identity.request_uuid,
        'api_key_uuid': identity.api_key_uuid,
        'api_key_name': identity.api_key_name,
        'group_uuid': identity.group_uuid,
        'group_name': identity.group_name,
        'route_name': identity.route_name,
    }


def _loose(scope, chat) -> dict:
    return {
        **_caller(scope),
        'tools': chat.tools,
        'tool_choice': chat.tool_choice,
        **chat.params,
    }


async def _complete(scope, chat):
    answer = await scope.route.invoke(**_loose(scope, chat), messages=chat.messages)
    scope.headers = lambda: answer.headers
    return answer.content


async def _stream(scope, chat):
    route = scope.route
    prepared = await route.prepare_stream(**_loose(scope, chat), messages=chat.messages)
    if route.guardrails.has_output:
        chunks, headers = await route.invoke_stream_buffered(
            **_loose(scope, chat), prepared=prepared
        )
        scope.headers = lambda: headers

        async def items():
            for chunk in chunks:
                yield chunk

        return items()
    scope.headers = lambda: prepared.headers
    return route.invoke_stream(**_loose(scope, chat), prepared=prepared)


async def _embed(scope, texts):
    return await scope.route.invoke_embeddings(**_caller(scope), input_texts=texts)


def _audio(audio) -> dict:
    return {
        'audio_bytes': audio.content,
        'filename': audio.filename,
        'content_type': audio.content_type,
        'language': audio.language,
        'prompt': audio.prompt,
        'temperature': audio.temperature,
    }


async def _transcribe(scope, audio):
    return await scope.route.invoke_transcription(
        **_caller(scope),
        **_audio(audio),
        requested_response_format=audio.response_format,
    )


async def _transcribe_stream(scope, audio):
    return scope.route.invoke_transcription_stream(**_caller(scope), **_audio(audio))


def _for_mocks(fake, real):
    """Return ``fake`` for a mocked route's requests, ``real`` for others."""

    async def serve(scope, *args):
        if isinstance(scope.route, MagicMock):
            return await fake(scope, *args)
        return await real(scope, *args)

    return serve


@contextmanager
def answered_by_mocks():
    """Serve the requests of mocked routes from their attributes."""
    with (
        patch.object(
            chat_pipeline, 'complete', _for_mocks(_complete, chat_pipeline.complete)
        ),
        patch.object(
            chat_pipeline, 'stream', _for_mocks(_stream, chat_pipeline.stream)
        ),
        patch.object(
            embeddings_pipeline, 'embed', _for_mocks(_embed, embeddings_pipeline.embed)
        ),
        patch.object(
            transcription_pipeline,
            'transcribe',
            _for_mocks(_transcribe, transcription_pipeline.transcribe),
        ),
        patch.object(
            transcription_pipeline,
            'stream',
            _for_mocks(_transcribe_stream, transcription_pipeline.stream),
        ),
    ):
        yield
