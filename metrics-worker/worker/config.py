"""Shared configuration for metrics worker using Pydantic Settings."""

import logging

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class ClickHouseConfig(BaseSettings):
    """ClickHouse connection settings."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra='ignore',
    )

    clickhouse_host: str = 'localhost'
    clickhouse_port: int = 8123
    clickhouse_database: str = 'default'
    clickhouse_user: str = 'default'
    clickhouse_password: str = ''
    clickhouse_async_insert: bool = True
    clickhouse_wait_for_async: bool = False


class CeleryConfig(BaseSettings):
    """Celery broker configuration."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra='ignore',
    )

    celery_broker_url: str = 'redis://localhost:6379/0'


class MetricsConfig(BaseSettings):
    """Metrics processing configuration (worker + buffer settings)."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra='ignore',
    )

    metrics_worker_prefetch: int = 4
    metrics_batch_size: int = 200
    metrics_flush_interval_ms: int = 500

    @property
    def flush_interval_sec(self) -> float:
        """Convert flush interval from milliseconds to seconds with minimum of 0.1."""
        return max(self.metrics_flush_interval_ms / 1000, 0.1)


class SlackConfig(BaseSettings):
    """Slack notification configuration."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra='ignore',
    )

    slack_enabled: bool = False
    slack_webhook_mappings: dict[str, str] = {}
    slack_user_mappings: dict[str, str] = {}


class SendGridConfig(BaseSettings):
    """SendGrid notification configuration."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra='ignore',
    )

    sendgrid_enabled: bool = False
    sendgrid_api_key: str | None = None
    sendgrid_from_email: str | None = None
    sendgrid_template_id: str | None = None
    sendgrid_email_mappings: dict[str, list[str]] = {}


class RedisConfig(BaseSettings):
    """Redis configuration for threshold state storage."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra='ignore',
    )

    redis_host: str = 'localhost'
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None


class NotificationConfig(BaseSettings):
    """Notification threshold configuration."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra='ignore',
    )

    notification_thresholds: list[int] = [75, 98]

    @field_validator('notification_thresholds', mode='after')
    @classmethod
    def validate_notification_thresholds(cls, thresholds: list[int]) -> list[int]:
        """Validate thresholds are in range 1-99 and sort them."""
        validated = sorted({t for t in thresholds if 1 <= t <= 99})
        return validated if validated else [75, 98]


class LogConfig(BaseSettings):
    """Logging configuration."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra='ignore',
    )

    log_level: str = 'INFO'


class Config(BaseSettings):
    """Configuration for metrics worker with nested config classes."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra='ignore',
    )

    celery: CeleryConfig = CeleryConfig()
    clickhouse: ClickHouseConfig = ClickHouseConfig()
    metrics: MetricsConfig = MetricsConfig()
    slack: SlackConfig = SlackConfig()
    sendgrid: SendGridConfig = SendGridConfig()
    redis: RedisConfig = RedisConfig()
    notification: NotificationConfig = NotificationConfig()
    log: LogConfig = LogConfig()


# Singleton instance
config = Config()
