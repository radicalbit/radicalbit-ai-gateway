import { LimitCategoryEnum, WINDOW_TYPE_LABELS } from '@Components/limits/constants';
import { formatLimitValue, formatLimitWindow } from '@Components/limits/helpers';
import { getMessageFromQueryError } from '@Helpers/errors';

const getBudgetLabel = ({ algorithm, value, windowSize } = {}) => `${formatLimitValue(LimitCategoryEnum.BUDGET, value)} / ${formatLimitWindow(windowSize)} · ${WINDOW_TYPE_LABELS[algorithm]}`;

const getErrorMessage = (queryError) => {
  const detail = queryError?.data?.detail;

  if (Array.isArray(detail) && detail.length) {
    return detail[0].msg.replace(/^Value error, /, '');
  }

  return getMessageFromQueryError(queryError);
};

export { getBudgetLabel, getErrorMessage };
