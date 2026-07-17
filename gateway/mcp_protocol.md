# MCP Protocol Reference — Gateway MCP Proxy (tools-only)

**Purpose.** Implementation contract for the gateway's MCP proxy. The gateway is both an **inbound
MCP server** (clients connect to it) and an **outbound MCP client** (it forwards to upstream servers).
Both sides use **Streamable HTTP** transport and the **tools** capability only.

**Protocol revisions supported: `2025-06-18` and `2025-11-25`** (the latter is current/latest).
The gateway negotiates per client: `initialize` echoes the client's requested version when it is
one of the two; otherwise it answers with `2025-11-25`. Version strings are `YYYY-MM-DD` and only
bump on backwards-incompatible changes. The outbound side (SDK `mcp` 1.x) already negotiates both
revisions with upstream servers automatically.

**Scope — implement:** `initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call`.
**Out of scope:** `resources/*`, `prompts/*`, logging, completion, sampling, roots,
`tools/list_changed`, sessions/resumability, Tasks.

---

## 1. Transport (Streamable HTTP)

Single endpoint path — for us `POST /mcp/{project_name}/{route_name}` (plus GET/DELETE). The gateway runs
**stateless**: no `Mcp-Session-Id` issued, every POST self-contained, always answer with
`application/json` (never open SSE).

| Method | Behavior in our proxy |
|---|---|
| **POST** | Client sends one JSON-RPC message. Requests → `200` + `application/json` JSON-RPC response. Notifications (e.g. `notifications/initialized`) → `202 Accepted`, empty body. |
| **GET** | We offer no server→client SSE stream → **`405 Method Not Allowed`**. |
| **DELETE** | Stateless, no session to end → `405` (or `204` no-op). |

**Request headers (client → gateway on POST):**
- `Accept: application/json, text/event-stream` — client MUST offer both (we tolerate/require it, but
  only ever return JSON).
- `Content-Type: application/json` (UTF-8).
- `MCP-Protocol-Version: 2025-11-25` (or `2025-06-18`) — MUST be present on all requests **after**
  `initialize`; both supported revisions are accepted. If absent, assume `2025-03-26`. If present
  but unsupported → **`400`**.

**Security:** validate `Origin` on every request → **`403`** if invalid (DNS-rebinding defense).
Require the gateway's `sk-rb-*` bearer.

**Status codes:** `200` (request response), `202` (notification accepted), `400` (malformed / bad
protocol version), `401` (missing/invalid bearer), `403` (bad Origin / key not bound to the
route), `404` (unknown project or route), `405` (GET/DELETE).

---

## 2. Methods

### `initialize` (request)
Client params: `protocolVersion`, `capabilities`, `clientInfo{name,version,...}`.
Gateway result — echo the client's requested version if it is `2025-06-18` or `2025-11-25`
(else return our latest, `2025-11-25`), advertise **tools only**:
```json
{ "jsonrpc":"2.0", "id":1, "result":{
  "protocolVersion":"2025-11-25",
  "capabilities": { "tools": {} },
  "serverInfo": { "name":"radicalbit-ai-gateway-mcp", "version":"<gw-version>" }
}}
```
> No `listChanged` — a JSON-only stateless server can't push notifications, so must not advertise it.
> Version negotiation is a **successful result** carrying a version, not an error. (Only a totally
> unusable version warrants `-32602` "Unsupported protocol version" with
> `data:{supported:[...],requested:"..."}`.)

### `notifications/initialized` (notification, no `id`)
```json
{ "jsonrpc":"2.0", "method":"notifications/initialized" }
```
Gateway → **`202 Accepted`**, empty body. No response object.

### `ping` (request)
```json
// req
{ "jsonrpc":"2.0", "id":"123", "method":"ping" }
// res
{ "jsonrpc":"2.0", "id":"123", "result":{} }
```

### `tools/list` (request)
Params: optional `cursor`. Gateway **fans out to the route's upstreams**, prefixes each tool
name `"{alias}__{tool}"`, merges, returns:
```json
{ "jsonrpc":"2.0", "id":1, "result":{
  "tools":[
    { "name":"github__get_issue",
      "title":"Get Issue",
      "description":"Fetch a GitHub issue",
      "inputSchema":{ "type":"object",
        "properties":{ "id":{ "type":"string" } },
        "required":["id"] } }
  ],
  "nextCursor":"optional"
}}
```
Tool object: `name` (required; `A-Za-z0-9_-.`, ≤128, unique), `title?`, `description?`, `inputSchema`
(required — valid JSON Schema 2020-12, never null), `outputSchema?`, `annotations?`, `icons?`,
`execution?`. We pass upstream fields through verbatim except the prefixed `name`.

