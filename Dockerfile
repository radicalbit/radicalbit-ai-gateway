# ============================================
# Stage 1: UI Dependencies Installation
# ============================================
FROM node:20-bookworm-slim AS ui-install

WORKDIR /app

# Enable corepack for yarn management
RUN corepack enable && corepack prepare yarn@1.22.21 --activate

# Copy dependency files first for better caching
COPY ./ui/package.json ./ui/yarn.lock ./

# Install dependencies with simplified retry logic
RUN yarn config set network-timeout 1200000 && \
    yarn install --frozen-lockfile

# Copy source code
COPY ./ui/src ./src
COPY ./ui/public ./public
COPY ./ui/*.js ./ui/*.cjs ./ui/*.html ./

# ============================================
# Stage 2: UI Build
# ============================================
FROM node:20-bookworm-slim AS ui-build

WORKDIR /app

# Reuse everything from ui-install (corepack setup, node_modules, source code)
COPY --from=ui-install /app /app

# Build production bundle
RUN echo "VITE_GATEWAY_ORIGIN=''" > .env.production && \
    yarn build:prod

# ============================================
# Stage 3: Final Runtime Image
# ============================================
FROM python:3.11.13-slim

ENV HTTP_INTERFACE=0.0.0.0
ENV HTTP_PORT=9000
ENV PYTHONUNBUFFERED=1

EXPOSE 9000

WORKDIR /radicalbit_ai_gateway

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc libpq-dev python3-dev curl tini && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY ./gateway/uv.lock ./gateway/pyproject.toml ./
RUN pip install --no-cache-dir --no-compile uv==0.9.27 && \
    uv export --no-hashes --format requirements-txt --group ahds > requirements.txt && \
    pip install --no-cache-dir --no-compile -r requirements.txt && \
    rm -f requirements.txt uv.lock pyproject.toml && \
    rm -rf /root/.cache

# Copy application code
COPY ./gateway/radicalbit_ai_gateway ./radicalbit_ai_gateway
COPY --from=ui-build /app/dist /radicalbit_ai_gateway/static

# Configure entrypoint
COPY ./gateway/entrypoint.sh .
RUN chmod +x ./entrypoint.sh

ENTRYPOINT ["tini", "-v", "--", "./entrypoint.sh"]
