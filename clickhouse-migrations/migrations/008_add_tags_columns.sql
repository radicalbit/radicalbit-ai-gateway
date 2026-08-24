-- +goose Up
-- Client-supplied tags from the X-RB-Tags header, stored as canonical
-- 'key=value' entries, sorted and deduplicated by the gateway.
--
-- A flat Array(String) rather than a Map: one key can carry several values,
-- and bloom_filter is the only skip index serving has()/hasAny()/hasAll().
-- Filter with hasAll(TAGS, ['env=prod','cost_center=retail']). TAGS stays out
-- of ORDER BY; the skip index plus PARTITION BY DATE pruning does the work.
ALTER TABLE default.event
    ADD COLUMN IF NOT EXISTS TAGS Array(String) CODEC(ZSTD(1));

ALTER TABLE default.event
    ADD INDEX IF NOT EXISTS idx_tags TAGS TYPE bloom_filter(0.01) GRANULARITY 1;

ALTER TABLE default.request_event
    ADD COLUMN IF NOT EXISTS TAGS Array(String) CODEC(ZSTD(1));

ALTER TABLE default.request_event
    ADD INDEX IF NOT EXISTS idx_tags TAGS TYPE bloom_filter(0.01) GRANULARITY 1;

-- Distinct tags per project, split into key and value (splitting is
-- unambiguous because tag values may not contain '='). Far cheaper to read
-- than 'SELECT DISTINCT arrayJoin(TAGS)', which scans the whole project.
-- Fed from request_event (one row per request) to limit write amplification.
CREATE TABLE IF NOT EXISTS default.project_tag (
    `PROJECT_UUID` UUID,
    `TAG_KEY` String,
    `TAG_VALUE` String,
    `LAST_SEEN` SimpleAggregateFunction(max, DateTime64(9, 'UTC'))
)
ENGINE = AggregatingMergeTree()
ORDER BY (PROJECT_UUID, TAG_KEY, TAG_VALUE)
SETTINGS index_granularity = 8192;

CREATE MATERIALIZED VIEW IF NOT EXISTS default.project_tag_mv
TO default.project_tag (
    `PROJECT_UUID` UUID,
    `TAG_KEY` String,
    `TAG_VALUE` String,
    `LAST_SEEN` SimpleAggregateFunction(max, DateTime64(9, 'UTC'))
) AS
SELECT
    assumeNotNull(PROJECT_UUID) AS PROJECT_UUID,
    splitByChar('=', TAG)[1] AS TAG_KEY,
    splitByChar('=', TAG)[2] AS TAG_VALUE,
    max(TIMESTAMP) AS LAST_SEEN
FROM default.request_event
ARRAY JOIN TAGS AS TAG
WHERE PROJECT_UUID IS NOT NULL AND notEmpty(TAGS)
GROUP BY PROJECT_UUID, TAG_KEY, TAG_VALUE;

-- +goose Down
DROP VIEW IF EXISTS default.project_tag_mv;

DROP TABLE IF EXISTS default.project_tag;

ALTER TABLE default.request_event
    DROP INDEX IF EXISTS idx_tags;

ALTER TABLE default.request_event
    DROP COLUMN IF EXISTS TAGS;

ALTER TABLE default.event
    DROP INDEX IF EXISTS idx_tags;

ALTER TABLE default.event
    DROP COLUMN IF EXISTS TAGS;
