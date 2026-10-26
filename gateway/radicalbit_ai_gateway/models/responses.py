from pydantic import BaseModel, ConfigDict, Field


class ResponsesSettings(BaseModel):
    """How a route governs the OpenAI Responses API (``POST /v1/responses``)."""

    model_config = ConfigDict(extra='forbid')

    force_store_false: bool = Field(
        default=False,
        description=(
            'Forward every request with store: false, so the provider keeps no '
            'response. Requests that reference stored state (previous_response_id, '
            'conversation, item_reference items) are rejected.'
        ),
    )
    allowed_hosted_tools: list[str] | None = Field(
        default=None,
        description=(
            'Tool types other than function and custom a request may use '
            '(web_search, file_search, code_interpreter, mcp...). '
            'Not set: all are allowed. Empty: none is.'
        ),
        examples=[['web_search', 'file_search']],
    )
