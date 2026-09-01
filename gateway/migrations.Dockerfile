FROM python:3.11.13-slim

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir --no-compile uv==0.9.27

# setuptools-scm derives the package version from git, which isn't available
# in this build context (only uv.lock/pyproject.toml are copied in) — pin a
# pretend version so it doesn't need one. The real release version is set by
# the PyPI publish job, which does a full git checkout.
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_RADICALBIT_AI_GATEWAY=0.0.0

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
