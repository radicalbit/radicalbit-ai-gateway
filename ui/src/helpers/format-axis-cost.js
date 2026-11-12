// A y-axis tick on a cost chart. From $1 up, two decimals. Below $1, up to three significant digits
// without trailing zeros, so ticks stay distinct at any scale: $0.005, $0.01 or $0.00000005, $0.0000001.
const AXIS_COST_FORMAT = new Intl.NumberFormat('en-US', {
  currency: 'USD', maximumFractionDigits: 2, minimumFractionDigits: 2, style: 'currency',
});

const SMALL_AXIS_COST_FORMAT = new Intl.NumberFormat('en-US', {
  currency: 'USD', maximumSignificantDigits: 3, style: 'currency',
});

const formatAxisCost = (value) => {
  const num = Number(value);

  if (Math.abs(num) < 1) {
    return SMALL_AXIS_COST_FORMAT.format(num);
  }

  return AXIS_COST_FORMAT.format(num);
};

export default formatAxisCost;
