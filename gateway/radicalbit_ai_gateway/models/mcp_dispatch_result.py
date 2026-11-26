from typing import Any

from pydantic import BaseModel


class McpDispatchResult(BaseModel):
    status_code: int
    payload: dict[str, Any] | None = None
