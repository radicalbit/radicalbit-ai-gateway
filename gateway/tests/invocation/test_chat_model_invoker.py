"""The chat model invoker: the tools a fallback is offered."""

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any
from unittest.mock import MagicMock

from openai.types.chat import ChatCompletionToolUnionParam
from typing_extensions import override

from tests.common.request_identity import IDENTITY

from radicalbit_ai_gateway.invocation.chat_model_invoker import ChatModelInvoker
from radicalbit_ai_gateway.invocation.recorder import Recorder
from radicalbit_ai_gateway.llm.chat_model import ChatModel
from radicalbit_ai_gateway.llm.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
)
from radicalbit_ai_gateway.models.fallback import Fallback
from radicalbit_ai_gateway.models.model import Model
from radicalbit_ai_gateway.services.cost_service import CostService

TARGET = Model(model_id='target', model='openai/target')
FALLBACK = Model(model_id='fallback', model='openai/fallback')
LOOKUP: ChatCompletionToolUnionParam = {
    'type': 'function',
    'function': {'name': 'lookup', 'parameters': {}},
}


class _ToolsModel(ChatModel):
    """Answers with the names of the tools it was bound with; fails when ``down``."""

    def __init__(
        self, down: bool, tools: Sequence[Mapping[str, Any]] = (), tool_choice=None
    ):
        self.down = down
        self.tools = tools
        self.tool_choice = tool_choice

    @override
    def bind_tools(
        self, tools: Sequence[Mapping[str, Any]], tool_choice: Any = None
    ) -> ChatModel:
        return _ToolsModel(self.down, tools, tool_choice)

    @override
    async def _agenerate(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        if self.down:
            raise RuntimeError('down')
        names = [tool['function']['name'] for tool in self.tools]
        return AIMessage(content=f'tools={names} choice={self.tool_choice}')

    @override
    async def _astream(
        self, messages: list[BaseMessage], **kwargs: Any
    ) -> AsyncIterator[AIMessageChunk]:
        raise NotImplementedError
        yield


class _Invoker(ChatModelInvoker):
    @override
    def _build_model(self, model: Model) -> ChatModel:
        return _ToolsModel(down=model is TARGET)


def _invoker() -> _Invoker:
    invoker = _Invoker(
        models=[TARGET, FALLBACK],
        cost_service=MagicMock(spec_set=CostService),
        fallbacks=[Fallback(target='target', fallbacks=['fallback'])],
    )
    invoker.recorder = MagicMock(spec_set=Recorder)
    return invoker


async def test_a_fallback_is_offered_the_tools_of_the_request():
    completion = await _invoker().complete(
        identity=IDENTITY,
        messages=[HumanMessage(content='hi')],
        model_id='target',
        tools=[LOOKUP],
        tool_choice='auto',
    )

    assert completion.model == 'fallback'
    assert completion.choices[0].message.content == "tools=['lookup'] choice=auto"


async def test_a_fallback_without_tool_choice_is_not_offered_tools():
    completion = await _invoker().complete(
        identity=IDENTITY,
        messages=[HumanMessage(content='hi')],
        model_id='target',
        tools=[LOOKUP],
        tool_choice=None,
    )

    assert completion.choices[0].message.content == 'tools=[] choice=None'
