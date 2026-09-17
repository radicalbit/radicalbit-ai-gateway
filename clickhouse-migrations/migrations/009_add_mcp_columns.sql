-- +goose Up
-- MCP invocation identity, promoted out of the attributes map. MODEL_ID and
-- the guardrail fields were promoted the same way.
--
-- Both are bounded. The method is one of three protocol verbs. The alias is
-- checked against the route's configured servers before it is recorded, and
-- is empty when it did not resolve.
--
-- The called tool's name is deliberately absent. It is client-supplied and
-- checked against nothing. Indexing it would let any caller mint unlimited
-- distinct values in this column.
--
-- No backfill. The method and the alias were never written to this table. Old
-- MCP traffic is absent from these columns, not wrong.
ALTER TABLE default.event
    ADD COLUMN IF NOT EXISTS MCP_METHOD LowCardinality(String) DEFAULT '',
    ADD COLUMN IF NOT EXISTS MCP_ALIAS LowCardinality(String) DEFAULT '';

-- +goose Down
ALTER TABLE default.event
    DROP COLUMN IF EXISTS MCP_METHOD,
    DROP COLUMN IF EXISTS MCP_ALIAS;
