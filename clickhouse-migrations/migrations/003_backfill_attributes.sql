-- +goose Up
-- Backfill MODEL_ID
ALTER TABLE default.event
    UPDATE MODEL_ID = ATTRIBUTES['model_name']
    WHERE MODEL_ID = '' AND mapContains(ATTRIBUTES, 'model_name');

-- Backfill MODEL_TYPE
ALTER TABLE default.event
    UPDATE MODEL_TYPE = ATTRIBUTES['model_type']
    WHERE MODEL_TYPE = '' AND mapContains(ATTRIBUTES, 'model_type');

-- Backfill CACHE_TYPE
ALTER TABLE default.event
    UPDATE CACHE_TYPE = ATTRIBUTES['cache_type']
    WHERE CACHE_TYPE = '' AND mapContains(ATTRIBUTES, 'cache_type');

-- Backfill IS_CACHED_TOKENS
ALTER TABLE default.event
    UPDATE IS_CACHED_TOKENS = ATTRIBUTES['is_cached_tokens'] = 'True'
    WHERE IS_CACHED_TOKENS = false AND mapContains(ATTRIBUTES, 'is_cached_tokens');

-- Backfill TARGET
ALTER TABLE default.event
    UPDATE TARGET = ATTRIBUTES['target']
    WHERE TARGET = '' AND mapContains(ATTRIBUTES, 'target');

-- Backfill FALLBACK
ALTER TABLE default.event
    UPDATE FALLBACK = ATTRIBUTES['fallback']
    WHERE FALLBACK = '' AND mapContains(ATTRIBUTES, 'fallback');

-- Backfill GUARDRAIL_NAME
ALTER TABLE default.event
    UPDATE GUARDRAIL_NAME = ATTRIBUTES['name']
    WHERE GUARDRAIL_NAME = '' AND mapContains(ATTRIBUTES, 'name');

-- Backfill GUARDRAIL_TYPE
ALTER TABLE default.event
    UPDATE GUARDRAIL_TYPE = ATTRIBUTES['type']
    WHERE GUARDRAIL_TYPE = '' AND mapContains(ATTRIBUTES, 'type');

-- Backfill GUARDRAIL_WHERE
ALTER TABLE default.event
    UPDATE GUARDRAIL_WHERE = ATTRIBUTES['where']
    WHERE GUARDRAIL_WHERE = '' AND mapContains(ATTRIBUTES, 'where');

-- Backfill GUARDRAIL_PARAMS
ALTER TABLE default.event
    UPDATE GUARDRAIL_PARAMS = ATTRIBUTES['parameters']
    WHERE GUARDRAIL_PARAMS = '' AND mapContains(ATTRIBUTES, 'parameters');

-- Backfill GUARDRAIL_BEHAVIOR
ALTER TABLE default.event
    UPDATE GUARDRAIL_BEHAVIOR = ATTRIBUTES['behavior']
    WHERE GUARDRAIL_BEHAVIOR = '' AND mapContains(ATTRIBUTES, 'behavior');

-- Backfill IS_JUDGE
ALTER TABLE default.event
    UPDATE IS_JUDGE = ATTRIBUTES['is_judge'] = 'True'
    WHERE IS_JUDGE = false AND mapContains(ATTRIBUTES, 'is_judge');

-- +goose Down
-- Clear backfilled values (data cannot be restored without source ATTRIBUTES Map)
ALTER TABLE default.event
    UPDATE MODEL_ID = '',
        MODEL_TYPE = '',
        CACHE_TYPE = '',
        IS_CACHED_TOKENS = false,
        TARGET = '',
        FALLBACK = '',
        GUARDRAIL_NAME = '',
        GUARDRAIL_TYPE = '',
        GUARDRAIL_WHERE = '',
        GUARDRAIL_PARAMS = '',
        GUARDRAIL_BEHAVIOR = '',
        IS_JUDGE = false
    WHERE 1=1;
