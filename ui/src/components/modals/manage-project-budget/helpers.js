import { LimitCategoryEnum, WINDOW_TYPE_LABELS } from '@Components/limits/constants';
import { formatLimitValue, formatLimitWindow } from '@Components/limits/helpers';
import { getMessageFromQueryError } from '@Helpers/errors';

const ConflictAlertTypeEnum = {
  PUBLISHED: 'warning',
  DRAFT: 'info',
};

const getConflictAlertType = ({ draft = [], published = [] } = {}) => {
  if (published.length) {
    return ConflictAlertTypeEnum.PUBLISHED;
  }

  if (draft.length) {
    return ConflictAlertTypeEnum.DRAFT;
  }

  return undefined;
};

const getBudgetLabel = ({ algorithm, value, windowSize } = {}) => `${formatLimitValue(LimitCategoryEnum.BUDGET, value)} / ${formatLimitWindow(windowSize)} · ${WINDOW_TYPE_LABELS[algorithm]}`;

const getErrorMessage = (queryError) => {
  const detail = queryError?.data?.detail;

  if (Array.isArray(detail) && detail.length) {
    return detail[0].msg.replace(/^Value error, /, '');
  }

  return getMessageFromQueryError(queryError);
};

export {
  ConflictAlertTypeEnum, getBudgetLabel, getConflictAlertType, getErrorMessage,
};
