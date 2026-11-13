import formatUsd from '@Helpers/format-usd';
import {
  AUDIO_DURATION_CATEGORY, DUPLICATE_LIMIT_ERROR, DUPLICATE_ROW_ERROR, LIMIT_CATEGORIES, LIMIT_CATEGORY_LABELS, LIMIT_EVENT_CATEGORIES, LIMIT_WINDOWS, LimitCategoryEnum, LimitScopeEnum,
  WindowTypeEnum,
} from './constants';

const NUMBER_FORMAT = new Intl.NumberFormat('en-US');

export const RuleScopeEnum = {
  CREDENTIAL: 'credential',
  PROJECT: 'project',
};

const RULE_TARGETS = {
  [RuleScopeEnum.CREDENTIAL]: ({ credentialUuid }) => credentialUuid,
  [RuleScopeEnum.PROJECT]: ({ project }) => project,
};

const getWindow = (windowSize) => LIMIT_WINDOWS.find(({ value }) => value === windowSize);

export const getWindowOptions = (algorithm) => LIMIT_WINDOWS
  .filter(({ aligned }) => algorithm !== WindowTypeEnum.ALIGNED || aligned)
  .map(({ label, value }) => ({ label, value }));

export const formatLimitWindow = (windowSize) => getWindow(windowSize)?.label ?? windowSize;

export const formatLimitValue = (category, value) => {
  if (category === LimitCategoryEnum.BUDGET) {
    return formatUsd(value);
  }

  const unit = category === LimitCategoryEnum.REQUEST_RATE ? 'requests' : 'tokens';

  return `${NUMBER_FORMAT.format(value)} ${unit}`;
};

export const formatRouteLimitWarning = ({
  category, credentialValue, credentialWindowSize, routeName, routeValue, routeWindowSize,
}, subject = 'this credential') => `${routeName}: route allows ${formatLimitValue(category, routeValue)} / ${formatLimitWindow(routeWindowSize)}, ${subject} ${formatLimitValue(category, credentialValue)} / ${formatLimitWindow(credentialWindowSize)}. The route limit is reached first.`;

export const getLimitWarnings = (warnings, { algorithm, category, windowSize }) => (warnings ?? [])
  .filter((warning) => warning.category === category && warning.algorithm === algorithm && warning.credentialWindowSize === windowSize);

export const formatNeverReached = ({ category, routeName, routeValue, routeWindowSize }) => `Never reached on ${routeName}: the route allows ${formatLimitValue(category, routeValue)} / ${formatLimitWindow(routeWindowSize)}.`;

export const formatCount = (count, noun) => (count === 1 ? `1 ${noun}` : `${count} ${noun}s`);

export const formatLimitsCount = (count) => formatCount(count, 'limit');

export const asBudgets = (limits = []) => limits.map((limit) => ({ ...limit, category: LimitCategoryEnum.BUDGET }));

export const getLimitSignature = ({ algorithm, category, windowSize }) => `${category}|${algorithm}|${windowSize}`;

export const sortLimits = (limits) => [...limits].sort((a, b) => {
  const byCategory = LIMIT_CATEGORIES.indexOf(a.category) - LIMIT_CATEGORIES.indexOf(b.category);

  if (byCategory !== 0) {
    return byCategory;
  }

  return LIMIT_WINDOWS.findIndex(({ value }) => value === a.windowSize)
    - LIMIT_WINDOWS.findIndex(({ value }) => value === b.windowSize);
});

const EVENT_WINDOW_UNITS = [['mo', 2592000], ['w', 604800], ['d', 86400], ['h', 3600], ['m', 60], ['s', 1]];

const WINDOW_UNIT_SECONDS = {
  second: 1, minute: 60, hour: 3600, day: 86400, week: 604800, month: 2592000,
};

const getEventWindow = (windowSize) => {
  const [, count, unit] = /^(\d+)\s*([a-z]+?)s?$/i.exec(windowSize?.trim() ?? '') ?? [];
  const seconds = Number(count) * WINDOW_UNIT_SECONDS[unit?.toLowerCase()];

  if (!seconds) {
    return undefined;
  }

  const [name, size] = EVENT_WINDOW_UNITS.find(([, unitSize]) => seconds % unitSize === 0);

  return `${seconds / size}${name}`;
};

// Alert rules name a limit by category and window, without window type: a rule on the deleted limit becomes stale
// only when no other limit of the same credential or project has the same category and window.
// e.g. `rate_limit-exceeded-1h` and `rate_limit-80pct-1h` both watch the hourly request limit.
// A project only has budgets, so its limits carry no category.
export const getRulesMadeStale = ({ limit, limits, rules, scope, targetUuid }) => {
  const eventWindow = getEventWindow(limit.windowSize);
  const limitCategory = limit.category ?? LimitCategoryEnum.BUDGET;

  if (!eventWindow) {
    return [];
  }

  const isStillWatched = limits.some(({ category = LimitCategoryEnum.BUDGET, uuid, windowSize }) => uuid !== limit.uuid
    && category === limitCategory
    && getEventWindow(windowSize) === eventWindow);

  if (isStillWatched) {
    return [];
  }

  const eventCategory = LIMIT_EVENT_CATEGORIES[limitCategory];
  const eventPattern = new RegExp(`^${eventCategory}-(exceeded|\\d+pct)-${eventWindow}$`);

  return rules.filter((rule) => rule.scope === scope
    && RULE_TARGETS[scope](rule) === targetUuid
    && eventPattern.test(rule.event));
};

