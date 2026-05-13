FROM python:3.13.11-slim AS build

WORKDIR /app

COPY uv.lock pyproject.toml ./
RUN pip install --no-cache-dir --no-compile uv==0.9.27 && \
    uv export --no-hashes --format requirements-txt > requirements.txt && \
    rm -f uv.lock pyproject.toml && \
    rm -rf /root/.cache

FROM python:3.13.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /worker

COPY --from=build /app/requirements.txt .

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc libpq-dev python3-dev tini && \
    pip install --no-cache-dir --no-compile --default-timeout=1000 -r requirements.txt && \
    rm -rf /var/lib/apt/lists/* /root/.cache requirements.txt

COPY ./worker ./worker

COPY ./entrypoint.sh .
RUN chmod +x ./entrypoint.sh

RUN adduser --system --no-create-home celeryuser 

RUN chown -R celeryuser /worker

USER celeryuser


ENTRYPOINT ["tini", "-v", "--", "./entrypoint.sh"]