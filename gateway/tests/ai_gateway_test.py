"""How a route wires its invokers. What a route does with a request is driven
over HTTP in ``tests/pipeline/test_route_http.py``.
"""

from unittest.mock import MagicMock

from radicalbit_ai_gateway.ai_gateway import GatewayRoute
from radicalbit_ai_gateway.models.credentials import Credentials
from radicalbit_ai_gateway.models.fallback import Fallback, FallbackModelType
from radicalbit_ai_gateway.models.gateway_route_config import GatewayRouteConfig
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.services.cost_service import CostService


def test_transcription_invoker_only_receives_transcription_fallbacks():
    """`GatewayRoute` must filter the route's `fallback` list down to
    `FallbackModelType.TRANSCRIPTION` entries before wiring it into
    `TranscriptionModelInvoker` — CHAT/EMBEDDING fallbacks aren't meaningful
    there and would otherwise leak in unfiltered.
    """
    cost_service = MagicMock(spec_set=CostService)
    gpt4o_model = Model(
        model_id='gpt4o-transcribe',
        model='openai/gpt-4o-transcribe',
        credentials=Credentials(api_key='sk-test'),
    )
    gpt4o_mini_model = Model(
        model_id='gpt4o-mini-transcribe',
        model='openai/gpt-4o-mini-transcribe',
        credentials=Credentials(api_key='sk-test'),
    )
    transcription_fallback = Fallback(
        type=FallbackModelType.TRANSCRIPTION,
        target='gpt4o-transcribe',
        fallbacks=['gpt4o-mini-transcribe'],
    )
    chat_fallback = Fallback(
        type=FallbackModelType.CHAT, target='some-chat-model', fallbacks=['other']
    )
    route_cfg = GatewayRouteConfig(
        route_name='rb-gateway',
        chat_models=[],
        transcription_models=['gpt4o-transcribe', 'gpt4o-mini-transcribe'],
        fallback=[transcription_fallback, chat_fallback],
    )

    ai_gateway = GatewayRoute(
        gateway_route_config=route_cfg,
        chat_models=[],
        embedding_models=None,
        transcription_models=[gpt4o_model, gpt4o_mini_model],
        gateway_cache=None,
        cost_service=cost_service,
    )

    assert ai_gateway.transcription_invoker.fallbacks == [transcription_fallback]
    fallback_model_ids = {
        m.model_id
        for m, _ in ai_gateway.transcription_invoker.model_map['gpt4o-transcribe'][2]
    }
    assert fallback_model_ids == {'gpt4o-mini-transcribe'}
