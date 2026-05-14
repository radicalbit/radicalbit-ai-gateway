# Vite Proxy, SPA Routing & Browser Navigation — A Deep Dive

## Table of Contents

- [1. What is vite.config.js](#1-what-is-viteconfigjs)
- [2. The Vite Dev Proxy](#2-the-vite-dev-proxy)
- [3. How the Proxy Solves CORS](#3-how-the-proxy-solves-cors)
- [4. Beyond CORS — Other Proxy Use Cases](#4-beyond-cors--other-proxy-use-cases)
- [5. How Route Priority Works in FastAPI](#5-how-route-priority-works-in-fastapi)
- [6. The Two HTTP Clients Living in Your Browser](#6-the-two-http-clients-living-in-your-browser)
- [7. The Proxy is a Dumb Pipe — How 302 Redirects Are Handled](#7-the-proxy-is-a-dumb-pipe--how-302-redirects-are-handled)
- [8. Why OIDC Cannot Work Through fetch/axios](#8-why-oidc-cannot-work-through-fetchaxios)
- [9. The Experiment — Proof by Failure](#9-the-experiment--proof-by-failure)
- [10. Environment Comparison](#10-environment-comparison)

---

## 1. What is vite.config.js

`vite.config.js` is the configuration file for Vite, the build tool and dev server used by the React frontend. It controls two distinct phases:

- **Development** (`vite dev`) — runs a local dev server with hot-module replacement (HMR)
- **Build** (`vite build`) — produces a static production bundle (HTML/JS/CSS)

### Key sections

```js
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd());
  const backendUrl = env.VITE_BACKEND_URL || 'http://localhost:9000';

  return {
    plugins: [react(), svgr({ include: '**/*.svg' })],
    server: {
      port: 5173,                          // Dev server port (localhost only)
      proxy: {
        '/auth': { target: backendUrl },   // Proxy (localhost only)
      },
    },
    resolve: {
      alias: { '@Api': '...', ... },       // Path aliases (dev + build)
    },
  };
});
```

- **`plugins`**: React Fast Refresh + SVG-as-component support. Used in both dev and build.
- **`server.port`**: The Vite dev server port. Only relevant during `vite dev` on localhost.
- **`server.proxy`**: Forwards matching requests to the backend. Only active during `vite dev`.
- **`resolve.alias`**: Path shortcuts like `@Api`, `@Components`. Used in both dev and build.

**The entire `server` block (port + proxy) is exclusively for local development.** It has zero effect on dev/prod deployments where the app is served by the gateway.

---

## 2. The Vite Dev Proxy

### The problem it solves

During local development, two separate servers are running:

| Server | URL | Serves |
|---|---|---|
| Vite dev server | `http://localhost:5173` | React app (with HMR) |
| Gateway backend | `http://localhost:9000` | API + auth endpoints |

These are **two different origins** (different ports = different origins). This creates problems with CORS, cookies, and routing.

### How it works

The proxy intercepts **any HTTP request** arriving at the Vite dev server where the path matches a configured prefix. This includes:

- Full page navigations (`window.location.href = '/auth/login'`)
- AJAX/fetch calls (`fetch('/auth/logout')`)
- Asset requests, form submissions, etc.

```
Browser (localhost:5173)
    |
    |  GET /auth/login  (same-origin request, no CORS)
    v
Vite dev server (localhost:5173)
    |
    |  GET /auth/login  (server-to-server, CORS doesn't apply)
    v
Gateway backend (localhost:9000)
    |
    |  response
    v
Vite dev server
    |
    |  proxied response
    v
Browser
```

The browser never knows `localhost:9000` exists. As far as it's concerned, the request went to `localhost:5173` and came back from `localhost:5173`.

### Why it's not needed in dev/prod

In deployed environments, the UI is bundled as static files **inside** the gateway container (see the Dockerfile — `COPY --from=ui-build /app/dist /radicalbit_ai_gateway/static`). The gateway serves both API and UI on the same origin (port 9000). No cross-origin problem, no proxy needed.

---

## 3. How the Proxy Solves CORS

### What is CORS

CORS (Cross-Origin Resource Sharing) is a **browser-only** security mechanism. When JavaScript code at one origin (e.g., `localhost:5173`) makes an HTTP request to a different origin (e.g., `localhost:9000`), the browser:

1. Sends a preflight `OPTIONS` request to the target
2. Checks if the response includes `Access-Control-Allow-Origin` matching the page's origin
3. If not, **blocks the response** — JavaScript never sees it

Important: CORS only applies to JavaScript-initiated requests (XMLHttpRequest, fetch). It does NOT apply to browser navigations or server-to-server HTTP calls.

### How the proxy bypasses CORS

With the proxy, frontend code uses **relative URLs**:

```js
fetch('/auth/logout')  // resolves to http://localhost:5173/auth/logout
```

The browser sees this as a same-origin request (page is on `localhost:5173`, request goes to `localhost:5173`). No CORS check happens. The Vite proxy then forwards the request to `localhost:9000` server-to-server, which is not subject to CORS.

Without the proxy, the code would need to call `http://localhost:9000/auth/logout` directly — a cross-origin request that the browser would block (unless the backend sends CORS headers).

---

## 4. Beyond CORS — Other Proxy Use Cases

### Routing

Without the proxy, navigating to `http://localhost:5173/auth/login` would hit Vite's SPA fallback. Vite would serve `index.html`, React would load, and React Router's catch-all would redirect to `/routes`. The request would **never reach the backend**. The proxy ensures `/auth/*` paths bypass the SPA and hit the real backend endpoint.

### Cookie scoping

Cookies are bound to an origin. If the backend at `localhost:9000` sets a cookie (like the `access_token` HttpOnly cookie), the browser won't send it back on requests to `localhost:5173`. With the proxy, everything is `localhost:5173` from the browser's perspective, so cookies work correctly.

### Single entry point

The frontend code can use **relative paths** (`/auth/logout` instead of `http://localhost:9000/auth/logout`), matching the production behavior. Less environment-specific code, fewer bugs.

### Multiple backends

You can route different path prefixes to different services, mimicking a production reverse proxy:

```js
proxy: {
  '/auth': { target: 'http://localhost:9000' },
  '/analytics': { target: 'http://localhost:8080' },
}
```

### Header/path manipulation

The proxy supports `changeOrigin`, `rewrite`, custom headers:

```js
proxy: {
  '/api': {
    target: 'http://backend:9000',
    rewrite: (path) => path.replace(/^\/api/, '/v2'),
  }
}
```

---

## 5. How Route Priority Works in FastAPI

### It's NOT "backend first, then SPA"

When a request arrives at the gateway, FastAPI matches routes in **registration order**. The first matching route wins. Looking at `server.py`:

```
1. load_plugins(app)                          → line 308  (registers /auth/*)
2. app.include_router(DashboardRoute...)      → line 321  (registers /public/api/v1/*)
3. app.include_router(ConfigsRoute...)        → line 328
4. app.include_router(KeyRoute...)            → line 345
5. app.include_router(GroupRoute...)          → line 346
6. @app.get('/health')                        → line 412
7. @app.post('/v1/chat/completions')          → line 474
8. app.mount('/assets', StaticFiles(...))     → line 696
9. @app.get('/{rest_of_path:path}')           → line 698  ← catch-all, registered LAST
```

### Example: `GET /auth/login`

```
→ Matches plugin route registered at step 1
→ OIDC plugin handles it, returns 302 to Keycloak
→ Catch-all is never reached
```

### Example: `GET /routes`

```
→ No plugin route matches
→ No API route matches
→ No explicit endpoint matches
→ No static file matches
→ Catch-all at step 9 matches
→ Serves index.html → React loads → React Router renders RoutesList
```

### Example: `GET /public/api/v1/nonexistent`

```
→ No matching API endpoint
→ Falls through to catch-all
→ rest_of_path starts with "public/api/" → returns 404 (not index.html)
→ Prevents the SPA from handling broken API URLs
```

The SPA (React) only gets involved when **no server-side route matched**.

---

## 6. The Two HTTP Clients Living in Your Browser

This is the most important concept for understanding why certain things work one way and not another.

### Client 1: The Browser Navigation Engine

This is the browser itself — the full rendering pipeline. Triggered by:

- Typing a URL in the address bar
- Clicking `<a href="...">` links
- `window.location.href = '...'`
- Form submissions

When it receives a response, it:

- Updates the URL bar
- Follows redirects (302) automatically
- **Parses HTML into a DOM**
- **Loads and applies CSS**
- **Loads and executes `<script>` tags**
- **Renders the page visually**
- Attaches event listeners
- The user sees and interacts with the result

**CORS does not apply** to browser navigations.

### Client 2: The JavaScript HTTP Client (XMLHttpRequest / fetch / axios)

This is code running **inside** a page. Triggered by:

- `axios.get(...)`, `fetch(...)`, `XMLHttpRequest`
- RTKQ's `baseQuery` → `customBaseQuery` → `axios`

When it receives a response, it:

- Stores the raw bytes in a JavaScript variable
- Does **NOT** parse HTML
- Does **NOT** execute scripts
- Does **NOT** render anything
- Does **NOT** change the URL bar
- The user sees **nothing**

**CORS applies** to all JavaScript-initiated requests.

### The difference in one sentence

**`axios` is a data fetcher** — it gets raw bytes for your JavaScript to process.
**Browser navigation is a page renderer** — it builds a full interactive page and puts the user in front of it.

---

## 7. The Proxy is a Dumb Pipe — How 302 Redirects Are Handled

A natural question arises: the proxy makes a server-to-server GET to the backend, and the backend returns a 302 redirect. Doesn't the proxy follow that redirect, just like axios would?

**No.** The Vite proxy (powered by `http-proxy` under the hood) is a **transparent reverse proxy**. It relays the response **as-is** back to whoever made the request, without interpreting it. It does not follow redirects.

### The exact flow with `window.location.href`

```
1. Browser navigates to localhost:5173/auth/login     (browser navigation)
2. Request arrives at Vite dev server
3. Vite proxy matches /auth → forwards GET to localhost:9000/auth/login  (server-to-server)
4. Backend responds: 302 Location: http://keycloak:8080/realms/acme/...
5. Proxy receives the 302
6. Proxy passes the 302 back to the browser UNCHANGED (does NOT follow it)
7. Browser navigation engine receives the 302
8. Browser follows the redirect → navigates to Keycloak
9. Browser renders the Keycloak login page → user can interact
```

The proxy is just a relay. It doesn't care what the status code is — 200, 302, 404, 500 — it passes everything through.

### Why this is different from axios

When `axios.get('/auth/login')` goes through the same proxy, the proxy behaves **identically** — it relays the 302 back. But the **consumer** is different:

| Scenario | Proxy behavior | Who receives the 302 | What happens next |
|---|---|---|---|
| `window.location.href` + proxy | Relays 302 unchanged | **Browser navigation engine** | Follows redirect as page navigation, no CORS, renders the page |
| `axios.get()` + proxy | Relays 302 unchanged | **XMLHttpRequest** | Automatically follows redirect as JS request, CORS applies, result is raw bytes |

The proxy does the same thing in both cases. The difference is entirely in **what's on the other side of the proxy**: the browser engine (which renders pages) vs XMLHttpRequest (which stores bytes in a variable).

### Proxy intercept vs browser render — what comes first?

When `window.location.href = '/auth/login'` executes, the browser sends an HTTP request to `localhost:5173/auth/login` **before** rendering anything. The Vite dev server is a web server — it receives the raw HTTP request and checks its proxy rules first. If the path matches `/auth`, the request is forwarded to the backend. The browser has not attempted to render anything yet — it's waiting for a response.

If there were no proxy match, Vite would fall back to serving `index.html` (SPA fallback), and only then would the browser render the page and React Router would take over.

```
Browser sends GET /auth/login to localhost:5173
    │
    ├─ Vite proxy: does path match /auth?
    │   YES → forward to backend, return response to browser
    │   NO  → serve index.html → browser renders React → React Router handles the path
```

The proxy always wins over the SPA fallback because the proxy operates at the HTTP server level, before any HTML is served or rendered.

---

## 8. Why OIDC Cannot Work Through fetch/axios

The OIDC Authorization Code flow is a chain of browser redirects:

```
Your app → /auth/login → 302 → Keycloak login page → user authenticates
→ Keycloak redirects → /auth/callback?code=... → backend sets cookies → 302 → /
```

This chain **requires browser navigation** because:

1. The user must **see and interact** with the Keycloak login form
2. Keycloak sets its **own session cookies** on its domain
3. The final redirect carries the authorization code in the URL
4. Each 302 hop must be rendered, not just fetched as data

If you use `axios.get('/auth/login')`:

1. The proxy forwards to the backend
2. Backend returns 302 → Keycloak
3. Axios follows the 302 silently (XMLHttpRequest always follows redirects, you can't prevent it)
4. Now axios tries to GET the Keycloak URL — **CORS blocks it** (Keycloak doesn't send `Access-Control-Allow-Origin` for your localhost)
5. Even if CORS were somehow bypassed, you'd get the Keycloak HTML login form as a **raw string in a variable** — the user would never see it

That's why `src/api/utils.js` correctly uses `window.location.href`:

```js
// On 401, hand off from JavaScript HTTP client to browser navigation engine
if (err.response?.status === 401 && !url.startsWith('/auth')) {
  window.location.href = `${window.location.origin}/auth/login`;
}
```

This is the **hand-off point**: "JavaScript can't handle this anymore; the browser itself needs to take over."

---

## 9. The Experiment — Proof by Failure

To verify all of the above, we replaced `window.location.href` with `axios.get('/auth/login')` in `utils.js`. Upon triggering a 401:

### What Chrome showed in the console

```
Access to XMLHttpRequest at 'http://keycloak:8080/realms/acme/protocol/openid-connect/auth?...'
(redirected from 'http://localhost:5173/auth/login')
from origin 'http://localhost:5173' has been blocked by CORS policy:
No 'Access-Control-Allow-Origin' header is present on the requested resource.
```

### What happened step by step

```
1. axios.get('/auth/login')
2. → Vite proxy forwards to localhost:9000/auth/login
3. → Backend returns 302 → http://keycloak:8080/realms/acme/...
4. → XMLHttpRequest automatically follows the 302
5. → Browser sends GET to keycloak:8080
6. → CORS check: origin is localhost:5173, target is keycloak:8080 → DIFFERENT ORIGIN
7. → Keycloak's response has no Access-Control-Allow-Origin header
8. → Browser BLOCKS the response
9. → Axios gets a network error
10. → User sees nothing. App is stuck.
```

Two layers of failure:
- **Layer 1 (CORS)**: The cross-origin redirect to Keycloak is blocked
- **Layer 2 (even if CORS passed)**: The Keycloak HTML would be a string in a variable, never rendered

---

## 10. Environment Comparison

| Aspect | Localhost (`vite dev`) | Dev / Prod (deployed) |
|---|---|---|
| **Frontend server** | Vite dev server (port 5173) | Gateway serves static files (port 9000) |
| **Backend server** | Gateway (port 9000) | Same gateway (port 9000) |
| **Same origin?** | No (5173 vs 9000) | Yes (single server) |
| **Proxy needed?** | Yes | No |
| **CORS problem?** | Yes, without proxy | No, same origin |
| **Cookie scoping?** | Solved by proxy | Naturally correct |
| **API base URL** | `http://localhost:9000/public/api/v1` | Relative: `/public/api/v1` |
| **Auth flow** | Proxy forwards `/auth/*` to backend | Gateway handles `/auth/*` directly |
| **SPA fallback** | Vite serves `index.html` for unknown paths | Gateway catch-all serves `index.html` |

### Env files

| File | Used when | VITE_BACKEND_URL |
|---|---|---|
| `.env.development` | `vite dev` (localhost) | `http://localhost:9000` |
| `.env.dev` | `vite dev` pointed at dev server | `http://ai-gateway.dev.radicalbit.io:9000` |
| `.env.production` | `vite build` (Docker) | Not set (relative URLs) |
