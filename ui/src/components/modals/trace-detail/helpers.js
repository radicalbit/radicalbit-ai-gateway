import { ATTRIBUTE_PREFIXES, DEFAULT_SPAN_TAB, IO_ATTRIBUTES, SPAN_TABS } from './constants';

const INVOCATION = 'invocation';

const OTHER_ATTRIBUTES = 'Other attributes';

export function flattenSpans(tree) {
  if (!tree) {
    return [];
  }

  const walk = (span, depth) => [
    { depth, span },
    ...(span.children ?? []).flatMap((child) => walk(child, depth + 1)),
  ];

  return walk(tree, 0);
}

export function selectedSpanId(tree, spanIdParam) {
  const spans = flattenSpans(tree).map(({ span }) => span);

  if (spans.some(({ spanId }) => spanId === spanIdParam)) {
    return spanIdParam;
  }

  const invocation = spans.find(({ operationCategory }) => operationCategory === INVOCATION);

  if (invocation) {
    return invocation.spanId;
  }

  return tree?.spanId;
}

export function selectedSpanTab(spanTabParam) {
  if (SPAN_TABS.includes(spanTabParam)) {
    return spanTabParam;
  }

  return DEFAULT_SPAN_TAB;
}

export function isSpanError(span) {
  return span?.statusCode === 'Error' || (span?.errorCount ?? 0) > 0;
}

export function waterfallBar(span, traceDurationMs) {
  if (!traceDurationMs) {
    return { offset: 0, value: 0 };
  }

  const offset = Math.min(Math.max((span.startOffsetMs / traceDurationMs) * 100, 0), 100);
  const value = Math.min((span.durationMs / traceDurationMs) * 100, 100 - offset);

  return { offset, value };
}

export function spanShare(span, traceDurationMs) {
  if (!traceDurationMs) {
    return 0;
  }

  return Math.round((span.durationMs / traceDurationMs) * 100);
}

function parseJson(value) {
  if (typeof value !== 'string') {
    return value;
  }

  try {
    const parsed = JSON.parse(value);

    if (typeof parsed === 'string' && parsed !== value) {
      return parseJson(parsed);
    }

    return parsed;
  } catch {
    return value;
  }
}

function isJsonTree(value) {
  return value !== null && typeof value === 'object';
}

export function spanIo(attributes, tab) {
  const raw = attributes?.[IO_ATTRIBUTES[tab]];

  if (raw === undefined || raw === null || raw === '') {
    return { type: 'empty' };
  }

  const parsed = parseJson(raw);

  if (isJsonTree(parsed)) {
    return { type: 'json', value: parsed };
  }

  return { type: 'text', value: String(raw) };
}

function shownAttributeKeys(attributes) {
  const ioKeys = Object.values(IO_ATTRIBUTES);

  return Object.keys(attributes ?? {}).filter((key) => !ioKeys.includes(key));
}

export function attributeCount(attributes) {
  return shownAttributeKeys(attributes).length;
}

export function attributeGroups(attributes) {
  const keys = shownAttributeKeys(attributes);
  const prefixOf = (key) => ATTRIBUTE_PREFIXES.find(({ prefix }) => key.startsWith(prefix));
  const item = (key, prefix = '') => ({ name: key.slice(prefix.length), value: parseJson(attributes[key]) });

  const prefixed = ATTRIBUTE_PREFIXES.map(({ prefix, title }) => ({
    title,
    items: keys.filter((key) => key.startsWith(prefix)).map((key) => item(key, prefix)),
  }));

  const other = {
    title: OTHER_ATTRIBUTES,
    items: keys.filter((key) => !prefixOf(key)).map((key) => item(key)),
  };

  return [...prefixed, other].filter(({ items }) => items.length > 0);
}

export function spanErrorLines(span) {
  const errorEvents = span?.errorEvents ?? [];
  const eventLines = errorEvents.map(({ attributes, name }) => attributes?.['exception.message'] ?? name);

  return [...new Set([span?.statusMessage, ...eventLines].filter(Boolean))];
}

export function spanTreeRows(tree) {
  if (!tree) {
    return [];
  }

  const row = ({ children, ...span }) => {
    if (!children?.length) {
      return span;
    }

    return { ...span, children: children.map(row) };
  };

  return [row(tree)];
}

export function attributeTags(value) {
  const list = Array.isArray(value) ? value : String(value ?? '').split(',');

  return list.map((tag) => String(tag).trim()).filter(Boolean);
}
