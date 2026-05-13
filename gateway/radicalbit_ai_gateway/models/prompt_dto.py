from enum import Enum

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class PromptCategory(str, Enum):
    CHAT_MODEL = 'chat-model'
    GUARDRAIL_JUDGE = 'guardrail-judge'


class PromptItemOut(BaseModel):
    category: PromptCategory
    model_id: str
    model_name: str
    guardrail_name: str | None = None
    tokens: int = 0
    prompt: str | None = None

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class RoutePromptsOut(BaseModel):
    route_name: str
    prompts: list[PromptItemOut]

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )
