# metrics-worker

Celery worker for processing metrics in the Radicalbit AI Gateway.

## What it does

Exposes two Celery tasks:

**`emit_event`** - Stores metrics in ClickHouse
- Receives event payloads from the gateway
- Buffers events in memory and flushes to ClickHouse when batch size or flush interval is reached
- Supports async inserts for better throughput

**`emit_notification`** - Sends token usage alerts
- Receives notification payloads with current token usage
- Checks if configurable thresholds are crossed (default: 75%, 98%)
- Sends alerts via Slack and/or SendGrid (each independently configurable)
- Notifies only once per threshold per time window (deduplication via Redis)

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
| **Slack Notifications** | | |
| `SLACK_ENABLED` | Enable Slack notifications | `false` |
| `SLACK_WEBHOOK_MAPPINGS` | JSON mapping of routes to Slack webhook URLs | `{}` |
| `SLACK_USER_MAPPINGS` | JSON mapping of routes to Slack user IDs for tagging | `{}` |
| **SendGrid Notifications** | | |
| `SENDGRID_ENABLED` | Enable SendGrid email notifications | `false` |
| `SENDGRID_API_KEY` | SendGrid API key | `None` |
| `SENDGRID_FROM_EMAIL` | Sender email address | `None` |
| `SENDGRID_TEMPLATE_ID` | SendGrid dynamic template ID (optional) | `None` |
| `SENDGRID_EMAIL_MAPPINGS` | JSON mapping of routes to email lists (first=to, rest=cc) | `{}` |
| **Notification Settings** | | |
| `NOTIFICATION_THRESHOLDS` | Threshold percentages that trigger alerts | `[75, 98]` |
| **Redis** | | |
| `REDIS_HOST` | Redis host for threshold state | `localhost` |
| `REDIS_PORT` | Redis port | `6379` |
| `REDIS_DB` | Redis database number | `0` |
| `REDIS_PASSWORD` | Redis password | `None` |
| **Logging** | | |
| `LOG_LEVEL` | Log level | `INFO` |

## Notification Channels

Notifications can be sent via Slack, SendGrid, or both. Each channel is independently controlled by its own enable flag.

### Slack Integration

- Create a new app here https://api.slack.com/apps?new_app=1
- Create Incoming Webhooks pointing to the channels you want to notify
- Set `SLACK_ENABLED=true`
- Map route names to webhook URLs in `SLACK_WEBHOOK_MAPPINGS`
- Optionally map route names to Slack user IDs in `SLACK_USER_MAPPINGS` for user tagging

### SendGrid Integration

- Obtain a SendGrid API key with email sending permissions
- Set `SENDGRID_ENABLED=true`
- Set `SENDGRID_API_KEY` to your API key
- Set `SENDGRID_FROM_EMAIL` to the sender address
- Map route names to recipient emails in `SENDGRID_EMAIL_MAPPINGS`

#### Using Dynamic Templates (Optional)

You can use SendGrid dynamic templates for customized email formatting:

1. Create a dynamic template in SendGrid
2. Copy the template ID (e.g., `d-e624763c71314ea2a1fae38d7fa64a4a`)
3. Set `SENDGRID_TEMPLATE_ID` to your template ID

**Available template variables:**

| Variable | Description | Example                          |
|----------|-------------|----------------------------------|
| `{{first_name}}` | Primary recipient email (the "to" address) | `user@example.com`               |
| `{{msg}}` | Current token usage with percentage | `12% (1,234 / 10,000 tokens)` |
| `{{route_name}}` | The route that triggered the alert | `openai-gpt4`                    |
| `{{direction}}` | Token direction | `INPUT` or `OUTPUT`              |
| `{{window_resets}}` | When the usage window resets | `18-02-2026, 14:30:00 UTC`       |

**Example template:**

```html
<h1>Token Usage Alert</h1>
<p>Hi {{first_name}},</p>
<p>Route <strong>{{route_name}}</strong> has reached {{msg}}.</p>
<p>Direction: {{direction}}</p>
<p>Window resets: {{window_resets}}</p>
```

If no template is configured, a default HTML email is sent.