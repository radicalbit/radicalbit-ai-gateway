-- +goose Up
-- Client-supplied tags from the X-RB-Tags header, stored as canonical
-- 'key=value' entries, sorted and deduplicated by the gateway.
--
-- A flat Array(String) is used rather than a Map so that one key can carry
-- several values, and because bloom_filter is the only skip index that serves
-- has()/hasAny()/hasAll() on Array columns -- the predicates tag filtering
-- needs. Filter with hasAll(TAGS, ['env=prod','cost_center=retail']).
--
-- TAGS is deliberately kept out of ORDER BY: reordering would rebuild both
-- tables and slow every existing query. The skip index plus the existing
-- PARTITION BY DATE pruning does the work instead.
ALTER TABLE default.event
    ADD COLUMN IF NOT EXISTS TAGS Array(String) CODEC(ZSTD(1));

ALTER TABLE default.event
    ADD INDEX IF NOT EXISTS idx_tags TAGS TYPE bloom_filter(0.01) GRANULARITY 1;

ALTER TABLE default.request_event
    ADD COLUMN IF NOT EXISTS TAGS Array(String) CODEC(ZSTD(1));

ALTER TABLE default.request_event
    ADD INDEX IF NOT EXISTS idx_tags TAGS TYPE bloom_filter(0.01) GRANULARITY 1;

-- Distinct tags per project, split into key and value.
--
-- 'SELECT DISTINCT arrayJoin(TAGS)' answers the same question but scans the
-- whole project: measured at 6M event rows it reads ~1.2M rows versus 71 from
-- this table, and that gap grows with traffic while this table stays bounded by
-- the number of distinct tags in the project.
--
-- Key and value are stored separately, and in that ORDER BY order, so a filter
-- UI can list a project's tag keys and then the values of one key without
-- splitting strings at query time. Splitting is unambiguous because tag values
-- may not contain '=' (see utils/request_tags.py).
--
-- Fed from request_event (one row per request) rather than event (several rows
-- per request) to keep write amplification down; both tables see the same tags.
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
