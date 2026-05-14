const formatCurrency = (value) => {
  if (value == null) {
    return '-';
  }

  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
};

/**
 * Returns a formatted cost value.
 *
 * @param {Object} params - Parameters for label generation.
 * @param {number} params.cent - Cost in string.
 *
 * @returns {string} Formatted cost value.
 */
const costFormatter = ({ cent }) => {
  if (!cent) {
    return formatCurrency(cent);
  }

  const formatted = formatCurrency(cent);
  return formatted === '$0.00' ? '< $0.01' : formatted;
};

export default costFormatter;
