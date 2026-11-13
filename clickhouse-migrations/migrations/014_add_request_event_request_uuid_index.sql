-- +goose Up
-- Opening one request by REQUEST_UUID. The lookup carries no time range, and
-- REQUEST_UUID comes last in the ORDER BY of request_event, after ROUTE_NAME
-- and TIMESTAMP, so the primary key cannot narrow it: without a skip index it
-- reads every granule of every partition. The bloom filter skips them.
ALTER TABLE default.request_event
    ADD INDEX IF NOT EXISTS idx_request_uuid REQUEST_UUID TYPE bloom_filter(0.01) GRANULARITY 1;

-- Build the index for the parts already stored. Runs as a background
-- mutation; until it finishes, lookups still work, only slower.
ALTER TABLE default.request_event
    MATERIALIZE INDEX idx_request_uuid;

-- +goose Down
ALTER TABLE default.request_event
    DROP INDEX IF EXISTS idx_request_uuid;
