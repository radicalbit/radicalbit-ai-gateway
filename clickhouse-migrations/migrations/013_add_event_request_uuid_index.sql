-- +goose Up
-- Looking up the events of one request by REQUEST_UUID. REQUEST_UUID is not
-- in the ORDER BY of event, so without a skip index such a lookup reads every
-- granule of the partitions it touches. Queries pair it with a DATE bound for
-- partition pruning; the bloom filter then skips the granules within.
ALTER TABLE default.event
    ADD INDEX IF NOT EXISTS idx_request_uuid REQUEST_UUID TYPE bloom_filter(0.01) GRANULARITY 1;

-- Build the index for the parts already stored. Runs as a background
-- mutation; until it finishes, lookups still work, only slower.
ALTER TABLE default.event
    MATERIALIZE INDEX idx_request_uuid;

-- +goose Down
ALTER TABLE default.event
    DROP INDEX IF EXISTS idx_request_uuid;
