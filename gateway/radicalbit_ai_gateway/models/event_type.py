from enum import Enum


class EventType(str, Enum):
    MODEL_INVOCATION = 'MODEL_INVOCATION'
    FALLBACK = 'FALLBACK'
    GUARDRAIL = 'GUARDRAIL'
    ROUTING = 'ROUTING'
    RATE_LIMIT = 'RATE_LIMIT'
    CACHE_HIT = 'CACHE_HIT'
    TOKEN_INPUT_LIMIT = 'TOKEN_INPUT_LIMIT'
    TOKEN_OUTPUT_LIMIT = 'TOKEN_OUTPUT_LIMIT'
    AUDIO_DURATION_LIMIT = 'AUDIO_DURATION_LIMIT'
    BUDGET_LIMIT = 'BUDGET_LIMIT'
    CREDENTIAL_RATE_LIMIT = 'CREDENTIAL_RATE_LIMIT'
    CREDENTIAL_TOKEN_INPUT_LIMIT = 'CREDENTIAL_TOKEN_INPUT_LIMIT'
    CREDENTIAL_TOKEN_OUTPUT_LIMIT = 'CREDENTIAL_TOKEN_OUTPUT_LIMIT'
    CREDENTIAL_BUDGET_LIMIT = 'CREDENTIAL_BUDGET_LIMIT'
    PROJECT_BUDGET_LIMIT = 'PROJECT_BUDGET_LIMIT'
    LIMIT_THRESHOLD = 'LIMIT_THRESHOLD'
    INPUT_TOKEN_PROCESSED = 'INPUT_TOKEN_PROCESSED'
    OUTPUT_TOKEN_PROCESSED = 'OUTPUT_TOKEN_PROCESSED'
    CACHE_INPUT_TOKENS = 'CACHE_INPUT_TOKENS'
    CACHE_OUTPUT_TOKENS = 'CACHE_OUTPUT_TOKENS'
    MCP_INVOCATION = 'MCP_INVOCATION'
    REQUEST = 'REQUEST'


# The events a limit records when it blocks a request, each with the scope and
# category it names, for rows recorded before the event carried them.
# LIMIT_THRESHOLD is not one: it warns, it does not block.
LIMIT_BLOCK_EVENTS: dict[str, tuple[str, str]] = {
    EventType.RATE_LIMIT.value: ('route', 'request_rate'),
    EventType.TOKEN_INPUT_LIMIT.value: ('route', 'token_input'),
    EventType.TOKEN_OUTPUT_LIMIT.value: ('route', 'token_output'),
    EventType.AUDIO_DURATION_LIMIT.value: ('route', 'audio_duration'),
    EventType.BUDGET_LIMIT.value: ('route', 'budget'),
    EventType.CREDENTIAL_RATE_LIMIT.value: ('credential', 'request_rate'),
    EventType.CREDENTIAL_TOKEN_INPUT_LIMIT.value: ('credential', 'token_input'),
    EventType.CREDENTIAL_TOKEN_OUTPUT_LIMIT.value: ('credential', 'token_output'),
    EventType.CREDENTIAL_BUDGET_LIMIT.value: ('credential', 'budget'),
    EventType.PROJECT_BUDGET_LIMIT.value: ('project', 'budget'),
}
# Every event type a limit records when it blocks a request.
LIMIT_BLOCK_EVENT_TYPES: tuple[str, ...] = tuple(LIMIT_BLOCK_EVENTS)
