-- +goose Up
CREATE TABLE IF NOT EXISTS default.event (
    `REQUEST_UUID` UUID,
    `TIMESTAMP` DateTime64(9, 'UTC'),
    `DATE` Date MATERIALIZED toDate(TIMESTAMP),
    `EVENT_TYPE` LowCardinality(String),
    `ROUTE_NAME` LowCardinality(String),
    `ATTRIBUTES` Map(LowCardinality(String), String),
    `API_KEY_UUID` UUID,
    `GROUP_UUID` UUID,
    `API_KEY_NAME` LowCardinality(String),
    `GROUP_NAME` LowCardinality(String),
    `VALUE` Float64,
    `COST` Decimal64(9)
)
ENGINE = MergeTree()
PARTITION BY DATE
ORDER BY (ROUTE_NAME, EVENT_TYPE, TIMESTAMP, API_KEY_UUID, GROUP_UUID)
SETTINGS index_granularity = 8192;

-- +goose Down
DROP TABLE IF EXISTS default.event;
