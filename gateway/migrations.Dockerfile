FROM python:3.11.13-slim

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir --no-compile uv==0.9.27

# Copy dependency files
COPY uv.lock pyproject.toml ./

# Install only migrations dependencies using uv
RUN uv pip install --no-cache --system --group migrations && \
    rm -rf /root/.cache

# Copy alembic config and migrations
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY radicalbit_ai_gateway ./radicalbit_ai_gateway

CMD ["alembic", "upgrade", "head"]
