default: start

compose := "docker compose"

# Start services (uses cached layers)
start:
    {{ compose }} up

# Rebuild images without Docker cache (keeps data)
rebuild:
    {{ compose }} build
    {{ compose }} up

# Reset — wipes volumes (DB, cache, ClickHouse), rebuilds without cache
reset:
    {{ compose }} down -v
    {{ compose }} build
    {{ compose }} up

# Purge — removes images + volumes, rebuilds everything from scratch
purge:
    {{ compose }} down -v --rmi all
    {{ compose }} build --no-cache
    {{ compose }} up

# Stop all services (keeps volumes)
stop:
    {{ compose }} down

# Stop all services and remove volumes
stopv:
    {{ compose }} down -v --remove-orphans

# Run the gateway from source; needs `just start` first. Second instance: just dev 8080 8081
dev port="8000" metrics="8001" log="color":
    cd gateway/ && uv run --env-file=.env.dev radicalbit-ai-gateway serve \
        --port {{ port }} --metrics-port {{ metrics }} --log {{ log }} \
        --secrets ../secrets.dev.yaml

# Install UI dependencies (node_modules)
ui-install:
    cd ui/ && yarn install

# Run the UI dev server on :5173, pointed at `just dev`. Compose: just ui http://localhost:9000
ui gateway="http://localhost:8000":
    cd ui/ && [ -d node_modules ] || yarn install
    cd ui/ && VITE_GATEWAY_ORIGIN={{ gateway }} yarn start:local

# Run tests for all plugins
test:
    cd gateway/ && uv run pytest
