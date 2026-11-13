import { describe, expect, it } from 'vitest';
import formatCost from './format-cost';

describe('formatCost', () => {
  it('shows a cost with three decimals', () => {
    expect(formatCost(12)).toBe('$12.000');
    expect(formatCost(12.5)).toBe('$12.500');
    expect(formatCost(1500.2564)).toBe('$1,500.256');
    expect(formatCost(0.0213)).toBe('$0.021');
  });

  it('shows a cost below a tenth of a cent as < $0.001', () => {
    expect(formatCost(0.0003027)).toBe('< $0.001');
    expect(formatCost(0.000000001)).toBe('< $0.001');
  });

  it('rounds a cost of half a tenth of a cent up to a tenth of a cent', () => {
    expect(formatCost(0.0005)).toBe('$0.001');
  });

  it('shows zero as $0.000', () => {
    expect(formatCost(0)).toBe('$0.000');
  });

  it('shows a dash when there is no value', () => {
    expect(formatCost(null)).toBe('-');
    expect(formatCost(undefined)).toBe('-');
  });
});
