-- +goose Up
-- The object an MCP invocation addressed: the tool for tools/call, the
-- prompt for prompts/get, the upstream URI for resources/read. Same value
-- and same rule as the rb.gateway.mcp_target trace attribute. It is written
-- only when the alias resolved to a server configured on the route, and is
-- empty otherwise.
--
-- Migration 009 left this out because the name is client-supplied. It is
-- needed now: drilling into a server on the Usage page shows one series per
-- tool. Plain String, not LowCardinality. The alias check bounds the server
-- side, but the name after it is still the caller's, and a dictionary column
-- degrades once its values stop being few.
--
-- No backfill. Older invocations read as an empty target.
ALTER TABLE default.event
    ADD COLUMN IF NOT EXISTS MCP_TARGET String DEFAULT '';

-- +goose Down
ALTER TABLE default.event
    DROP COLUMN IF EXISTS MCP_TARGET;
