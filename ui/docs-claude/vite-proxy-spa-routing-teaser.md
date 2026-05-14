# Vite Proxy, SPA Routing & Browser Navigation — TL;DR

Your browser has **two independent HTTP clients**: the navigation engine (renders pages, follows redirects visually, ignores CORS) and JavaScript's fetch/axios (gets raw bytes into a variable, invisible to the user, subject to CORS).

During local development, your React app runs on `localhost:5173` while the backend runs on `localhost:9000` — two different origins. The **Vite dev proxy** makes the browser think everything is on `localhost:5173` by intercepting requests matching `/auth` and forwarding them server-to-server to the backend. This solves CORS, cookie scoping, and routing in one shot.

In production, there's no proxy because there's no problem: the gateway serves both the API and the UI static files on the same origin.

The OIDC login flow (`/auth/login`) **must** use `window.location.href` (browser navigation), not `fetch`/`axios`. Why? Because the backend returns a 302 redirect to Keycloak's login page. The user needs to **see and interact** with that page. Axios would follow the redirect silently, hit a CORS wall (Keycloak doesn't allow your origin), and even if it got through, the HTML would be a string in a variable — never rendered, never interactive.

FastAPI routes are matched by **registration order**. Plugin routes (`/auth/*`) are registered first, API routes next, and the SPA catch-all (`/{rest_of_path:path}` serving `index.html`) is registered **last**. This ensures backend endpoints always win over the frontend fallback.

**Read the [full deep dive](./vite-proxy-spa-routing-deep-dive.md) for diagrams, code examples, and a real experiment proving why axios fails.**
