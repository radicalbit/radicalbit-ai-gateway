# Radicalbit AI Gateway – Developer Guide

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager
- Docker + Docker Compose — for support services (Postgres, Valkey, ClickHouse)

---

## 1. Install dependencies

From the `gateway/` directory:

```bash
cd gateway
uv sync
uv pip install -e .
```

---

## 2. Start support services

From the project root, start the full stack. The compose gateway runs on port 9000; the local dev server runs on port 8000 — no conflict.

```bash
docker compose up -d
```

---

## 3. Configure environment

Create `gateway/.env.dev` with the connection details matching the compose services:

```dotenv
# Database
DB_TYPE=postgresql
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PWD=postgres
DB_NAME=radicalbit
DB_SCHEMA=public

# Cache / broker
REDIS_HOST=localhost
REDIS_PORT=6379
CELERY_BROKER_URL=redis://localhost:6379/0

# ClickHouse
CLICKHOUSE_DB_HOST=localhost
CLICKHOUSE_DB_PORT=9002
CLICKHOUSE_DB_USER=default
CLICKHOUSE_DB_PWD=default
CLICKHOUSE_DB_NAME=default
CLICKHOUSE_DB_SCHEMA=default

# Tracing
COLLECTOR_BASE_URL=http://localhost:4318/v1/traces

# Plugins
ENABLED_PLUGINS=

# CORS
CORS_ALLOW_ORIGINS='["http://localhost:5173"]'
CORS_ALLOW_CREDENTIALS=True
```

Add your LLM provider keys to `gateway/secrets.yaml`:

```yaml
OPENAI_API_KEY: sk-your-key-here
```

---

## 4. Start the gateway

The gateway runs on **port 8000** by default — separate from the compose stack which uses port 9000.

```bash
cd gateway
uv run --env-file=.env.dev radicalbit-ai-gateway serve --port 8000 --secrets ../secrets.yaml
```

Gateway is available at `http://localhost:8000`.

### CLI options

| Flag | Default | Description |
|------|---------|-------------|
| `--port` / `-p` | `8000` | HTTP port |
| `--host` | `127.0.0.1` | Bind address |
| `--secrets` / `-s` | `secrets.yaml` | Path to secrets file |
| `--debug` / `-d` | off | Enable debug mode |
| `--log` | `plain` | Log format: `plain` \| `json` \| `color` |
| `--metrics-port` | `8001` | Prometheus metrics port |
| `--workers` / `-w` | `1` | Uvicorn worker count (keep 1 for dev) |

---

## 5. Start the UI

From the `ui/` directory:

```bash
cd ui
yarn install
yarn start:local
```

UI runs at `http://localhost:5173`. By default it points to the gateway at `http://localhost:9000` (compose stack).

To point it at the local dev server instead, edit `ui/.env.development`:

```dotenv
VITE_GATEWAY_ORIGIN=http://localhost:8000
```

---

## 6. Teardown

Stop and remove all compose containers and volumes:

```bash
docker compose down -v
```
