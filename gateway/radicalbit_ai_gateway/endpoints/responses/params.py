"""The body of a Responses API request."""

from __future__ import annotations

from typing import Any, Union

from openai.types.shared.chat_model import ChatModel
from openai.types.shared_params.metadata import Metadata
from typing_extensions import Required, TypedDict

# ---------------------------------------------------------------------------
# Responses API (POST /v1/responses)
# ---------------------------------------------------------------------------
# A minimal TypedDict for the Responses API create params.  We use `list`
# instead of `Iterable` and `Any` for union-heavy fields so that FastAPI /
# Pydantic can parse the request body without issues. It only validates the
# request: the body goes upstream with every field the client sent.
# ---------------------------------------------------------------------------


class ResponseCreateParamsCustom(TypedDict, total=False):
    input: Union[str, list]
    """The input to the model — a string or a list of input items."""

    model: Required[Union[str, ChatModel]]
    """Gateway route name used to select the backend model."""

    instructions: str | None
    """System-level instructions for the model."""

    stream: bool | None
    """Whether to stream the response."""

    tools: list
    """Function, custom and hosted tools (see the route's ``responses`` settings)."""

    tool_choice: Any
    """Which tool the model should use."""

    temperature: float | None
    """Sampling temperature."""

    top_p: float | None
    """Nucleus sampling probability."""

    max_output_tokens: int | None
    """Maximum number of output tokens."""

    metadata: Metadata | None
    """Key-value pairs attached to the response."""

    previous_response_id: str | None
    """A response stored at the provider to continue; the request has no fallback."""

    store: bool | None
    """Whether the provider stores the response (forced false by a route's settings)."""

    user: str | None
    """End-user identifier forwarded to the upstream provider."""

    parallel_tool_calls: bool | None
    """Whether to allow parallel tool calls."""
