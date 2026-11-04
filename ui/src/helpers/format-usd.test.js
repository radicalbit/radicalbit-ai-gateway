import { describe, expect, it } from 'vitest';
import formatUsd from './format-usd';

describe('formatUsd', () => {
  it('shows a budget of one billionth of a dollar exactly', () => {
    expect(formatUsd(0.000000001)).toBe('$0.000000001');
  });

  it('drops trailing zeros', () => {
    expect(formatUsd(12)).toBe('$12');
    expect(formatUsd(12.5)).toBe('$12.5');
    expect(formatUsd(1500.25)).toBe('$1,500.25');
  });

  it('shows a dash when there is no value', () => {
    expect(formatUsd(null)).toBe('-');
    expect(formatUsd(undefined)).toBe('-');
  });

  it('shows zero as $0', () => {
    expect(formatUsd(0)).toBe('$0');
  });

  it('rounds float noise from summed costs to nine decimals', () => {
    expect(formatUsd(0.1 + 0.2)).toBe('$0.3');
  });
});
