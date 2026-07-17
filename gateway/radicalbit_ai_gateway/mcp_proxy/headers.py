from collections.abc import Mapping

from radicalbit_ai_gateway.models.mcp_server import (
    FORBIDDEN_FORWARD_HEADERS,
    GATEWAY_AUTH_HEADER,
    MCP_FORWARD_HEADER_PREFIX,
    McpHttpServer,
)


def build_upstream_headers(
    server: McpHttpServer,
    inbound_headers: Mapping[str, str] | None,
) -> dict[str, str]:
    """Build the headers sent to an upstream MCP server.

    Inbound client headers fill allowlisted (``server.forward_headers``)
    upstream header names from two sources:

    - the plain header itself (``X-User-Jwt`` → ``x-user-jwt``), except
      ``authorization``, which always carries the gateway API key;
    - the server-specific form ``x-mcp-{alias}-{header}``
      (``x-mcp-github-authorization`` → ``authorization`` on the ``github``
      server only), which wins over the plain form and is the only way to
      fill the upstream ``authorization`` header.

    Static ``server.headers`` are applied last so operator-provisioned
    credentials always win over client-supplied values.
    """
    headers: dict[str, str] = {}
    if inbound_headers and server.forward_headers:
        allowed = set(server.forward_headers) - FORBIDDEN_FORWARD_HEADERS
        prefix = f'{MCP_FORWARD_HEADER_PREFIX}{server.alias.lower()}-'
        prefixed: dict[str, str] = {}
        for name, value in inbound_headers.items():
            lowered = name.lower()
            if lowered.startswith(prefix):
                target = lowered[len(prefix) :]
                if target in allowed:
                    prefixed[target] = value
            elif lowered in allowed and lowered != GATEWAY_AUTH_HEADER:
                headers[lowered] = value
        headers.update(prefixed)
    if server.headers:
        for name, value in server.headers.items():
            headers.pop(name.lower(), None)
            headers[name] = value
    return headers
