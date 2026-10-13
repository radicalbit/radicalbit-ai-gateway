-- +goose Up
-- One row per alert send attempt, sent or failed. This is the alert history.
--
-- SCOPE, PROJECT_UUID, ROUTE_NAME and CREDENTIAL_UUID are nullable because a
-- rule fills only the ones its scope uses. COUNT is 1 for an instant alert
-- and the number of matching events for a time window, whose bounds are null
-- otherwise.
--
-- No TTL. The history is kept for as long as the rule exists.
CREATE TABLE IF NOT EXISTS default.alert (
    `ALERT_UUID` UUID,
    `TIMESTAMP` DateTime64(9, 'UTC'),
    `DATE` Date MATERIALIZED toDate(TIMESTAMP),
    `RULE_UUID` UUID,
    `RULE_NAME` String,
    `SCOPE` LowCardinality(Nullable(String)),
    `PROJECT_UUID` Nullable(UUID),
    `ROUTE_NAME` LowCardinality(Nullable(String)),
    `CREDENTIAL_UUID` Nullable(UUID),
    `EVENT` LowCardinality(String),
    `AGGREGATION` LowCardinality(String),
    `COUNT` UInt64,
    `WINDOW_START` Nullable(DateTime64(9, 'UTC')),
    `WINDOW_END` Nullable(DateTime64(9, 'UTC')),
    `STATUS` LowCardinality(String)
)
ENGINE = MergeTree()
PARTITION BY DATE
ORDER BY (RULE_UUID, TIMESTAMP)
SETTINGS index_granularity = 8192;

-- +goose Down
DROP TABLE IF EXISTS default.alert;
