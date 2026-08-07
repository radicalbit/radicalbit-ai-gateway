from enum import Enum
from functools import lru_cache
import logging
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr, computed_field, field_validator
from pydantic.alias_generators import to_camel
from pydantic_core.core_schema import ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogMode(str, Enum):
    JSON = 'json'
    PLAIN = 'plain'
    COLOR = 'color'


class HealthCheckFilter(logging.Filter):
    def filter(self, record):
        return record.getMessage().find('/health') == -1


class ClickHouseConfig(BaseSettings):
    clickhouse_db_host: str = 'localhost'
    clickhouse_db_port: int = 9002
    clickhouse_db_user: str = 'default'
    clickhouse_db_pwd: str = 'default'
    clickhouse_db_name: str = 'default'
    clickhouse_db_schema: str = 'default'


class DBConfig(BaseSettings):
    db_type: str = 'sqlite'
    db_host: str | None = None
    db_port: int | None = None
    db_user: str | None = None
    db_pwd: str | None = None
    db_name: str = ':memory:'
    db_schema: str | None = None


class RedisConfig(BaseSettings):
    redis_host: str | None = None
    redis_port: int | None = None
    redis_url: str | None = Field(default=None)

    @field_validator('redis_url', mode='before')
    @classmethod
    def assemble_redis_url(
        cls, value: str | None, values: ValidationInfo
    ) -> str | None:
        redis_host = values.data['redis_host']
        redis_port = values.data['redis_port']
        if redis_host and redis_port:
            return f'redis://{redis_host}:{redis_port}'
        return None


class RuntimeConfig(BaseSettings):
    enabled_plugins: str = Field(default='', exclude=True)

    def plugins(self) -> list[str]:
        # Split by comma and filter out empty strings
        return [p for p in self.enabled_plugins.replace(' ', '').split(',') if p]

    @computed_field
    @property
    def enabled_plugins_list(self) -> list[str]:
        return self.plugins()

    model_config = SettingsConfigDict(
        populate_by_name=True, alias_generator=to_camel, protected_namespaces=()
    )


class CeleryConfig(BaseSettings):
    celery_broker_url: str = 'redis://localhost:6379/0'
    celery_events_batch_size: int = 50
    celery_events_flush_ms: int = Field(gt=10, default=100)
    celery_broker_pool_limit: int = 5


class PromptManagerConfig(BaseSettings):
    prompts_dir: str | None = None
    judge_prompts_dir: str | None = None


class ConfigGeneratorConfig(BaseSettings):
    config_generator_openai_api_key: SecretStr | None = None
    config_generator_openai_base_url: str | None = None
    config_generator_openai_model: str = 'gpt-4.1'
    config_generator_max_retries: int = 3


class SmtpConfig(BaseSettings):
    smtp_host: str = 'localhost'
    smtp_port: int = 25
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str = 'alerts@radicalbit.ai'


class CorsConfig(BaseSettings):
    """CORS configuration settings.

    Environment variables:
        CORS_ALLOW_ORIGINS: Comma-separated list of allowed origins.
            Default: "http://localhost:5173"
            Example: "http://localhost:5173,https://example.com"
        CORS_ALLOW_CREDENTIALS: Whether to allow credentials.
            Default: True
    """

    cors_allow_origins: list[str] = Field(default=['http://localhost:5173'])
    cors_allow_credentials: bool = True


class LogConfig(BaseSettings):
    """Logging settings model used to assemble a complete `logging.dictConfig` at runtime.

    - Environment overrides for nested fields are enabled via `env_nested_delimiter='__'`.
    - Provides standard and debug formats/levels (`log_format`/`log_level` and
      `debug_log_format`/`debug_log_level`) to switch verbosity and context.
    - `disable_existing_loggers=True` helps prevent duplicate handlers from Uvicorn
      or other libraries when applying the configuration.
    - `formatters` and `loggers` are intentionally left empty: populate them in
      `AppConfig.model_post_init(...)` or via a builder method (e.g. `to_dict_config(debug=...)`)
      based on the selected mode.
    - `filters` and `handlers` define reusable building blocks for the final dictConfig:
        * `healthcheck_filter` drops `/health` entries from access logs.
        * `default` sends application logs to stderr; `access` sends HTTP access logs to stdout.
    """

    model_config = SettingsConfigDict(env_nested_delimiter='__')

    logger_name: str = 'radicalbit-ai-gateway'

    log_format: str = '%(asctime)s %(levelname)s [%(name)s] %(message)s'
    log_level: str = 'INFO'

    debug_log_format: str = (
        '%(asctime)s %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s'
    )
    debug_log_level: str = 'DEBUG'

    version: int = 1
    disable_existing_loggers: bool = True

    formatters: dict = Field(default_factory=dict)
    handlers: dict = Field(default_factory=dict)
    loggers: dict = Field(default_factory=dict)

    filters: dict = {
        'healthcheck_filter': {'()': HealthCheckFilter},
    }


