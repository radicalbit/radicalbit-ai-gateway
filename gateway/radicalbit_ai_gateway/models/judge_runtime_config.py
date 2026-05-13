from pydantic import BaseModel


class JudgeRuntimeConfig(BaseModel):
    model_id: str
    fallback_model_id: str | None = None
    temperature: float = 0.0
    max_tokens: int = 512
    prompt_ref: str
    include_reasoning: bool = True
