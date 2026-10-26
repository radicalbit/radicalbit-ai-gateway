import {
  DUPLICATE_LIMIT_ERROR, DUPLICATE_ROW_ERROR, LIMIT_CATEGORIES, LIMIT_EVENT_CATEGORIES, LIMIT_WINDOWS, LimitCategoryEnum,
  WindowTypeEnum,
} from './constants';

const CURRENCY_FORMAT = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });

const NUMBER_FORMAT = new Intl.NumberFormat('en-US');

const CREDENTIAL_SCOPE = 'credential';

const getWindow = (windowSize) => LIMIT_WINDOWS.find(({ value }) => value === windowSize);

export const getWindowOptions = (algorithm) => LIMIT_WINDOWS
  .filter(({ aligned }) => algorithm !== WindowTypeEnum.ALIGNED || aligned)
  .map(({ label, value }) => ({ label, value }));

export const formatLimitWindow = (windowSize) => getWindow(windowSize)?.label ?? windowSize;

export const formatLimitValue = (category, value) => {
  if (category === LimitCategoryEnum.BUDGET) {
    return CURRENCY_FORMAT.format(value);
  }

  const unit = category === LimitCategoryEnum.REQUEST_RATE ? 'requests' : 'tokens';

  return `${NUMBER_FORMAT.format(value)} ${unit}`;
};

export const formatCount = (count, noun) => (count === 1 ? `1 ${noun}` : `${count} ${noun}s`);

export const formatLimitsCount = (count) => formatCount(count, 'limit');

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
// only when no other limit of the credential has the same category and window.
// e.g. `rate_limit-exceeded-1h` and `rate_limit-80pct-1h` both watch the hourly request limit.
export const getRulesMadeStale = ({ credentialUuid, limit, limits, rules }) => {
  const eventWindow = getEventWindow(limit.windowSize);

  if (!eventWindow) {
    return [];
  }

  const isStillWatched = limits.some(({ category, uuid, windowSize }) => uuid !== limit.uuid
    && category === limit.category
    && getEventWindow(windowSize) === eventWindow);

  if (isStillWatched) {
    return [];
  }

  const eventCategory = LIMIT_EVENT_CATEGORIES[limit.category];
  const eventPattern = new RegExp(`^${eventCategory}-(exceeded|\\d+pct)-${eventWindow}$`);

  return rules.filter(({ credentialUuid: ruleCredentialUuid, event, scope }) => scope === CREDENTIAL_SCOPE
    && ruleCredentialUuid === credentialUuid
    && eventPattern.test(event));
};

export const getNewLimitsErrors = ({ limits, rows }) => {
  const savedSignatures = new Set(limits.map(getLimitSignature));

  return rows.map((row, index) => {
    if (!row.category || !row.algorithm || !row.windowSize) {
      return undefined;
    }

    const signature = getLimitSignature(row);

    if (savedSignatures.has(signature)) {
      return DUPLICATE_LIMIT_ERROR;
    }

    if (rows.slice(0, index).some((above) => getLimitSignature(above) === signature)) {
      return DUPLICATE_ROW_ERROR;
    }

    return undefined;
  });
};

export const isLimitComplete = ({ algorithm, category, value, windowSize }) => !!category && !!algorithm && !!windowSize && typeof value === 'number' && value > 0;