class OtlpExporterConfig(BaseModel):
    """Configuration settings for exporting telemetry via OpenLLMetry.

    Attributes:
        url (Optional[str]):
            The endpoint where telemetry data will be collected.
            Typically points to an OTEL-compatible service or monitoring platform.
            Example: "http://localhost:9000/api/otel".

        api_key (Optional[str]):
            API key used for authentication when sending telemetry.
            Optional; required only if the destination enforces authentication.

        headers (Dict | None):
            Additional HTTP headers for telemetry export, expressed as a dictionary.
            Useful for custom authentication or integration requirements.
            Example: {"Authorization": "Basic sk-key"}.

    """

    url: str
    api_key: str | None = None
    headers: dict | None = Field(default_factory=dict)


class TelemetryConfig(BaseSettings):
    collector_base_url: str | None = None
    otlp_exporters: list[OtlpExporterConfig] = Field(default_factory=list)


class AppConfig(BaseSettings):
    """Central application settings with nested blocks (runtime/db/redis/log).
    - Env overrides for nested fields via `env_nested_delimiter='__'`.
    - `gateway_debug_mode` selects logging format/level.
    - `log_mode` selects the log output:
      'json'  (default) structured logs via python-json-logger
      'plain' text logs (debug vs standard format)
      'color' Rich colored logs (forced width, no wrap)

    `model_post_init`:
    - Populates `log_config.formatters` and `log_config.loggers` using debug or
      standard values from `LogConfig`.
    - Makes `log_config.model_dump()` a complete `logging.dictConfig` ready for
      `logging.config.dictConfig(...)`.
    - Wiring: app & `uvicorn.error` → `default`; `uvicorn.access` → `access`
      (stdout, with `healthcheck_filter`).
    """

    model_config = SettingsConfigDict(env_nested_delimiter='__')

    gateway_secrets_path: Path = Path('secrets.yaml')
    gateway_debug_mode: bool = False
    log_mode: LogMode = LogMode.PLAIN
    prometheus_metrics_port: int = 8001
    endpoint_version: str = 'v1'

    runtime_config: RuntimeConfig = RuntimeConfig()
    db_config: DBConfig = DBConfig()
    redis_config: RedisConfig = RedisConfig()
    log_config: LogConfig = LogConfig()
    telemetry_config: TelemetryConfig = TelemetryConfig()
    otel_exporter_otlp_endpoint: str = 'http://localhost:4318'
    clickhouse_config: ClickHouseConfig = ClickHouseConfig()
    celery_config: CeleryConfig = CeleryConfig()
    prompt_manager_config: PromptManagerConfig = PromptManagerConfig()
    cors_config: CorsConfig = CorsConfig()
    config_generator_config: ConfigGeneratorConfig = ConfigGeneratorConfig()
    smtp_config: SmtpConfig = SmtpConfig()

    def model_post_init(self, __context) -> None:
        lvl_str = (
            self.log_config.debug_log_level
            if self.gateway_debug_mode
            else self.log_config.log_level
        ).upper()

        app_handler_name = None

        if self.log_mode is LogMode.COLOR:
            self.log_config.formatters = {
                'rich': {'format': '%(message)s'},
            }
            self.log_config.handlers = {
                'rich': {
                    '()': 'radicalbit_ai_gateway.utils.rich_logging_factories.make_rich_handler',
                    'formatter': 'rich',
                    'level': lvl_str,
                },
                'rich_access': {
                    '()': 'radicalbit_ai_gateway.utils.rich_logging_factories.make_rich_handler',
                    'formatter': 'rich',
                    'filters': ['healthcheck_filter'],
                    'level': lvl_str,
                },
            }
            self.log_config.loggers = {
                self.log_config.logger_name: {
                    'handlers': ['rich'],
                    'level': lvl_str,
                    'propagate': False,
                },
                'uvicorn.error': {
                    'handlers': ['rich'],
                    'level': lvl_str,
                    'propagate': False,
                },
                'uvicorn.access': {
                    'handlers': ['rich_access'],
                    'level': lvl_str,
                    'propagate': False,
                },
                'root': {
                    'handlers': ['rich'],
                    'level': lvl_str,
                    'propagate': False,
                },
            }
            app_handler_name = 'rich'
        elif self.log_mode is LogMode.JSON:
            fmt_fields = (
                '%(asctime)s %(levelname)s %(name)s %(message)s '
                '%(module)s %(funcName)s %(lineno)d %(process)d %(threadName)s'
            )
            fmt_str = (
                self.log_config.debug_log_format
                if self.gateway_debug_mode
                else self.log_config.log_format
            )
            fmt = {'format': fmt_str, 'datefmt': '%Y-%m-%d %H:%M:%S'}
            self.log_config.formatters = {
                'json': {
                    '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
                    'fmt': fmt_fields,
                    # 'json_ensure_ascii': False,
                    # 'json_indent': None,
                },
                'json_access': {
                    '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
                    'fmt': fmt_fields,
                },
            }
            self.log_config.handlers = {
                'default': {
                    'formatter': 'json',
                    'class': 'logging.StreamHandler',
                    'stream': 'ext://sys.stderr',
                    'level': lvl_str,
                },
                'access': {
                    'formatter': 'json_access',
                    'class': 'logging.StreamHandler',
                    'stream': 'ext://sys.stdout',
                    'filters': ['healthcheck_filter'],
                    'level': lvl_str,
                },
            }
            self.log_config.loggers = {
                self.log_config.logger_name: {
                    'handlers': ['default'],
                    'level': lvl_str,
                    'propagate': False,
                },
                'uvicorn.error': {
                    'handlers': ['default'],
                    'level': lvl_str,
                    'propagate': False,
                },
                'uvicorn.access': {
                    'handlers': ['access'],
                    'level': lvl_str,
                    'propagate': False,
                },
                'root': {
                    'handlers': ['default'],
                    'level': lvl_str,
                    'propagate': False,
                },
            }
            app_handler_name = 'default'
        else:  # log mode 'plain'
            fmt_str = (
                self.log_config.debug_log_format
                if self.gateway_debug_mode
                else self.log_config.log_format
            )
            fmt = {'format': fmt_str, 'datefmt': '%Y-%m-%d %H:%M:%S'}
            self.log_config.formatters = {'default': fmt, 'access': fmt.copy()}
            self.log_config.handlers = {
                'default': {
                    'formatter': 'default',
                    'class': 'logging.StreamHandler',
                    'stream': 'ext://sys.stderr',
                    'level': lvl_str,
                },
                'access': {
                    'formatter': 'access',
                    'class': 'logging.StreamHandler',
                    'stream': 'ext://sys.stdout',
                    'filters': ['healthcheck_filter'],
                    'level': lvl_str,
                },
            }
            self.log_config.loggers = {
                self.log_config.logger_name: {
                    'handlers': ['default'],
                    'level': lvl_str,
                    'propagate': False,
                },
                'uvicorn.error': {
                    'handlers': ['default'],
                    'level': lvl_str,
                    'propagate': False,
                },
                'uvicorn.access': {
                    'handlers': ['access'],
                    'level': lvl_str,
                    'propagate': False,
                },
                'root': {'handlers': ['default'], 'level': lvl_str, 'propagate': False},
            }
            app_handler_name = 'default'

        self.log_config.loggers.update(
            {
                'slowapi': {
                    'handlers': [app_handler_name],
                    'level': 'ERROR',
                    'propagate': False,
                },
                'slowapi.middleware': {
                    'handlers': [app_handler_name],
                    'level': 'ERROR',
                    'propagate': False,
                },
                'slowapi.errors': {
                    'handlers': [app_handler_name],
                    'level': 'ERROR',
                    'propagate': False,
                },
                'limits': {
                    'handlers': [app_handler_name],
                    'level': 'ERROR',
                    'propagate': False,
                },
            }
        )


@lru_cache
def get_app_config() -> AppConfig:
    return AppConfig()
