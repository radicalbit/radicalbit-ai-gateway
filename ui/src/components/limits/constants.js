// Limits of a credential or a project, as the backend names them (models/credential_limiting.py)
export const LimitCategoryEnum = {
  REQUEST_RATE: 'request_rate',
  TOKEN_INPUT: 'token_input',
  TOKEN_OUTPUT: 'token_output',
  BUDGET: 'budget',
};

export const WindowTypeEnum = {
  FIXED: 'FIXED_WINDOW',
  ALIGNED: 'ALIGNED_FIXED_WINDOW',
};

export const LIMIT_CATEGORIES = [
  LimitCategoryEnum.REQUEST_RATE,
  LimitCategoryEnum.TOKEN_INPUT,
  LimitCategoryEnum.TOKEN_OUTPUT,
  LimitCategoryEnum.BUDGET,
];

export const LIMIT_CATEGORY_LABELS = {
  [LimitCategoryEnum.REQUEST_RATE]: 'Requests',
  [LimitCategoryEnum.TOKEN_INPUT]: 'Input tokens',
  [LimitCategoryEnum.TOKEN_OUTPUT]: 'Output tokens',
  [LimitCategoryEnum.BUDGET]: 'Budget',
};

export const MAX_LABELS = {
  [LimitCategoryEnum.REQUEST_RATE]: 'Max requests',
  [LimitCategoryEnum.TOKEN_INPUT]: 'Max tokens',
  [LimitCategoryEnum.TOKEN_OUTPUT]: 'Max tokens',
  [LimitCategoryEnum.BUDGET]: 'Max spend',
};

export const MAX_LABEL = 'Max';

export const WINDOW_TYPE_LABELS = {
  [WindowTypeEnum.FIXED]: 'Fixed',
  [WindowTypeEnum.ALIGNED]: 'Aligned',
};

export const WINDOW_TYPE_HELP = 'Fixed: the window starts at the first request and lasts its full length. Aligned: the window follows the UTC clock (1 day runs from midnight to midnight).';

// The windows the backend accepts (models/limiting.py), in its canonical form. An aligned window is at most one
// day long; a month is always 30 days.
export const LIMIT_WINDOWS = [
  { value: '1 minute', label: '1 min', aligned: true },
  { value: '5 minutes', label: '5 min', aligned: true },
  { value: '10 minutes', label: '10 min', aligned: true },
  { value: '15 minutes', label: '15 min', aligned: true },
  { value: '30 minutes', label: '30 min', aligned: true },
  { value: '1 hour', label: '1 h', aligned: true },
  { value: '2 hours', label: '2 h', aligned: true },
  { value: '3 hours', label: '3 h', aligned: true },
  { value: '4 hours', label: '4 h', aligned: true },
  { value: '6 hours', label: '6 h', aligned: true },
  { value: '8 hours', label: '8 h', aligned: true },
  { value: '12 hours', label: '12 h', aligned: true },
  { value: '1 day', label: '1 day', aligned: true },
  { value: '1 week', label: '1 week', aligned: false },
  { value: '1 month', label: '1 month (30 days)', aligned: false },
];

// How alert rules name each category in their events, e.g. `rate_limit-exceeded-1h`
export const LIMIT_EVENT_CATEGORIES = {
  [LimitCategoryEnum.REQUEST_RATE]: 'rate_limit',
  [LimitCategoryEnum.TOKEN_INPUT]: 'token_input_limit',
  [LimitCategoryEnum.TOKEN_OUTPUT]: 'token_output_limit',
  [LimitCategoryEnum.BUDGET]: 'budget_limit',
};

export const DUPLICATE_LIMIT_ERROR = 'A limit with the same category, window type and window already exists.';

export const DUPLICATE_ROW_ERROR = 'Same limit as a row above.';

export const EXPIRED_LIMITS_MESSAGE = 'This credential has expired: its limits can no longer be changed.';

// Nothing preselected: a default would read as a suggested configuration
export const EMPTY_LIMIT = {
  category: undefined,
  algorithm: undefined,
  windowSize: undefined,
  value: undefined,
};
