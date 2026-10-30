import { EXPIRED_LIMITS_MESSAGE, LIMIT_CATEGORY_LABELS, WINDOW_TYPE_LABELS } from '@Components/limits/constants';
import { formatLimitWindow } from '@Components/limits/helpers';
import { getMessageFromQueryError } from '@Helpers/errors';

const METHOD_NOT_ALLOWED = 405;

const getLimitLabel = ({ algorithm, category, windowSize } = {}) => `${LIMIT_CATEGORY_LABELS[category]} ${formatLimitWindow(windowSize)} · ${WINDOW_TYPE_LABELS[algorithm]}`;

const getErrorMessage = (queryError) => {
  if (queryError?.status === METHOD_NOT_ALLOWED) {
    return EXPIRED_LIMITS_MESSAGE;
  }

  const detail = queryError?.data?.detail;

  if (Array.isArray(detail) && detail.length) {
    return detail[0].msg.replace(/^Value error, /, '');
  }

  return getMessageFromQueryError(queryError);
};

export { getErrorMessage, getLimitLabel };
