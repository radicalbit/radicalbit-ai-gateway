const GATEWAY_OWNER = 'gateway';
const pageSize = 20;
const tracesPageSize = 50;
const startPage = 1;
const MAX_DECIMAL_ROUND = 3;
const DEFAULT_POLLING_INTERVAL = 2000;
const STATUS_SELECTOR_MAX_LEN = 10;
const TRUNCATE_LENGTH = STATUS_SELECTOR_MAX_LEN + 3;

const ModalsEnum = {
  QUERY_NAME: 'modal',
};

const PathsEnum = {
  CONFIG: 'config',
  COSTS: 'costs',
  GROUPS: 'groups',
  CREDENTIALS: 'credentials',
  PROJECTS: 'projects',
  ROUTES: 'routes',
  TRACING: 'tracing',
  USAGE: 'usage',
};

const SEARCH_PARAMS = {
  routes: 'searchRoute',
  groups: 'searchGroup',
  credentials: 'searchCredential',
  projects: 'searchProject',
};

const SortOrderEnum = {
  ASCEND: 'ascend',
  DESCEND: 'descend',
};

const NamespaceEnum = {};

const NUMBER_FORMATTER_STYLE_ENUM = {
  DECIMAL: 'decimal',
  PERCENT: 'percent',
};

const defaultNumberFormatter = {
  maximumSignificantDigits: MAX_DECIMAL_ROUND,
  style: NUMBER_FORMATTER_STYLE_ENUM.DECIMAL,
};

const userLocale = navigator.languages && navigator.languages.length
  ? navigator.languages[0]
  : navigator.language || 'en-US';

const numberFormatter = (options = defaultNumberFormatter) => new Intl.NumberFormat(userLocale, options);
const numberFormatterInt = (number) => {
  if (number === null || number === undefined) {
    return undefined;
  }

  return new Intl.NumberFormat(userLocale, { maximumFractionDigits: 0 }).format(number);
};

const numberFormatterFloat = (number, options = {}) => {
  if (number === null || number === undefined) {
    return undefined;
  }

  return new Intl.NumberFormat(userLocale, { maximumFractionDigits: 2, minimumFractionDigits: 2, ...options }).format(number);
};

const echartNumberFormatter = (options = defaultNumberFormatter) => new Intl.NumberFormat('en-US', options);

const CHART_COLORS = ['#3E75D8', '#4C95A4', '#F1B143', '#EF9337', '#84929E', '#70A268', '#467EA8', '#1D15B1', '#9242A5'];

const DATE_FORMAT = ' DD MMM YYYY, HH:mm:ss';

export {
  CHART_COLORS,
  DATE_FORMAT,
  DEFAULT_POLLING_INTERVAL,
  GATEWAY_OWNER,
  echartNumberFormatter,
  SEARCH_PARAMS,
  MAX_DECIMAL_ROUND,
  ModalsEnum,
  NamespaceEnum,
  NUMBER_FORMATTER_STYLE_ENUM,
  numberFormatter,
  numberFormatterInt,
  numberFormatterFloat,
  pageSize,
  PathsEnum,
  SortOrderEnum,
  startPage,
  STATUS_SELECTOR_MAX_LEN,
  tracesPageSize,
  TRUNCATE_LENGTH,
};
