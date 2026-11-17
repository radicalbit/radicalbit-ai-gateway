// A cost the gateway measured, rounded for reading: three decimals, and `< $0.001` for a cost that would round to zero.
// Budgets and limits use formatUsd instead: they show the value the user typed, exactly.
const COST_FORMAT = new Intl.NumberFormat('en-US', {
  currency: 'USD', maximumFractionDigits: 3, minimumFractionDigits: 3, style: 'currency',
});

const ZERO = COST_FORMAT.format(0);

const formatCost = (value) => {
  if (value == null) {
    return '-';
  }

  const formatted = COST_FORMAT.format(value);

  if (value !== 0 && formatted === ZERO) {
    return '< $0.001';
  }

  return formatted;
};

export default formatCost;
