from pydantic import BaseModel


class JudgeInvocationResult(BaseModel):
    """Container for raw judge invocation data before metrics recording."""

    result: dict
    latency_ms: float
    token_input_count: int | None = None
    token_output_count: int | None = None
    cached_token_count: int | None = None
