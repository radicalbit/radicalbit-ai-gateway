import { describe, expect, it } from 'vitest';
import { getDuplicateLimit } from './helpers';

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
