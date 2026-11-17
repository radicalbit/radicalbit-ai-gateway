import { describe, expect, it } from 'vitest';
import { WindowTypeEnum } from './constants';
import {
  formatBlockedBy, formatLimitCategory, formatResetsIn, formatWindowSeconds, getDuplicateLimit, getMostConsumed,
} from './helpers';

const SAVED = {
  algorithm: 'fixed_window', category: 'requests', uuid: 'saved-1', value: 10, windowSize: '1 minute',
};

const DUPLICATE_ROW = {
  algorithm: 'fixed_window', category: 'requests', value: 20, windowSize: '1 minute',
};

const OTHER_ROW = {
  algorithm: 'fixed_window', category: 'tokens', value: 5, windowSize: '1 hour',
};

const EMPTY_ROW = {
  algorithm: undefined, category: undefined, value: undefined, windowSize: undefined,
};

describe('getDuplicateLimit', () => {
  it('returns the saved limit when the duplicate row is the only filled row', () => {
    expect(getDuplicateLimit({ limits: [SAVED], rows: [DUPLICATE_ROW] })).toBe(SAVED);
  });

  it('ignores empty rows when counting filled rows', () => {
    expect(getDuplicateLimit({ limits: [SAVED], rows: [DUPLICATE_ROW, EMPTY_ROW] })).toBe(SAVED);
  });

  it('returns nothing when another row is filled', () => {
    expect(getDuplicateLimit({ limits: [SAVED], rows: [DUPLICATE_ROW, OTHER_ROW] })).toBeUndefined();
  });

  it('returns nothing when the only filled row is not a duplicate', () => {
    expect(getDuplicateLimit({ limits: [SAVED], rows: [OTHER_ROW] })).toBeUndefined();
  });

  it('counts a row with only the category picked as empty, since budgets preset it', () => {
    const categoryOnly = { ...EMPTY_ROW, category: 'tokens' };

    expect(getDuplicateLimit({ limits: [SAVED], rows: [DUPLICATE_ROW, categoryOnly] })).toBe(SAVED);
  });
});

const NOW = 1_800_000_000;

const bar = ({ endsIn, filled }) => ({
  windowEndTime: NOW + endsIn,
  windowFilledPercentage: filled,
  windowFilledSize: filled,
  windowSize: 100,
  windowStatus: 'ok',
});

describe('formatResetsIn', () => {
  it('counts minutes under an hour', () => {
    expect(formatResetsIn({ algorithm: WindowTypeEnum.ALIGNED, bar: bar({ endsIn: 30 * 60, filled: 10 }), now: NOW })).toBe('resets in 30 min');
  });

  it('rounds a partial minute up, never to zero', () => {
    expect(formatResetsIn({ algorithm: WindowTypeEnum.ALIGNED, bar: bar({ endsIn: 20, filled: 10 }), now: NOW })).toBe('resets in 1 min');
  });

  it('counts hours under a day', () => {
    expect(formatResetsIn({ algorithm: WindowTypeEnum.ALIGNED, bar: bar({ endsIn: 3 * 3600 + 600, filled: 10 }), now: NOW })).toBe('resets in 3 h');
  });

  it('rounds hours down, so it never promises more time than is left', () => {
    expect(formatResetsIn({ algorithm: WindowTypeEnum.ALIGNED, bar: bar({ endsIn: 23 * 3600 + 36 * 60, filled: 10 }), now: NOW })).toBe('resets in 23 h');
  });

  it('rounds days down', () => {
    expect(formatResetsIn({ algorithm: WindowTypeEnum.FIXED, bar: bar({ endsIn: 34 * 3600, filled: 10 }), now: NOW })).toBe('resets in 1 day');
    expect(formatResetsIn({ algorithm: WindowTypeEnum.FIXED, bar: bar({ endsIn: 47 * 3600, filled: 10 }), now: NOW })).toBe('resets in 1 day');
  });

  it('counts days from a day on', () => {
    expect(formatResetsIn({ algorithm: WindowTypeEnum.FIXED, bar: bar({ endsIn: 2 * 86400, filled: 10 }), now: NOW })).toBe('resets in 2 days');
    expect(formatResetsIn({ algorithm: WindowTypeEnum.FIXED, bar: bar({ endsIn: 86400, filled: 10 }), now: NOW })).toBe('resets in 1 day');
  });

  it('says a Fixed window with nothing consumed has not started', () => {
    expect(formatResetsIn({ algorithm: WindowTypeEnum.FIXED, bar: bar({ endsIn: 3600, filled: 0 }), now: NOW })).toBe('Starts at the first request');
  });

  it('keeps counting down an Aligned window with nothing consumed', () => {
    expect(formatResetsIn({ algorithm: WindowTypeEnum.ALIGNED, bar: bar({ endsIn: 3600, filled: 0 }), now: NOW })).toBe('resets in 1 h');
  });

  it('says nothing before the stream has a bar for the limit', () => {
    expect(formatResetsIn({ algorithm: WindowTypeEnum.FIXED, bar: undefined, now: NOW })).toBeUndefined();
  });
});

