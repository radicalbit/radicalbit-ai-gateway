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

// Categorical palette for echarts series — design-system "Visualization Colors"
// (charts + tags), Light row, in Chart 1->8 order.
const CHART_COLORS = ['#00E6C7', '#B61CD4', '#00A35C', '#D16900', '#006FFA', '#F33D23', '#ED32B9', '#FF8C00'];

const DATE_FORMAT = ' DD MMM YYYY, HH:mm:ss';

const DATE_FORMAT_SHORT = ' DD MMM YYYY';

const ConfigStatusEnum = {
  DRAFT: 'DRAFT',
  READY_TO_SERVE: 'READY_TO_SERVE',
  SERVED: 'SERVED',
};

const SlotEnum = {
  A: 'A',
  B: 'B',
};

const ProjectStatusEnum = {
  DEV: 'DEV',
  PROD: 'PROD',
};

export {
  ConfigStatusEnum,
  CHART_COLORS,
  DATE_FORMAT,
  DATE_FORMAT_SHORT,
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
  ProjectStatusEnum,
  SlotEnum,
  SortOrderEnum,
  startPage,
  STATUS_SELECTOR_MAX_LEN,
  tracesPageSize,
  TRUNCATE_LENGTH,
};
