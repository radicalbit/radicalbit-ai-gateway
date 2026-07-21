JSON_RPC_UPSTREAM_ERROR = -32000


class McpUpstreamError(Exception):
    """Failure while calling an upstream MCP server.

    ``message`` must stay sanitized (alias only — never url, headers, or
    command); full detail is logged at the raise site. Deliberately not an
    ``AppError``: upstream failures become JSON-RPC error bodies over HTTP
    200, not HTTP error responses.
    """

    def __init__(self, alias: str, message: str, code: int = JSON_RPC_UPSTREAM_ERROR):
        super().__init__(message)
        self.alias = alias
        self.message = message
        self.code = code
