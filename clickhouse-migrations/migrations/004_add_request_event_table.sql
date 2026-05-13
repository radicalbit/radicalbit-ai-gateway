-- +goose Up
CREATE TABLE IF NOT EXISTS default.request_event (
    `REQUEST_UUID` UUID,
    `TIMESTAMP` DateTime64(9, 'UTC'),
    `DATE` Date MATERIALIZED toDate(TIMESTAMP),
    `ROUTE_NAME` LowCardinality(String),
    `API_KEY_UUID` Nullable(UUID),
    `API_KEY_NAME` LowCardinality(String),
    `GROUP_UUID` Nullable(UUID),
    `GROUP_NAME` LowCardinality(String),
    `REQUEST_TYPE` LowCardinality(String),
    `REQUEST_STATUS` LowCardinality(String),
    `HTTP_STATUS_CODE` Int32,
    `DURATION_MS` Float64,
    `ERROR_TYPE` LowCardinality(String),
    `ERROR_CODE` LowCardinality(String),
    `IS_STREAMING` Bool
)
ENGINE = MergeTree()
PARTITION BY DATE
ORDER BY (ROUTE_NAME, TIMESTAMP, REQUEST_UUID)
SETTINGS index_granularity = 8192;

-- +goose Down
DROP TABLE IF EXISTS default.request_event;
