"""Shared configuration for metrics worker using Pydantic Settings."""

import logging

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
    log: LogConfig = LogConfig()


# Singleton instance
config = Config()
