"""Drivers for the request pipeline in tests that call it directly.

They take a request the way tests describe it, the caller in loose fields
(``request_uuid``, ``api_key_uuid``…), and run it through the route's
pipeline in the scope of that caller.
"""

from dataclasses import dataclass, field

from tests.common.limits import request_limits
from tests.common.request_identity import with_identity

from radicalbit_ai_gateway.pipeline import (
    chat as chat_pipeline,
    embeddings as embeddings_pipeline,
    transcription as transcription_pipeline,
)
from radicalbit_ai_gateway.pipeline.chat import ChatRequest
from radicalbit_ai_gateway.pipeline.scope import RequestScope
from radicalbit_ai_gateway.pipeline.transcription import Audio

_CHAT_FIELDS = {'messages', 'tools', 'tool_choice'}


@dataclass
class InvokeResponse:
    """What an endpoint answers: its body and the gateway's headers."""

    content: object
    headers: dict[str, str] = field(default_factory=dict)


def scope_of(route, limits=None, **caller) -> RequestScope:
    """Return the scope of a request to ``route`` by ``caller`` (loose
    identity fields; the tests' caller for those not given).
    """
    caller.pop('route_name', None)
    identity = with_identity(
        route_name=route.gateway_route_config.route_name,
        project_uuid=route.project_uuid,
        project_name=route.project_name,
        **caller,
    )['identity']
    return route.for_request(identity, limits or request_limits(route))


def _split(kwargs: dict) -> tuple[dict, ChatRequest]:
    """Split a test's chat call into its caller and its request."""
    caller = {
        k: kwargs.pop(k)
        for k in list(kwargs)
        if k
        in (
            'limits',
            'request_uuid',
            'api_key_uuid',
            'api_key_name',
            'group_uuid',
            'group_name',
            'route_name',
        )
    }
    chat = ChatRequest(
        messages=list(kwargs.pop('messages')),
        tools=kwargs.pop('tools', None),
        tool_choice=kwargs.pop('tool_choice', None),
        params=kwargs,
    )
    return caller, chat


async def invoke(route, **kwargs) -> InvokeResponse:
    """Answer a chat request with one completion."""
    caller, chat = _split(kwargs)
    scope = scope_of(route, **caller)
    content = await chat_pipeline.complete(scope, chat)
    return InvokeResponse(content, scope.headers())


async def stream(route, **kwargs) -> InvokeResponse:
    """Answer a chat request with chunks; return them all."""
    caller, chat = _split({**kwargs, 'stream': True})
    scope = scope_of(route, **caller)
    items = await chat_pipeline.stream(scope, chat)
    chunks = [chunk async for chunk in items]
    return InvokeResponse(chunks, scope.headers())


_CALLER_FIELDS = (
    'limits',
    'request_uuid',
    'api_key_uuid',
    'api_key_name',
    'group_uuid',
    'group_name',
    'route_name',
)


def _caller(kwargs: dict) -> dict:
    return {k: kwargs.pop(k) for k in list(kwargs) if k in _CALLER_FIELDS}


async def invoke_embeddings(route, **kwargs):
    """Embed ``input_texts``."""
    scope = scope_of(route, **_caller(kwargs))
    return await embeddings_pipeline.embed(scope, kwargs['input_texts'])


def _audio(kwargs: dict) -> Audio:
    return Audio(
        content=kwargs['audio_bytes'],
        filename=kwargs['filename'],
        content_type=kwargs.get('content_type'),
        language=kwargs.get('language'),
        prompt=kwargs.get('prompt'),
        temperature=kwargs.get('temperature'),
        response_format=kwargs.get('requested_response_format', 'json'),
    )


async def invoke_transcription(route, **kwargs):
    """Transcribe ``audio_bytes``."""
    scope = scope_of(route, **_caller(kwargs))
    return await transcription_pipeline.transcribe(scope, _audio(kwargs))
