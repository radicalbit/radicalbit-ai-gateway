import { describe, expect, it } from 'vitest';
import {
  filterBudgetsByStatus, formatNoBudgetMatches, formatNoRouteMatches, parseWindowStatuses,
} from './helpers';

const LIMITS = [{ uuid: 'daily' }, { uuid: 'weekly' }, { uuid: 'monthly' }];

const CONSUMPTION = {
  daily: { windowStatus: 'ok' },
  weekly: { windowStatus: 'warning' },
  monthly: { windowStatus: 'critical' },
};

describe('filterBudgetsByStatus', () => {
  it('keeps every budget when no status is selected', () => {
    expect(filterBudgetsByStatus({ limits: LIMITS, consumption: CONSUMPTION, windowStatuses: [] })).toEqual(LIMITS);
  });

  it('keeps only the budgets whose status is selected', () => {
    expect(filterBudgetsByStatus({ limits: LIMITS, consumption: CONSUMPTION, windowStatuses: ['warning', 'critical'] }))
      .toEqual([{ uuid: 'weekly' }, { uuid: 'monthly' }]);
  });

  it('keeps every budget until the consumption stream arrives', () => {
    expect(filterBudgetsByStatus({ limits: LIMITS, consumption: null, windowStatuses: ['critical'] })).toEqual(LIMITS);
  });
});

describe('formatNoBudgetMatches', () => {
  it('names the budgets count and the selected statuses', () => {
    expect(formatNoBudgetMatches({ count: 3, windowStatuses: ['warning', 'critical'] }))
      .toBe("None of this project's 3 budgets is Warning or Critical right now. Change the Limit status filter to see them.");
  });

  it('reads a single budget in the singular', () => {
    expect(formatNoBudgetMatches({ count: 1, windowStatuses: ['critical'] }))
      .toBe("None of this project's 1 budget is Critical right now. Change the Limit status filter to see them.");
  });

  it('names the statuses from Normal to Critical whatever the selection order', () => {
    expect(formatNoBudgetMatches({ count: 2, windowStatuses: ['critical', 'ok', 'warning'] }))
      .toBe("None of this project's 2 budgets is Normal, Warning or Critical right now. Change the Limit status filter to see them.");
  });
});

describe('formatNoRouteMatches', () => {
  it('names the selected statuses without a routes count', () => {
    expect(formatNoRouteMatches(['warning', 'critical']))
      .toBe('No route is Warning or Critical right now. Change the Limit status filter to see them.');
  });
});

describe('parseWindowStatuses', () => {
  it('reads the statuses of the URL parameter', () => {
    expect(parseWindowStatuses('warning,critical')).toEqual(['warning', 'critical']);
  });

  it('reads no status when the parameter is missing', () => {
    expect(parseWindowStatuses(null)).toEqual([]);
  });

  it('ignores the statuses it does not know', () => {
    expect(parseWindowStatuses('high,warning')).toEqual(['warning']);
  });
});
