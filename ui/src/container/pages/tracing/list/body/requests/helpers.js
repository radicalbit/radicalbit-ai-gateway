import formatCost from '@Src/helpers/format-cost';

const ICON_KINDS = ['routing', 'guardrail', 'fallback', 'limits', 'cache'];

const GUARDRAIL_VERBS = {
  BLOCK: 'blocked the',
  SOFT_BLOCK: 'soft-blocked the',
  WARN: 'warned on the',
};

const ICON_LINES = {
  routing: ({ routingName, selectedModel }) => `${routingName} chose ${selectedModel}`,
  guardrail: ({ behavior, name, position }) => `${name} ${GUARDRAIL_VERBS[behavior] ?? 'ran on the'} ${position}`,
  fallback: ({ fallbackModel, target }) => `${target} fell back to ${fallbackModel}`,
  limits: ({ category, limitScope, thresholdPercentage }) => {
    if (thresholdPercentage) {
      return `${limitScope} ${category} at ${thresholdPercentage}%`;
    }

    return `${limitScope} ${category} limit exceeded`;
  },
  cache: ({ cacheType }) => `${cacheType} cache hit`,
};

const LIMIT_FIELDS = ['limit_scope', 'category', 'consumption', 'maximum', 'window_seconds'];

const LIMIT_EVENT_TYPES = [
  'RATE_LIMIT',
  'TOKEN_INPUT_LIMIT',
  'TOKEN_OUTPUT_LIMIT',
  'AUDIO_DURATION_LIMIT',
  'BUDGET_LIMIT',
  'CREDENTIAL_RATE_LIMIT',
  'CREDENTIAL_TOKEN_INPUT_LIMIT',
  'CREDENTIAL_TOKEN_OUTPUT_LIMIT',
  'CREDENTIAL_BUDGET_LIMIT',
  'PROJECT_BUDGET_LIMIT',
];

const FIELDS_BY_TYPE = {
  MODEL_INVOCATION: ['modelId', 'modelType', 'cacheType', 'isJudge', 'isRouting'],
  INPUT_TOKEN_PROCESSED: ['value', 'cost', 'modelId', 'cacheType', 'isCachedTokens', 'isJudge', 'isRouting'],
  OUTPUT_TOKEN_PROCESSED: ['value', 'cost', 'modelId', 'cacheType', 'isJudge', 'isRouting'],
  FALLBACK: ['target', 'fallback', 'isJudge', 'isRouting'],
  CACHE_HIT: ['cacheType', 'modelId'],
  CACHE_INPUT_TOKENS: ['value', 'cacheType', 'modelId'],
  CACHE_OUTPUT_TOKENS: ['value', 'cacheType', 'modelId'],
  GUARDRAIL: ['guardrailName', 'guardrailType', 'guardrailWhere', 'guardrailBehavior', 'isJudge'],
  ROUTING: ['routingName', 'routingSelectedModelId'],
  MCP_INVOCATION: ['mcpMethod', 'mcpAlias', 'mcpTarget'],
  LIMIT_THRESHOLD: ['threshold_percentage', ...LIMIT_FIELDS],
  ...Object.fromEntries(LIMIT_EVENT_TYPES.map((eventType) => [eventType, LIMIT_FIELDS])),
};

const NOT_FIELDS = ['eventType', 'timestamp', 'blocking', 'attributes'];

const HIDDEN_EVENT_TYPES = ['GUARDRAIL_PARAMS'];

const WARNING_EVENT_TYPES = ['FALLBACK', 'LIMIT_THRESHOLD'];

const MUTED_EVENT_TYPES = ['INPUT_TOKEN_PROCESSED', 'OUTPUT_TOKEN_PROCESSED', 'CACHE_INPUT_TOKENS', 'CACHE_OUTPUT_TOKENS'];

const RESPONSE_TONES = {
  success: 'success',
  handled_error: 'error',
  unhandled_error: 'error',
};

const RESPONSE_FIELDS = ['requestStatus', 'httpStatusCode', 'errorType', 'errorCode'];

const isShown = ({ value }) => value !== undefined && value !== null && value !== false && value !== '';

const formatField = (name, value) => {
  if (name === 'cost') {
    return formatCost(value);
  }

  return String(value);
};

const eventFieldNames = (event) => {
  const { attributes, eventType } = event;

  if (FIELDS_BY_TYPE[eventType]) {
    return FIELDS_BY_TYPE[eventType];
  }

  return [
    ...Object.keys(event).filter((name) => !NOT_FIELDS.includes(name)),
    ...Object.keys(attributes ?? {}),
  ];
};

const eventFields = (event) => {
  const { attributes } = event;
  const names = eventFieldNames(event);

  return names
    .map((name) => ({ name, value: event[name] ?? attributes?.[name] }))
    .filter(isShown)
    .map(({ name, value }) => ({ name, value: formatField(name, value) }));
};

const eventTone = ({ blocking, eventType, guardrailBehavior }) => {
  if (blocking) {
    return 'error';
  }

  if (guardrailBehavior === 'WARN' || WARNING_EVENT_TYPES.includes(eventType)) {
    return 'warning';
  }

  if (MUTED_EVENT_TYPES.includes(eventType)) {
    return 'muted';
  }

  if (eventType === 'MODEL_INVOCATION') {
    return 'neutral';
  }

  return 'primary';
};

const responseStep = (request) => {
  const { durationMs, requestStatus } = request;

  return {
    key: 'response',
    offsetMs: durationMs,
    type: 'response',
    blocking: false,
    tone: RESPONSE_TONES[requestStatus] ?? 'neutral',
    fields: RESPONSE_FIELDS
      .map((name) => ({ name, value: request[name] }))
      .filter(isShown)
      .map(({ name, value }) => ({ name, value: String(value) })),
  };
};

const requestSteps = (request) => {
  const { events } = request;

  const shownEvents = events
    .filter(({ eventType }) => !HIDDEN_EVENT_TYPES.includes(eventType))
    .map((event) => ({ event, time: Date.parse(event.timestamp) }))
    .sort((a, b) => a.time - b.time);

  const firstTime = shownEvents[0]?.time;

  const eventSteps = shownEvents.map(({ event, time }, index) => ({
    key: `${index}-${event.eventType}`,
    offsetMs: time - firstTime,
    type: event.eventType,
    blocking: event.blocking,
    tone: eventTone(event),
    fields: eventFields(event),
  }));

  return [...eventSteps, responseStep(request)];
};

const formatOffset = (ms) => {
  if (ms === 0) {
    return '0 ms';
  }

  if (ms < 10) {
    return `${ms.toFixed(2)} ms`;
  }

  if (ms < 1000) {
    return `${Math.round(ms)} ms`;
  }

  return `${(ms / 1000).toFixed(2)} s`;
};

const selectedRequestUuid = (items, requestUuid) => {
  const isOnPage = items.some((item) => item.requestUuid === requestUuid);

  if (isOnPage) {
    return requestUuid;
  }

  return items[0]?.requestUuid;
};

const firedIcons = (icons) => ICON_KINDS
  .filter((kind) => icons[kind])
  .map((kind) => ({
    kind,
    tone: icons[kind].tone,
    lines: icons[kind].details.map(ICON_LINES[kind]),
  }));

export {
  firedIcons, formatOffset, requestSteps, selectedRequestUuid,
};
