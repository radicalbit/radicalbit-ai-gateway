// A readable one-line summary per event (AG-1109). UX owns the final wording.
// Raw names (model IDs, guardrail names) are kept as they are configured.

const isLimit = (eventType) => eventType.endsWith('_LIMIT');

const judgeSuffix = (isJudge) => (isJudge ? ' (judge)' : '');

const joinWords = (...words) => words.filter(Boolean).join(' ');

const summarizeLimit = (attributes) => {
  const limit = joinWords(attributes.limit_scope, attributes.category, 'limit');
  const usage = attributes.maximum ? `, ${attributes.consumption ?? '?'} / ${attributes.maximum}` : '';
  const window = attributes.window_seconds ? ` in ${attributes.window_seconds}s` : '';

  return `Blocked by the ${limit}${usage}${window}`;
};

export default function summarize(event) {
  const {
    eventType, value, modelId, isJudge, cacheType, target, fallback, routingName,
    routingSelectedModelId, guardrailName, guardrailType, guardrailWhere,
    guardrailBehavior, mcpMethod, mcpAlias, mcpTarget, attributes = {},
  } = event;

  switch (eventType) {
    case 'MODEL_INVOCATION':
      return `Invoked ${modelId ?? 'a model'}${judgeSuffix(isJudge)}`;

    case 'INPUT_TOKEN_PROCESSED':
      return `${value} input tokens on ${modelId ?? '--'}${judgeSuffix(isJudge)}`;

    case 'OUTPUT_TOKEN_PROCESSED':
      return `${value} output tokens on ${modelId ?? '--'}${judgeSuffix(isJudge)}`;

    case 'CACHE_HIT':
      return joinWords('Served from the', cacheType, 'cache');

    case 'CACHE_INPUT_TOKENS':
      return `${value} input tokens saved by the cache`;

    case 'CACHE_OUTPUT_TOKENS':
      return `${value} output tokens saved by the cache`;

    case 'FALLBACK':
      return `${target ?? '--'} failed, fell back to ${fallback ?? '--'}`;

    case 'ROUTING':
      return `${routingName ?? 'Routing'} picked ${routingSelectedModelId ?? '--'}`;

    case 'GUARDRAIL':
      return `${guardrailName ?? 'Guardrail'} (${guardrailType ?? '--'}) on ${guardrailWhere ?? '--'}: ${guardrailBehavior ?? '--'}`;

    case 'LIMIT_THRESHOLD':
      return joinWords(attributes.limit_scope, attributes.category, 'limit threshold crossed');

    case 'MCP_INVOCATION':
      return `MCP ${mcpMethod ?? '--'} on ${mcpAlias ?? mcpTarget ?? '--'}`;

    default:
      if (isLimit(eventType)) {
        return summarizeLimit(attributes);
      }

      return eventType;
  }
}
