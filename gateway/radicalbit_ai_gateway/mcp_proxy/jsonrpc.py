"""JSON-RPC 2.0 framing helpers for the inbound MCP endpoint.

Protocol-level failures are carried as JSON-RPC ``error`` objects (usually
over HTTP 200); only envelope problems the gateway cannot attribute to a
well-formed request (parse / invalid request) travel over HTTP 400. See
``gateway/mcp_protocol.md`` §3.
"""

from typing import Any

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

RequestId = str | int


def is_valid_request_id(request_id: Any) -> bool:
    """Check the JSON-RPC request ``id``: string or integer, never null."""
    return isinstance(request_id, RequestId) and not isinstance(request_id, bool)


def result_message(request_id: RequestId, result: dict) -> dict:
    return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def error_message(
    request_id: RequestId | None,
    code: int,
    message: str,
    data: Any = None,
) -> dict:
    error: dict[str, Any] = {'code': code, 'message': message}
    if data is not None:
        error['data'] = data
    return {'jsonrpc': '2.0', 'id': request_id, 'error': error}
