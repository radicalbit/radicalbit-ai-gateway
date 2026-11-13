export const SPAN_PARAM = 'spanId';

export const SPAN_TAB_PARAM = 'spanTab';

export const SPAN_TABS = ['input', 'output', 'attributes'];

export const DEFAULT_SPAN_TAB = 'input';

export const IO_ATTRIBUTES = {
  input: 'traceloop.entity.input',
  output: 'traceloop.entity.output',
};

export const ATTRIBUTE_PREFIXES = [
  { prefix: 'decision.', title: 'Decision' },
  { prefix: 'gen_ai.usage.', title: 'Usage' },
  { prefix: 'traceloop.association.properties.', title: 'Association properties' },
];

export const TAGS_ATTRIBUTE = { group: 'Association properties', name: 'tags' };