describe('getMostConsumed', () => {
  const limits = [{ uuid: 'a' }, { uuid: 'b' }, { uuid: 'c' }];

  it('returns the percentage and status of the most consumed limit', () => {
    const consumption = {
      a: { windowFilledPercentage: 40.2, windowStatus: 'ok' },
      b: { windowFilledPercentage: 94.6, windowStatus: 'critical' },
      c: { windowFilledPercentage: 75, windowStatus: 'warning' },
    };

    expect(getMostConsumed(limits, consumption)).toEqual({ percentage: 95, status: 'critical' });
  });

  it('ignores limits of other credentials in the stream', () => {
    const consumption = {
      a: { windowFilledPercentage: 10, windowStatus: 'ok' },
      other: { windowFilledPercentage: 99, windowStatus: 'critical' },
    };

    expect(getMostConsumed(limits, consumption)).toEqual({ percentage: 10, status: 'ok' });
  });

  it('returns nothing when no limit has consumed anything', () => {
    const consumption = { a: { windowFilledPercentage: 0, windowStatus: 'ok' } };

    expect(getMostConsumed(limits, consumption)).toBeNull();
  });

  it('returns nothing when the most consumed limit rounds to 0%', () => {
    const consumption = { a: { windowFilledPercentage: 0.3, windowStatus: 'ok' } };

    expect(getMostConsumed(limits, consumption)).toBeNull();
  });

  it('returns nothing before the stream has data', () => {
    expect(getMostConsumed(limits, undefined)).toBeNull();
  });
});

describe('formatBlockedBy', () => {
  it('names a route block', () => {
    expect(formatBlockedBy({ apiKeyName: 'alice', limitScope: 'route' })).toBe('Route');
  });

  it('names the credential whose limit blocked', () => {
    expect(formatBlockedBy({ apiKeyName: 'alice', limitScope: 'credential' })).toBe('Credential "alice"');
  });

  it('names a project block', () => {
    expect(formatBlockedBy({ apiKeyName: 'alice', limitScope: 'project' })).toBe('Project');
  });
});

describe('formatLimitCategory', () => {
  it('uses the limit category labels', () => {
    expect(formatLimitCategory('request_rate')).toBe('Requests');
    expect(formatLimitCategory('token_output')).toBe('Output tokens');
  });

  it('names the route-only audio duration category', () => {
    expect(formatLimitCategory('audio_duration')).toBe('Audio duration');
  });
});

describe('formatWindowSeconds', () => {
  it('uses the largest exact unit', () => {
    expect(formatWindowSeconds(60)).toBe('1 min');
    expect(formatWindowSeconds(300)).toBe('5 min');
    expect(formatWindowSeconds(3600)).toBe('1 h');
    expect(formatWindowSeconds(7200)).toBe('2 h');
    expect(formatWindowSeconds(86400)).toBe('1 day');
    expect(formatWindowSeconds(172800)).toBe('2 days');
    expect(formatWindowSeconds(604800)).toBe('1 week');
    expect(formatWindowSeconds(2592000)).toBe('1 month');
  });

  it('keeps windows that are not a whole unit in a smaller one', () => {
    expect(formatWindowSeconds(90)).toBe('90 s');
    expect(formatWindowSeconds(5400)).toBe('90 min');
  });

  it('shows a dash when the event did not record its window', () => {
    expect(formatWindowSeconds(undefined)).toBe('—');
    expect(formatWindowSeconds(null)).toBe('—');
  });
});
