import { describe, expect, it } from 'vitest';
import { ConflictAlertTypeEnum, getConflictAlertType } from './helpers';

describe('getConflictAlertType', () => {
  it('is a warning when a published route has its own budget, since it blocks adding', () => {
    expect(getConflictAlertType({ draft: ['b'], published: ['a'] })).toBe(ConflictAlertTypeEnum.PUBLISHED);
    expect(ConflictAlertTypeEnum.PUBLISHED).toBe('warning');
  });

  it('is info when only the draft has routes with their own budget, since it allows adding', () => {
    expect(getConflictAlertType({ draft: ['b'], published: [] })).toBe(ConflictAlertTypeEnum.DRAFT);
    expect(ConflictAlertTypeEnum.DRAFT).toBe('info');
  });

  it('is undefined without conflicts', () => {
    expect(getConflictAlertType({ draft: [], published: [] })).toBeUndefined();
    expect(getConflictAlertType(undefined)).toBeUndefined();
  });
});
