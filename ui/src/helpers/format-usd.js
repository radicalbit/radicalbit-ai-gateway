const USD_FORMAT = new Intl.NumberFormat('en-US', {
  currency: 'USD', maximumFractionDigits: 9, minimumFractionDigits: 0, style: 'currency',
});

const formatUsd = (value) => {
  if (value == null) {
    return '-';
  }

  return USD_FORMAT.format(value);
};

export default formatUsd;
