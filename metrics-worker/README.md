# metrics-worker

Celery worker for processing metrics in the Radicalbit AI Gateway.

## What it does

Exposes three Celery tasks, each storing what the gateway emits in ClickHouse:

**`emit_event`** - Stores metrics
- Receives event payloads from the gateway
- Buffers events in memory and flushes to ClickHouse when batch size or flush interval is reached
- Supports async inserts for better throughput

**`emit_request_event`** - Stores one record per gateway request

**`emit_alert`** - Stores every alert the gateway sends

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| **Celery** | | |
| `CELERY_BROKER_URL` | Redis broker URL for Celery | `redis://localhost:6379/0` |
| `METRICS_WORKER_PREFETCH` | Number of tasks to prefetch | `4` |
| **ClickHouse** | | |
| `CLICKHOUSE_HOST` | ClickHouse server host | `localhost` |
| `CLICKHOUSE_PORT` | ClickHouse HTTP port | `8123` |
| `CLICKHOUSE_DATABASE` | Database name | `default` |
| `CLICKHOUSE_USER` | Username | `default` |
| `CLICKHOUSE_PASSWORD` | Password | `""` (empty) |
| `CLICKHOUSE_ASYNC_INSERT` | Enable async inserts | `true` |
| `CLICKHOUSE_WAIT_FOR_ASYNC` | Wait for async insert completion | `false` |
| `METRICS_BATCH_SIZE` | Number of records per batch | `200` |
| `METRICS_FLUSH_INTERVAL_MS` | Flush interval in milliseconds | `500` |
| **Logging** | | |
| `LOG_LEVEL` | Log level | `INFO` |