export const getNewLimitsErrors = ({ duplicateError = DUPLICATE_LIMIT_ERROR, limits, rows }) => {
  const savedSignatures = new Set(limits.map(getLimitSignature));

  return rows.map((row, index) => {
    if (!row.category || !row.algorithm || !row.windowSize) {
      return undefined;
    }

    const signature = getLimitSignature(row);

    if (savedSignatures.has(signature)) {
      return duplicateError;
    }

    if (rows.slice(0, index).some((above) => getLimitSignature(above) === signature)) {
      return DUPLICATE_ROW_ERROR;
    }

    return undefined;
  });
};

const isRowFilled = ({ algorithm, value, windowSize }) => !!algorithm || !!windowSize || value != null;

export const getDuplicateLimit = ({ limits, rows }) => {
  const filledRows = rows.filter(isRowFilled);

  if (filledRows.length !== 1) {
    return undefined;
  }

  const signature = getLimitSignature(filledRows[0]);

  return limits.find((limit) => getLimitSignature(limit) === signature);
};

export const isLimitComplete = ({ algorithm, category, value, windowSize }) => !!category && !!algorithm && !!windowSize && typeof value === 'number' && value > 0;

const SECONDS_PER_MINUTE = 60;
const SECONDS_PER_HOUR = 3600;
const SECONDS_PER_DAY = 86400;

export const WINDOW_NOT_STARTED = 'Starts at the first request';

// A Fixed window starts at the first request: with nothing consumed it has not started,
// and its end time is only "one window from now".
export const formatResetsIn = ({ algorithm, bar, now }) => {
  if (!bar) {
    return undefined;
  }

  if (algorithm === WindowTypeEnum.FIXED && !bar.windowFilledSize) {
    return WINDOW_NOT_STARTED;
  }

  const seconds = Math.max(0, bar.windowEndTime - now);

  if (seconds < SECONDS_PER_HOUR) {
    return `resets in ${Math.max(1, Math.ceil(seconds / SECONDS_PER_MINUTE))} min`;
  }

  if (seconds < SECONDS_PER_DAY) {
    return `resets in ${Math.floor(seconds / SECONDS_PER_HOUR)} h`;
  }

  return `resets in ${formatCount(Math.floor(seconds / SECONDS_PER_DAY), 'day')}`;
};

export const getMostConsumed = (limits, consumption) => {
  const bars = (limits ?? [])
    .map(({ uuid }) => consumption?.[uuid])
    .filter((bar) => Math.round(bar?.windowFilledPercentage ?? 0) > 0);

  if (!bars.length) {
    return null;
  }

  const most = bars.reduce((a, b) => (b.windowFilledPercentage > a.windowFilledPercentage ? b : a));

  return { percentage: Math.round(most.windowFilledPercentage), status: most.windowStatus };
};

// Who blocked a request: a credential's own limit is named after the credential that sent it.
export const formatBlockedBy = ({ apiKeyName, limitScope }) => {
  if (limitScope === LimitScopeEnum.CREDENTIAL) {
    return `Credential "${apiKeyName}"`;
  }

  if (limitScope === LimitScopeEnum.PROJECT) {
    return 'Project';
  }

  return 'Route';
};

export const formatLimitCategory = (category) => {
  if (category === AUDIO_DURATION_CATEGORY) {
    return 'Audio duration';
  }

  return LIMIT_CATEGORY_LABELS[category] ?? category;
};

const WINDOW_SECONDS_UNITS = [
  { seconds: SECONDS_PER_DAY * 30, singular: 'month', plural: 'months' },
  { seconds: SECONDS_PER_DAY * 7, singular: 'week', plural: 'weeks' },
  { seconds: SECONDS_PER_DAY, singular: 'day', plural: 'days' },
  { seconds: SECONDS_PER_HOUR, singular: 'h', plural: 'h' },
  { seconds: SECONDS_PER_MINUTE, singular: 'min', plural: 'min' },
  { seconds: 1, singular: 's', plural: 's' },
];

// A limit event records its window in seconds; route windows need not be on the credential list.
export const formatWindowSeconds = (windowSeconds) => {
  if (!windowSeconds) {
    return '—';
  }

  const { plural, seconds, singular } = WINDOW_SECONDS_UNITS.find((unit) => windowSeconds % unit.seconds === 0);
  const count = windowSeconds / seconds;

  if (count === 1) {
    return `1 ${singular}`;
  }

  return `${count} ${plural}`;
};
