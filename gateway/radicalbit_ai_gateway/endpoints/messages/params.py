"""The body of an Anthropic Messages API request."""

from __future__ import annotations

from typing import Any

from typing_extensions import Required, TypedDict


class MessageCreateParams(TypedDict, total=False):
    """The shape of a Messages request the gateway needs.

    It only validates the request: the body goes upstream with every field the
    client sent.
    """

    model: Required[str]
    """Gateway route name used to select the backend model."""

    messages: Required[list[dict[str, Any]]]
    """The conversation, as Anthropic's message objects."""

    max_tokens: Required[int]
    """The most tokens the model may generate."""

    system: str | list[dict[str, Any]] | None
    """The system prompt, a string or a list of text blocks."""

    stream: bool | None
    """Whether to stream the response."""
