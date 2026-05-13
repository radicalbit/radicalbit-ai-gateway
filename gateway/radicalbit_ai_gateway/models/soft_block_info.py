from dataclasses import dataclass
from time import time
import uuid

from openai.types import CompletionUsage
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from openai.types.create_embedding_response import CreateEmbeddingResponse, Usage

from radicalbit_ai_gateway.models.guardrails import Guardrail, GuardrailWhereType


@dataclass
class SoftBlockInfo:
    """Information about a triggered soft block guardrail."""

    guardrail: Guardrail
    where: GuardrailWhereType
    message: str  # client-facing fallback

    def get_soft_block_message(self) -> str:
        custom_response_message = self.guardrail.response_message

        if custom_response_message:
            return custom_response_message
        if self.where == GuardrailWhereType.INPUT:
            return f'I cannot process this request as it violates content policy: {self.guardrail.name}'
        return f'This response has been blocked due to policy violation: {self.guardrail.name}'

    def build_soft_block_response(self, route_name: str) -> ChatCompletion:
        """Build a ChatCompletion response for a soft block guardrail."""
        error_message = self.get_soft_block_message()

        return ChatCompletion(
            id=f'chatcmpl-{uuid.uuid4()}',
            object='chat.completion',
            created=int(time()),
            model=route_name,
            choices=[
                Choice(
                    index=0,
                    message=ChatCompletionMessage(
                        role='assistant',
                        content=error_message,
                        tool_calls=None,
                    ),
                    finish_reason='stop',
                )
            ],
            usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )

    def build_soft_block_embedding_response(
        self,
        route_name: str,
    ) -> CreateEmbeddingResponse:
        """Build a CreateEmbeddingResponse for embedding inputs blocked by a guardrail."""
        error_message = self.get_soft_block_message()

        return CreateEmbeddingResponse(
            object='list',
            data=[],
            model=route_name,
            usage=Usage(
                prompt_tokens=0,
                total_tokens=0,
            ),
            error=error_message,
        )