### `tools/call` (request)
```json
{ "jsonrpc":"2.0", "id":2, "method":"tools/call",
  "params":{ "name":"github__get_issue", "arguments":{ "id":"42" } } }
```
Gateway splits `name` on the first `__` → alias `github`, forwards `get_issue` + `arguments` to that
upstream, returns its `CallToolResult` unchanged:
```json
{ "jsonrpc":"2.0", "id":2, "result":{
  "content":[ { "type":"text", "text":"..." } ],
  "isError":false
}}
```
`content[]` block types: `text`; `image`/`audio` (`data` base64 + `mimeType`); `resource_link`
(`uri`,`name`,...); embedded `resource`. Optional top-level `structuredContent` (with a mirrored
`text` block for back-compat).

---

## 3. Error handling — two distinct mechanisms

**Protocol errors → JSON-RPC `error`** (envelope/routing problems):
```json
{ "jsonrpc":"2.0", "id":3, "error":{ "code":-32602, "message":"Unknown tool: bad__name" } }
```
- `-32700` parse · `-32600` invalid request · `-32601` method not found · `-32602` invalid params
  (unknown tool prefix, unknown upstream, bad args shape) · `-32603` internal · `-32000` (server range)
  for upstream connection/timeout failures (sanitized message; log full detail).

**Tool-execution errors → successful result with `isError:true`** (things the model might recover
from — upstream tool raised, bad inputs). Pass an upstream `isError:true` through unchanged:
```json
{ "jsonrpc":"2.0", "id":4, "result":{
  "content":[ { "type":"text", "text":"Upstream error: rate limited" } ],
  "isError":true
}}
```

**JSON-RPC framing:** `id` is string|int, never null, never reused; notifications carry no `id` and
get no response.

---

## 4. Outbound (gateway → upstream)

Same methods via the official `mcp` SDK client (Streamable HTTP, ephemeral session): `initialize` →
(`tools/list` | `tools/call`) → close. Inject resolved `!secret` auth headers per upstream.
`asyncio.wait_for(timeout)` per op; map failures to the errors above.

---

## 5. Minimal proxy checklist
1. Single `/mcp/{project}/{route}` endpoint; validate `Origin` (403); require bearer (401);
   unknown project/route → 404; key's group not bound to the route → 403.
2. POST does the work; GET → 405; DELETE → 405/204.
3. Accept both content types on POST; **always respond `application/json`**; never open SSE.
4. Stateless — issue no `Mcp-Session-Id`; accept `MCP-Protocol-Version` after init (400 on
   unsupported; default `2025-03-26` if absent).
5. `initialize` → `capabilities:{tools:{}}`, echo/negotiate version; `notifications/initialized` → 202;
   `ping` → `{}`.
6. `tools/list` — fan out, prefix `alias__tool`, tolerate one-upstream failure (partial list).
   `tools/call` — resolve prefix, forward, pass result through.
7. `isError:true` for tool failures; `-32601`/`-32602` for unknown method/tool/bad params.

---

## Forward compatibility — the `2026-07-28` revision (Release Candidate)

As of 2026-07-14 the current/final revision is **`2025-11-25`** (what this doc targets). A next revision
**`2026-07-28`** exists only as a **Release Candidate**, scheduled to publish 2026-07-28; the SDK v2 that
implements it is still **beta** (`mcp 2.0.0b1`; stable `pip install mcp` = `1.x`). **We build v1 against
`2025-11-25` + SDK `mcp>=1.13,<2`** — do not target the RC/beta yet.

Our proxy is **stateless by design**, which aligns with the direction of `2026-07-28` (it removes the
`initialize`/`initialized` handshake in favor of self-describing requests and a `server/discover` probe).
A v2 client using `mode='auto'` probes `server/discover` then **falls back to the legacy `initialize`
handshake**, so a `2025-11-25` proxy keeps interoperating with newer clients.

Fast-follow to add once `2026-07-28` is final and SDK v2 is GA (additive, not a rewrite):
- Implement `server/discover` and read protocol/capabilities from `params._meta` (keep `initialize` for
  legacy clients).
- Honor new required Streamable HTTP headers `Mcp-Method` / `Mcp-Name`.
- Emit optional `ttlMs` / `cacheScope` on `tools/list`.
- Error code: missing-resource `-32002` → standard `-32602` (minimal impact; tools-only).
- Outbound SDK v2: `streamablehttp_client` → `streamable_http_client`, pass your own `httpx.AsyncClient`,
  handle the 2-tuple return (session-id callback removed).

Sources: https://modelcontextprotocol.io/specification/versioning ·
https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/ ·
https://blog.modelcontextprotocol.io/posts/sdk-betas-2026-07-28/ ·
https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/migration.md

## Sources (MCP spec revision 2025-11-25)
- Versioning: https://modelcontextprotocol.io/specification/versioning
- Transports: https://modelcontextprotocol.io/specification/2025-11-25/basic/transports
- Lifecycle: https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle
- Base/JSON-RPC: https://modelcontextprotocol.io/specification/2025-11-25/basic
- Ping: https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/ping
- Tools: https://modelcontextprotocol.io/specification/2025-11-25/server/tools
- Schema (truth): https://github.com/modelcontextprotocol/specification/blob/main/schema/2025-11-25/schema.ts
