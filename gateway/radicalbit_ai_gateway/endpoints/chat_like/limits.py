"""The limit check of a chat-like request, before anything spends."""

from radicalbit_ai_gateway.endpoints.common.limits import check_limits, checked_in_span
from radicalbit_ai_gateway.gateway_route.scope import RequestScope
from radicalbit_ai_gateway.limiting.limits import Demand, InputEstimate
from radicalbit_ai_gateway.llm.messages import BaseMessage
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.utils.build_user_content import build_user_content


def chat_demand(messages: list[BaseMessage], model: Model) -> Demand:
    """Return what a chat request demands; ``model`` picks the tokenizer."""
    return Demand(
        input=InputEstimate(build_user_content(messages), model.model),
        output_room=True,
        cost_room=True,
    )


_check_in_chat_span = checked_in_span('check_limiters')


async def check_chat_limits(scope: RequestScope, messages: list[BaseMessage]) -> None:
    """Check a conversation on the request's limits, before anything spends.
    Routing has not run yet: the route's first chat model picks the
    tokenizer.
    """
    await check_limits(
        scope.limits,
        chat_demand(messages, scope.route.chat_models[0]),
        _check_in_chat_span,
    )
