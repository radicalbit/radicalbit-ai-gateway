import { describe, expect, it } from 'vitest';
import formatAxisCost from './format-axis-cost';

describe('formatAxisCost', () => {
  it('shows zero as $0', () => {
    expect(formatAxisCost(0)).toBe('$0');
  });

  it('keeps cent-scale ticks distinct', () => {
    expect(formatAxisCost(0.005)).toBe('$0.005');
    expect(formatAxisCost(0.01)).toBe('$0.01');
    expect(formatAxisCost(0.035)).toBe('$0.035');
  });

  it('keeps ticks far below a cent distinct', () => {
    expect(formatAxisCost(0.00000005)).toBe('$0.00000005');
    expect(formatAxisCost(0.0000001)).toBe('$0.0000001');
    expect(formatAxisCost(1.5000000000000002e-7)).toBe('$0.00000015');
  });

  it('shows ticks from $1 up with two decimals', () => {
    expect(formatAxisCost(1)).toBe('$1.00');
    expect(formatAxisCost(2.5)).toBe('$2.50');
    expect(formatAxisCost(1500)).toBe('$1,500.00');
  });

  it('accepts the string value ECharts may pass', () => {
    expect(formatAxisCost('0.02')).toBe('$0.02');
  });
});
