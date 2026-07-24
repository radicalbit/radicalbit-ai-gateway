from pydantic import BaseModel


class McpDispatchResult(BaseModel):
    status_code: int
    payload: dict | None = None
