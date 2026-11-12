import { describe, expect, it } from 'vitest';
import formatCost from './format-cost';

describe('formatCost', () => {
  it('shows a cost with two decimals', () => {
    expect(formatCost(12)).toBe('$12.00');
    expect(formatCost(12.5)).toBe('$12.50');
    expect(formatCost(1500.256)).toBe('$1,500.26');
  });

  it('shows a cost below one cent as < $0.01', () => {
    expect(formatCost(0.0030277)).toBe('< $0.01');
    expect(formatCost(0.000000001)).toBe('< $0.01');
  });

  it('rounds a cost of half a cent up to one cent', () => {
    expect(formatCost(0.005)).toBe('$0.01');
  });

  it('shows zero as $0.00', () => {
    expect(formatCost(0)).toBe('$0.00');
  });

  it('shows a dash when there is no value', () => {
    expect(formatCost(null)).toBe('-');
    expect(formatCost(undefined)).toBe('-');
  });
});
