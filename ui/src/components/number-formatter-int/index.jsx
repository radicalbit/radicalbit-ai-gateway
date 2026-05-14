function NumberFormatterInt({ value }) {
  const formatted = new Intl.NumberFormat(undefined, {
    maximumFractionDigits: 0,
  }).format(value);

  return formatted;
}

export default NumberFormatterInt;
