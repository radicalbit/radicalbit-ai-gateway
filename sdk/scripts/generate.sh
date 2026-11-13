#!/usr/bin/env bash
# Regenerate the SDK from the gateway app, in three steps:
#   1. export the SDK spec (openapi.json) from the gateway app;
#   2. datamodel-codegen: the models (src/radicalbit_gateway/models.py),
#      options in pyproject.toml [tool.datamodel-codegen];
#   3. generator/generate_client.py: the client methods
#      (src/radicalbit_gateway/_resources.py).
# Then ruff formats both. Every tool is pinned in pyproject.toml/uv.lock, so
# the output is deterministic: running it twice yields no diff.
set -euo pipefail

SDK="$(cd "$(dirname "$0")/.." && pwd)"
GATEWAY="$SDK/../gateway"
GENERATED=(src/radicalbit_gateway/models.py src/radicalbit_gateway/_resources.py)

(cd "$GATEWAY" && uv run --quiet python scripts/export_sdk_spec.py --out "$SDK/openapi.json")

cd "$SDK"
uv sync --quiet
uv run --quiet datamodel-codegen
uv run --quiet python generator/generate_client.py
uv run --quiet ruff check --fix-only --quiet "${GENERATED[@]}"
uv run --quiet ruff format --quiet "${GENERATED[@]}"
