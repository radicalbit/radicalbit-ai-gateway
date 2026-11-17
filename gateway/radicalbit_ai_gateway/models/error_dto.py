"""The error bodies of the management API, as documentation only.

The exception handlers in ``utils/exceptions.py`` build these bodies; the
models below describe them in the OpenAPI spec (``responses=`` on the routes).
"""

from typing import Any

from pydantic import BaseModel


class ConfigErrorDetail(BaseModel):
    """One problem found in a gateway configuration."""

    loc: list[str | int]
    msg: str
    type: str


class ErrorBody(BaseModel):
    message: str
    type: str
    param: Any = None
    code: str | int | None = None
    # Config validation errors only: one entry per problem in the YAML
    details: list[ConfigErrorDetail] | None = None
    # Config budget conflicts only: the routes that configure their own budget
    routes: list[str] | None = None


class ErrorOut(BaseModel):
    error: ErrorBody


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Build the ``responses=`` of a route that can fail with an ``ErrorOut`` body."""
    return {status: {'model': ErrorOut} for status in statuses}
