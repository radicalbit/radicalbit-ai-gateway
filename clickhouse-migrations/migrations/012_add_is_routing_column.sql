-- +goose Up
-- True on the cost events of a call a router made for a request: the query
-- embedding of semantic routing, the decision model call of decision
-- routing. Same idea as IS_JUDGE. Usage totals already sum it through COST.
--
-- No backfill. Older events read as not routing.
ALTER TABLE default.event
    ADD COLUMN IF NOT EXISTS IS_ROUTING Bool DEFAULT false;

-- +goose Down
ALTER TABLE default.event
    DROP COLUMN IF EXISTS IS_ROUTING;
