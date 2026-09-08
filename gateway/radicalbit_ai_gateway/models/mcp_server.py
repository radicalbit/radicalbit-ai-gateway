from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

# Header names that may never be sent to an upstream MCP server, regardless
# of source: the mcp-* headers are owned by the SDK transport, the rest are
# hop-by-hop or message-framing headers.
FORBIDDEN_FORWARD_HEADERS = frozenset(
    {
        'host',
        'content-length',
        'content-type',
        'accept',
        'connection',
        'transfer-encoding',
        'te',
        'upgrade',
        'mcp-session-id',
        'mcp-protocol-version',
        'x-rb-tags',
    }
)

# The inbound 'authorization' header carries the gateway's own API key and is
# never forwarded as-is. It IS a valid *target* name in forward_headers: the
# client supplies the upstream credential via the server-specific
# 'x-mcp-{alias}-authorization' header instead.
GATEWAY_AUTH_HEADER = 'authorization'

# Prefix of server-specific client headers: 'x-mcp-{alias}-{header}' is
# forwarded to the server with that alias as '{header}' (if allowlisted).
MCP_FORWARD_HEADER_PREFIX = 'x-mcp-'

ALIAS_TOOL_SEPARATOR = '__'


def _allowed(allowlist: list[str] | None, value: str) -> bool:
    """Apply one allowlist's null/empty semantics.

    ``None`` means "everything" (the pre-allowlist behaviour), an empty list
    means "nothing". Keeping the two apart is the whole point: a config that
    deliberately exposes no tools must not read as one that never opted in.
    """
    return allowlist is None or value in allowlist


class McpServerBase(BaseModel):
    model_config = ConfigDict(extra='forbid')

    alias: str = Field(
        ...,
        description=(
            "Unique alias for the MCP server; used as the '{alias}__{tool}' "
            'prefix when tools are exposed on a route.'
        ),
        examples=['github', 'internal-search'],
    )
    timeout: float | None = Field(
        default=None,
        gt=0,
        description='Per-operation timeout override in seconds.',
    )
    allowed_tools: list[str] | None = Field(
        default=None,
        description=(
            'Allowlist of upstream tool names this server may expose. Names are '
            "the upstream's own, i.e. before the '{alias}__' prefix is applied. "
            'Omitted or null exposes every tool the upstream advertises; an '
            'empty list exposes none. Entries the upstream does not advertise '
            'are inert (warned about on the first tools/list that sees them).'
        ),
        examples=[['get_issue', 'list_issues']],
    )
    allowed_prompts: list[str] | None = Field(
        default=None,
        description=(
            'Allowlist of upstream prompt names this server may expose. Names '
            "are the upstream's own, i.e. before the '{alias}__' prefix is "
            'applied. Same null/empty semantics as allowed_tools.'
        ),
        examples=[['review_pr']],
    )
    allowed_resources: list[str] | None = Field(
        default=None,
        description=(
            'Allowlist of upstream resource URIs this server may expose. URIs '
            "are the upstream's own, i.e. before the gateway wraps them for "
            'routing. Same null/empty semantics as allowed_tools.'
        ),
        examples=[['https://api.example.com/docs/readme']],
    )

    def tool_allowed(self, name: str) -> bool:
        """Whether ``name`` (an upstream tool name) may be exposed or called."""
        return _allowed(self.allowed_tools, name)

    def prompt_allowed(self, name: str) -> bool:
        """Whether ``name`` (an upstream prompt name) may be exposed or fetched."""
        return _allowed(self.allowed_prompts, name)

    def resource_allowed(self, uri: str) -> bool:
        """Whether ``uri`` (an upstream resource URI) may be exposed or read."""
        return _allowed(self.allowed_resources, uri)

    @field_validator('allowed_tools', 'allowed_prompts', 'allowed_resources')
    @classmethod
    def validate_allowlist(
        cls, v: list[str] | None, info: ValidationInfo
    ) -> list[str] | None:
        """Strip, reject blanks and dedupe, keeping ``None`` distinct from ``[]``.

        Matching is exact and case-sensitive: MCP tool, prompt and resource
        identifiers are, so normalizing case here would silently widen the
        allowlist.
        """
        if v is None:
            return v
        normalized: list[str] = []
        for entry in v:
            stripped = entry.strip()
            if not stripped:
                raise ValueError(f'{info.field_name} entries must not be empty.')
            if stripped not in normalized:
                normalized.append(stripped)
        return normalized

    @field_validator('alias')
    @classmethod
    def validate_alias(cls, v: str) -> str:
        alias = v.strip()
        if not alias:
            raise ValueError('MCP server alias must not be empty.')
        if any(c.isspace() for c in alias):
            raise ValueError(f"MCP server alias '{alias}' must not contain whitespace.")
        if ALIAS_TOOL_SEPARATOR in alias:
            raise ValueError(
                f"MCP server alias '{alias}' must not contain '{ALIAS_TOOL_SEPARATOR}' "
                '(reserved as the alias/tool separator).'
            )
        return alias


class McpHttpServer(McpServerBase):
    transport: Literal['streamable_http'] = 'streamable_http'
    url: str = Field(
        ...,
        description='Upstream Streamable HTTP endpoint of the MCP server.',
        examples=['https://api.githubcopilot.com/mcp/'],
    )
    headers: dict[str, str] | None = Field(
        default=None,
        description=(
            'Static headers sent to the upstream server. Sensitive values must '
            'use !secret references.'
        ),
    )
    forward_headers: list[str] | None = Field(
        default=None,
        description=(
            'Allowlist of upstream header names fillable from the inbound '
            'client request (case-insensitive). A client supplies the value '
            'either as the plain header itself or, server-specifically, as '
            "'x-mcp-{alias}-{header}'. 'authorization' is fillable only via "
            'the prefixed form — the plain inbound Authorization header '
            'carries the gateway API key and is never forwarded.'
        ),
    )

    @field_validator('forward_headers')
    @classmethod
    def validate_forward_headers(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        normalized: list[str] = []
        for name in v:
            lowered = name.strip().lower()
            if not lowered:
                raise ValueError('forward_headers entries must not be empty.')
            if lowered in FORBIDDEN_FORWARD_HEADERS:
                raise ValueError(
                    f"forward_headers must not contain '{lowered}': "
                    'transport-level and message-framing headers are managed '
                    'by the gateway.'
                )
            if lowered not in normalized:
                normalized.append(lowered)
        return normalized


class McpStdioServer(McpServerBase):
    transport: Literal['stdio'] = 'stdio'
    command: str = Field(
        ...,
        description='Executable used to spawn the MCP server subprocess.',
        examples=['python'],
    )
    args: list[str] = Field(
        default_factory=list,
        description='Arguments passed to the command.',
    )
    env: dict[str, str] | None = Field(
        default=None,
        description=(
            'Environment variables for the subprocess, merged over the SDK '
            'default environment. Sensitive values must use !secret references.'
        ),
    )
    cwd: str | None = Field(
        default=None,
        description='Working directory for the subprocess.',
    )


AnyMcpServer = Annotated[
    Union[McpHttpServer, McpStdioServer],
    Field(discriminator='transport'),
]
